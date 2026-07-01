"""
九参数磁传感器标定脚本。

操作流程:
1. 在远离明显铁磁干扰的位置启动采集。
2. 点击上位机“信号录制”，缓慢转动传感器，使三轴姿态尽可能覆盖完整球面。
3. 停止录制，得到 raw_data/{timestamp}.npz。
4. 运行:
   python scripts/calibrate_magnetometer.py raw_data/1780403603_060227.npz
5. 在上位机点击“加载九参数标定”，选择生成的 calibration_profiles/*.json。

说明:
- 标定拟合对象是由原始电压按三轴灵敏度换算得到的磁感应强度。
- 原始 npz 数据不会被覆盖。
- 若存在局部铁磁干扰，应重新选择环境采集标定数据，不建议把干扰当作传感器误差拟合掉。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np

# ============================================================
# 用户可修改变量（在此区域集中配置）
# ============================================================

# 标定名称，会进入 JSON 文件名和 profile 内容
CALIBRATION_NAME = "magnetometer_9param"

# 已知当地磁场模值 (μT)。未知时填 None，脚本会用采样数据自动估计尺度。
TARGET_MAGNITUDE_UT = None

# 抽点步长：数据量很大时可增大，例如 5 或 10，加快拟合。
FIT_DECIMATION = 1

# 输出图像目录（相对于标定 profile 所在目录）
FIGURE_SUBDIR = "figures"

# ============================================================
# 以下为脚本逻辑，一般无需修改
# ============================================================

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.calibration import (  # noqa: E402
    evaluate_calibration,
    fit_ellipsoid_calibration,
    profile_output_path,
    voltage_to_magnetic_field,
)


def resolve_npz_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists() and p.suffix == ".npz":
        return p
    candidate = Path("raw_data") / f"{arg}.npz"
    if candidate.exists():
        return candidate
    candidate = Path("raw_data") / arg
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"找不到录制文件: {arg}")


def load_npz(path: Path) -> tuple[np.ndarray, list[int], list[float]]:
    data = np.load(path, allow_pickle=False)
    voltage = data["voltage"]
    channels = data["channels"].tolist()
    sensitivity = data["sensitivity_mv_per_ut"].tolist()
    if voltage.shape[1] != 3:
        raise ValueError(f"九参数标定需要恰好 3 个通道，当前为 {voltage.shape[1]} 个")
    return voltage, channels, sensitivity


def set_axes_equal_3d(ax) -> None:
    limits = np.array([ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d()])
    centers = np.mean(limits, axis=1)
    radius = 0.5 * np.max(limits[:, 1] - limits[:, 0])
    ax.set_xlim3d([centers[0] - radius, centers[0] + radius])
    ax.set_ylim3d([centers[1] - radius, centers[1] + radius])
    ax.set_zlim3d([centers[2] - radius, centers[2] + radius])


def plot_clouds(raw: np.ndarray, corrected: np.ndarray, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(12, 5))
    fig.suptitle("Magnetometer Calibration: Before / After", fontname="Times New Roman")

    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax1.scatter(raw[:, 0], raw[:, 1], raw[:, 2], s=2, alpha=0.25)
    ax1.set_title("Before", fontname="Times New Roman")
    ax1.set_xlabel("X (μT)")
    ax1.set_ylabel("Y (μT)")
    ax1.set_zlabel("Z (μT)")
    set_axes_equal_3d(ax1)

    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    ax2.scatter(corrected[:, 0], corrected[:, 1], corrected[:, 2], s=2, alpha=0.25)
    ax2.set_title("After", fontname="Times New Roman")
    ax2.set_xlabel("X (μT)")
    ax2.set_ylabel("Y (μT)")
    ax2.set_zlabel("Z (μT)")
    set_axes_equal_3d(ax2)

    plt.tight_layout()
    fig.savefig(output_dir / "calibration_cloud.png", dpi=200)
    fig.savefig(output_dir / "calibration_cloud.pdf")

    fig2, ax = plt.subplots(1, 1, figsize=(10, 4))
    ax.plot(np.linalg.norm(raw, axis=1), linewidth=0.4, label="Before")
    ax.plot(np.linalg.norm(corrected, axis=1), linewidth=0.4, label="After")
    ax.set_title("|B| Consistency", fontname="Times New Roman")
    ax.set_xlabel("Sample Index", fontname="Times New Roman")
    ax.set_ylabel("|B| (μT)", fontname="Times New Roman")
    ax.grid(True, alpha=0.3)
    ax.legend(prop={"family": "Times New Roman"})
    plt.tight_layout()
    fig2.savefig(output_dir / "calibration_magnitude.png", dpi=200)
    fig2.savefig(output_dir / "calibration_magnitude.pdf")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    npz_path = resolve_npz_path(sys.argv[1])
    voltage, channels, sensitivity = load_npz(npz_path)
    magnetic = voltage_to_magnetic_field(voltage, sensitivity)
    fit_data = magnetic[:: max(1, int(FIT_DECIMATION))]

    print(f"加载录制文件: {npz_path}")
    print(f"样本数: {magnetic.shape[0]}, 拟合样本数: {fit_data.shape[0]}")
    print(f"通道: {channels}")
    print(f"灵敏度: {sensitivity} mV/μT")

    before = evaluate_calibration(fit_data)
    print(f"标定前 |B| RMS 残差: {before.rms_residual_ut:.4f} μT ({before.relative_rms_percent:.2f}%)")

    profile = fit_ellipsoid_calibration(
        fit_data,
        channels=channels,
        sensitivity_mv_per_ut=sensitivity,
        name=CALIBRATION_NAME,
        target_magnitude_ut=TARGET_MAGNITUDE_UT,
        notes=f"source_npz={npz_path}",
    )
    corrected = profile.apply(fit_data)
    after = evaluate_calibration(corrected)

    out_path = profile_output_path(profile.name, profile.created_at)
    profile.save(out_path)
    figure_dir = out_path.parent / FIGURE_SUBDIR
    plot_clouds(fit_data, corrected, figure_dir)

    print(f"标定后 |B| RMS 残差: {after.rms_residual_ut:.4f} μT ({after.relative_rms_percent:.2f}%)")
    print(f"标定文件已保存: {out_path}")
    print(f"验证图已保存: {figure_dir}")

    exit_code = _report_health(profile.health)

    print("下一步：回到上位机，点击“加载九参数标定”，选择该 JSON 文件并确认“启用标定”。")
    plt.show()
    sys.exit(exit_code)


_GRADE_LABEL = {
    "healthy": "健康 ✓",
    "acceptable": "合格 ~",
    "poor": "不足 ✗",
}


def _report_health(health: dict | None) -> int:
    """打印健康度报告，返回退出码：poor -> 2，acceptable -> 1，healthy -> 0。"""
    if not health:
        print("[健康度] 未生成健康度信息（旧版 profile）。")
        return 0

    grade = str(health.get("grade", "unknown"))
    score = float(health.get("score", 0.0))
    label = _GRADE_LABEL.get(grade, grade)

    print("─" * 60)
    print(f"[健康度] 总分 {score:5.1f} / 100  ·  等级: {label}")
    print(f"    样本数量        {health.get('sample_count', 0):>7d}    "
          f"得分 {health.get('sample_score', 0.0):5.1f}")
    print(f"    姿态球面覆盖率  {100.0 * float(health.get('coverage_ratio', 0.0)):>6.1f}%   "
          f"得分 {health.get('coverage_score', 0.0):5.1f}")
    print(f"    |B| 残差比例    {float(health.get('residual_percent', 0.0)):>6.2f}%   "
          f"得分 {health.get('residual_score', 0.0):5.1f}")
    print(f"    矩阵条件数      {float(health.get('condition_number', 0.0)):>7.2f}    "
          f"得分 {health.get('condition_score', 0.0):5.1f}")

    issues = health.get("issues") or []
    if issues:
        print("[健康度] 主要问题:")
        for item in issues:
            print(f"    - {item}")
    suggestions = health.get("suggestions") or []
    if suggestions:
        print("[健康度] 改进建议:")
        for item in suggestions:
            print(f"    - {item}")

    verdict = health.get("verdict")
    if verdict:
        print(f"[健康度] 判定: {verdict}")
    print("─" * 60)

    if grade == "poor":
        print("‼ 强烈建议重新采集一次标定数据后再使用本 profile。")
        return 2
    if grade == "acceptable":
        print("⚠ 本次数据可勉强使用，如场景对精度敏感建议重新采集。")
        return 1
    return 0


if __name__ == "__main__":
    main()
