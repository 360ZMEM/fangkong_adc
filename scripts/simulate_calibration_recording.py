"""
仿真九参数标定录制脚本（无需连接 TMR 传感器）。

用途:
    在没有真实传感器与磁场硬件的情况下，构造一段包含椭球畸变 + 三轴偏置 +
    轴间耦合 + 灵敏度失衡的 3 通道电压数据，落盘为一份与真实录制契约完全一致
    的 raw_data/{unix_timestamp}_{us}.npz 文件。生成的 npz 可以直接被
    scripts/calibrate_magnetometer.py 与 scripts/analyze_recording.py 读入，
    从而完整跑通「录制 → 标定 → 加载 → 验证」全流程。

物理模型:
    1. 在旋转姿态球面上均匀采样 (N 个方向)，代表用户手持传感器缓慢做 8 字动作
       时的姿态覆盖。
    2. 每个方向乘以一个"真实磁场模值" TRUE_FIELD_MAGNITUDE_UT，得到理想的
       B_true (μT)。
    3. 施加逆向标定畸变: B_raw = M_inv · B_true + bias，其中
         - M_inv 模拟传感器的椭球轴长不等 + 轴间投影 (九参数畸变来源);
         - bias  模拟硬铁偏移。
    4. 按各通道灵敏度将 μT 转换成传感器输出电压 (V):
         V = B_raw * (sensitivity_mv_per_ut / 1000)
    5. 叠加高斯噪声，模拟实际采集环境。

用法:
    python scripts/simulate_calibration_recording.py

    可在文件顶部集中修改仿真参数（畸变强度、噪声、样本点数等）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

# ============================================================
# 用户可修改变量（在此区域集中配置）
# ============================================================

# 采样率 (Hz)，与实际录制一致 (recorder.py 会重采样到 2000Hz)
SAMPLE_RATE_HZ = 2000

# 总采集时长 (秒)。旋转八字建议 30~60s，样本数 = SAMPLE_RATE_HZ * DURATION_SEC
DURATION_SEC = 30

# 当地真实磁场模值 (μT)。地磁在中国大部分地区约 45~55 μT。
TRUE_FIELD_MAGNITUDE_UT = 50.0

# 三轴灵敏度 (mV/μT)，与上位机默认配置保持一致
SENSITIVITY_MV_PER_UT = [20.02, 19.98, 19.96]

# 使用的通道编号
CHANNELS = [0, 1, 2]

# --- 椭球畸变参数（真值，用于反演验证）----------------------
# 三轴等效尺度：模拟不同通道对同一 μT 输出不同（生产偏差）
SCALE_XYZ = [1.10, 0.92, 1.05]
# 轴间耦合角 (弧度)：模拟三个传感器安装不完全正交
CROSS_COUPLING = [0.06, -0.04, 0.03]
# 硬铁偏置 (μT)：模拟传感器附近的直流磁性偏移
BIAS_UT = [3.0, -2.5, 1.8]

# --- 噪声与姿态覆盖 ------------------------------------------
# 每个电压通道叠加的高斯噪声标准差 (V)
NOISE_STD_V = 5e-5

# 姿态采样点数（在球面上均匀撒点后线性内插到 SAMPLE_RATE_HZ*DURATION_SEC）
POSE_SAMPLE_COUNT = 400

# 姿态覆盖比例 [0,1]：1 表示完整球面；小于 1 时缩到局部姿态（测欠采样）
POSE_COVERAGE = 1.0

# 输出目录，与 recorder 默认保持一致
OUTPUT_DIR = "raw_data"

# 是否输出到确定性时间戳（便于文档中引用同一文件名）
# True 时使用固定 UNIX 时间戳；False 使用当前时间
DETERMINISTIC_TIMESTAMP = True
FIXED_UNIX_TIMESTAMP = 1780000000.123456

# 随机数种子，保证可复现
RANDOM_SEED = 20260701

# ============================================================
# 以下为脚本逻辑，一般无需修改
# ============================================================


def fibonacci_sphere(n: int, coverage: float = 1.0) -> np.ndarray:
    """在单位球面上生成 n 个尽可能均匀的方向向量。coverage<1 时压缩极角范围。"""
    if n < 1:
        raise ValueError("POSE_SAMPLE_COUNT 必须 >= 1")
    indices = np.arange(0, n, dtype=np.float64) + 0.5
    # 覆盖比例通过限制 cos(theta) 范围实现，coverage=1 -> [-1,1]
    z_range = float(np.clip(coverage, 1e-3, 1.0))
    z = (1.0 - 2.0 * indices / n) * z_range
    phi = np.arccos(np.clip(z, -1.0, 1.0))
    theta = np.pi * (1.0 + 5.0**0.5) * indices
    x = np.sin(phi) * np.cos(theta)
    y = np.sin(phi) * np.sin(theta)
    return np.column_stack([x, y, z])


def build_forward_distortion(
    scale: list[float], cross: list[float], bias: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """构造 forward 畸变: B_raw = A @ B_true + bias。返回 (A, bias_arr)。

    A 由三轴 scale 与三个耦合角组合而成，非正交且各轴长不等，逆矩阵即为标定矩阵。
    """
    if len(scale) != 3 or len(cross) != 3 or len(bias) != 3:
        raise ValueError("SCALE_XYZ / CROSS_COUPLING / BIAS_UT 必须均为 3 元素列表")
    a, b, c = cross
    # 通过三个耦合角构造非正交基底
    e1 = np.array([1.0, 0.0, 0.0])
    e2 = np.array([np.sin(a), np.cos(a), 0.0])
    e3 = np.array([np.sin(b), np.sin(c) * np.cos(b), np.cos(c) * np.cos(b)])
    basis = np.column_stack([e1, e2, e3])  # 3x3
    scale_diag = np.diag(scale)
    A = basis @ scale_diag
    return A, np.asarray(bias, dtype=np.float64)


def synth_pose_stream(pose_count: int, coverage: float, n_samples: int) -> np.ndarray:
    """生成随时间平滑变化的姿态序列 (n_samples, 3)。"""
    poses = fibonacci_sphere(pose_count, coverage=coverage)
    # 随机打乱以模拟真实旋转轨迹（连续但不规则）
    rng = np.random.default_rng(RANDOM_SEED)
    rng.shuffle(poses, axis=0)
    # 线性插值到 n_samples 长度
    src_idx = np.linspace(0.0, 1.0, pose_count)
    tgt_idx = np.linspace(0.0, 1.0, n_samples)
    interp = np.column_stack(
        [np.interp(tgt_idx, src_idx, poses[:, k]) for k in range(3)]
    )
    # 重新归一到单位球面，防止插值后模值漂移
    norms = np.linalg.norm(interp, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return interp / norms


def synthesize_voltage() -> tuple[np.ndarray, dict]:
    """按照物理模型合成畸变电压数据，并返回相关元信息用于诊断。"""
    n_samples = int(round(SAMPLE_RATE_HZ * DURATION_SEC))
    if n_samples < 100:
        raise ValueError("DURATION_SEC 与 SAMPLE_RATE_HZ 组合过小，样本数不足以标定")

    A, bias = build_forward_distortion(SCALE_XYZ, CROSS_COUPLING, BIAS_UT)

    directions = synth_pose_stream(POSE_SAMPLE_COUNT, POSE_COVERAGE, n_samples)
    b_true = directions * TRUE_FIELD_MAGNITUDE_UT  # (N,3) 理想球面
    b_raw = b_true @ A.T + bias  # (N,3) 畸变后 μT

    if len(SENSITIVITY_MV_PER_UT) != 3:
        raise ValueError("SENSITIVITY_MV_PER_UT 必须是 3 元素列表")
    sens_v_per_ut = np.array(SENSITIVITY_MV_PER_UT, dtype=np.float64) / 1000.0
    voltage = b_raw * sens_v_per_ut  # V

    rng = np.random.default_rng(RANDOM_SEED + 1)
    voltage = voltage + rng.normal(0.0, NOISE_STD_V, size=voltage.shape)

    diagnostics = {
        "A_forward": A,
        "bias_ut": bias,
        "true_magnitude_ut": TRUE_FIELD_MAGNITUDE_UT,
        "raw_rms_percent": float(
            100.0
            * np.std(np.linalg.norm(b_raw, axis=1))
            / max(TRUE_FIELD_MAGNITUDE_UT, 1e-9)
        ),
    }
    return voltage, diagnostics


def build_output_path(start_time: float) -> Path:
    ts_int = int(start_time)
    ts_frac = int(round((start_time - ts_int) * 1e6))
    filename = f"{ts_int}_{ts_frac:06d}.npz"
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / filename


def save_recording(voltage: np.ndarray, start_time: float) -> Path:
    """按照 core/recorder.py 中的 npz 字段契约保存。"""
    filepath = build_output_path(start_time)

    # 与 recorder.py 保持一致的字段（不包含 calibration_* 因为原始录制默认无标定）
    np.savez_compressed(
        filepath,
        voltage=voltage.astype(np.float64),
        sample_rate_hz=np.int32(SAMPLE_RATE_HZ),
        channels=np.array(CHANNELS, dtype=np.int16),
        start_timestamp=np.float64(start_time),
        sensitivity_mv_per_ut=np.array(SENSITIVITY_MV_PER_UT, dtype=np.float64),
        calibration_enabled=np.bool_(False),
        calibration_name=np.array("", dtype="<U1"),
        calibration_bias_ut=np.empty(0, dtype=np.float64),
        calibration_matrix=np.empty((0, 0), dtype=np.float64),
    )
    return filepath


def main() -> int:
    voltage, diag = synthesize_voltage()
    start_time = FIXED_UNIX_TIMESTAMP if DETERMINISTIC_TIMESTAMP else time.time()
    filepath = save_recording(voltage, start_time)

    print("=" * 60)
    print("仿真录制文件已生成")
    print("=" * 60)
    print(f"  路径:        {filepath}")
    print(f"  样本数:      {voltage.shape[0]}")
    print(f"  采样率:      {SAMPLE_RATE_HZ} Hz")
    print(f"  时长:        {DURATION_SEC} s")
    print(f"  真实 |B|:    {diag['true_magnitude_ut']:.2f} μT")
    print(f"  畸变前 RMS: {diag['raw_rms_percent']:.2f} % (体现椭球扭曲程度)")
    print()
    print("下一步：")
    print(f"  python scripts/calibrate_magnetometer.py {filepath}")
    print("  执行完毕后 calibration_profiles/ 下会生成 JSON，")
    print('  在上位机点击"加载九参数标定"并勾选"启用标定"即可完成闭环验证。')
    return 0


if __name__ == "__main__":
    sys.exit(main())
