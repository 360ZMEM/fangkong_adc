"""
离线分析脚本：读取录制的 npz 文件，完成电压→磁场转换、FFT、锁相放大，
并以多 matplotlib 窗口同时弹出展示，保存为 PNG + PDF 双格式。

用法:
    python scripts/analyze_recording.py <npz文件路径或UNIX时间戳标记>

示例:
    python scripts/analyze_recording.py raw_data/1780403603_060227.npz
    python scripts/analyze_recording.py 1780403603_060227
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

# ============================================================
# 用户可修改变量（在此区域集中配置）
# ============================================================

# 三轴传感器灵敏度 (mV/μT)，对应 CH1, CH2, CH3
SENSITIVITY_MV_PER_UT = [20.02, 19.98, 19.96]

# 锁相放大目标频率 (Hz)
LOCKIN_FREQUENCY_HZ = 50.0

# 统一采样率 (Hz)，用于显示和计算
DISPLAY_SAMPLE_RATE_HZ = 2000

# FFT 窗口长度 (秒)
FFT_WINDOW_SEC = 1.0

# 锁相放大滑动窗口长度 (秒)
LOCKIN_WINDOW_SEC = 1.0

# 锁相放大滑动步长 (秒)
LOCKIN_HOP_SEC = 0.05

# 图片输出目录（相对于 npz 文件所在目录）
OUTPUT_SUBDIR = "figures"

# 通道标签
CHANNEL_LABELS = ["CH1 (X)", "CH2 (Y)", "CH3 (Z)"]

# ============================================================
# 以下为脚本逻辑，一般无需修改
# ============================================================

# 将项目根目录加入 sys.path 以便引用核心算法
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.dsp import compute_fft  # noqa: E402
from core.lockin import compute_lockin  # noqa: E402


def resolve_npz_path(arg: str) -> Path:
    """根据传入参数解析 npz 文件路径。"""
    p = Path(arg)
    if p.exists() and p.suffix == ".npz":
        return p
    # 尝试在 raw_data/ 目录下查找
    candidate = Path("raw_data") / f"{arg}.npz"
    if candidate.exists():
        return candidate
    candidate = Path("raw_data") / arg
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"找不到 npz 文件: {arg}")


def load_recording(path: Path) -> dict:
    """加载 npz 录制文件。"""
    data = np.load(path, allow_pickle=False)
    voltage = data["voltage"]  # (N, n_channels)
    sample_rate_hz = int(data["sample_rate_hz"])
    channels = data["channels"].tolist()
    start_timestamp = float(data["start_timestamp"])
    sensitivity = data["sensitivity_mv_per_ut"].tolist() if "sensitivity_mv_per_ut" in data else SENSITIVITY_MV_PER_UT
    return {
        "voltage": voltage,
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "start_timestamp": start_timestamp,
        "sensitivity_mv_per_ut": sensitivity,
    }


def voltage_to_magnetic_field(voltage: np.ndarray, sensitivity_mv_per_ut: list[float]) -> np.ndarray:
    """电压 (V) 转磁感应强度 (μT)，按通道独立灵敏度。"""
    n_ch = voltage.shape[1]
    sens = np.array(
        [sensitivity_mv_per_ut[i % len(sensitivity_mv_per_ut)] for i in range(n_ch)],
        dtype=np.float64,
    )
    sens_v_per_ut = sens / 1000.0
    return voltage / sens_v_per_ut


def compute_sliding_lockin(
    voltage: np.ndarray,
    sample_rate_hz: int,
    channels: list[int],
    frequency_hz: float,
    window_sec: float,
    hop_sec: float,
) -> dict:
    """滑动窗口锁相放大，返回时间轴和各通道幅值/相位序列。"""
    n_samples = voltage.shape[0]
    window_samples = int(round(window_sec * sample_rate_hz))
    hop_samples = max(1, int(round(hop_sec * sample_rate_hz)))

    times = []
    amplitudes = {ch: [] for ch in channels}
    phases = {ch: [] for ch in channels}

    pos = 0
    while pos + window_samples <= n_samples:
        segment = voltage[pos: pos + window_samples]
        results = compute_lockin(segment, sample_rate_hz, channels, frequency_hz)
        t = (pos + window_samples / 2) / sample_rate_hz
        times.append(t)
        for r in results:
            amplitudes[r.channel].append(r.amplitude)
            phases[r.channel].append(r.phase_rad)
        pos += hop_samples

    return {
        "times": np.array(times),
        "amplitudes": {ch: np.array(v) for ch, v in amplitudes.items()},
        "phases": {ch: np.array(v) for ch, v in phases.items()},
    }


def plot_raw_signal(time_s: np.ndarray, magnetic: np.ndarray, channels: list[int], output_dir: Path):
    """绘制原始信号时域波形。"""
    fig, axes = plt.subplots(len(channels) + 1, 1, figsize=(12, 3 * (len(channels) + 1)), sharex=True)
    fig.suptitle("Raw Magnetic Field Signal", fontsize=14, fontname="Times New Roman")

    for idx, ch in enumerate(channels):
        label = CHANNEL_LABELS[idx] if idx < len(CHANNEL_LABELS) else f"CH{ch}"
        axes[idx].plot(time_s, magnetic[:, idx], linewidth=0.5)
        axes[idx].set_ylabel(f"{label} (μT)", fontname="Times New Roman")
        axes[idx].grid(True, alpha=0.3)

    # |B|
    mag = np.sqrt(np.sum(magnetic ** 2, axis=1))
    axes[-1].plot(time_s, mag, linewidth=0.5, color="black")
    axes[-1].set_ylabel("|B| (μT)", fontname="Times New Roman")
    axes[-1].set_xlabel("Time (s)", fontname="Times New Roman")
    axes[-1].grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(output_dir / "raw_signal.png", dpi=200)
    fig.savefig(output_dir / "raw_signal.pdf")
    return fig


def plot_fft_spectrum(voltage: np.ndarray, sample_rate_hz: int, channels: list[int], output_dir: Path):
    """绘制 FFT 频谱。"""
    fft_result = compute_fft(voltage, sample_rate_hz, channels)
    fig, axes = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes = [axes]
    fig.suptitle("FFT Spectrum", fontsize=14, fontname="Times New Roman")

    for idx, ch in enumerate(channels):
        label = CHANNEL_LABELS[idx] if idx < len(CHANNEL_LABELS) else f"CH{ch}"
        if ch in fft_result.spectra:
            axes[idx].semilogy(fft_result.freqs, fft_result.spectra[ch], linewidth=0.5)
        axes[idx].set_ylabel(f"{label} Amplitude", fontname="Times New Roman")
        axes[idx].grid(True, alpha=0.3)
        axes[idx].axvline(LOCKIN_FREQUENCY_HZ, color="red", linestyle="--", alpha=0.5, label=f"{LOCKIN_FREQUENCY_HZ} Hz")
        axes[idx].legend(prop={"family": "Times New Roman"})

    axes[-1].set_xlabel("Frequency (Hz)", fontname="Times New Roman")
    plt.tight_layout()
    fig.savefig(output_dir / "fft_spectrum.png", dpi=200)
    fig.savefig(output_dir / "fft_spectrum.pdf")
    return fig


def plot_lockin_results(lockin_data: dict, channels: list[int], output_dir: Path):
    """绘制锁相放大后的幅值和相位时域图。"""
    times = lockin_data["times"]
    amplitudes = lockin_data["amplitudes"]
    phases = lockin_data["phases"]

    # 幅值图
    fig_amp, axes_amp = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes_amp = [axes_amp]
    fig_amp.suptitle(f"Lock-in Amplitude @ {LOCKIN_FREQUENCY_HZ} Hz", fontsize=14, fontname="Times New Roman")

    for idx, ch in enumerate(channels):
        label = CHANNEL_LABELS[idx] if idx < len(CHANNEL_LABELS) else f"CH{ch}"
        if ch in amplitudes:
            axes_amp[idx].plot(times, amplitudes[ch], linewidth=0.8)
        axes_amp[idx].set_ylabel(f"{label} Amplitude (V)", fontname="Times New Roman")
        axes_amp[idx].grid(True, alpha=0.3)

    axes_amp[-1].set_xlabel("Time (s)", fontname="Times New Roman")
    plt.tight_layout()
    fig_amp.savefig(output_dir / "lockin_amplitude.png", dpi=200)
    fig_amp.savefig(output_dir / "lockin_amplitude.pdf")

    # 相位图
    fig_phase, axes_phase = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes_phase = [axes_phase]
    fig_phase.suptitle(f"Lock-in Phase @ {LOCKIN_FREQUENCY_HZ} Hz", fontsize=14, fontname="Times New Roman")

    for idx, ch in enumerate(channels):
        label = CHANNEL_LABELS[idx] if idx < len(CHANNEL_LABELS) else f"CH{ch}"
        if ch in phases:
            axes_phase[idx].plot(times, np.rad2deg(phases[ch]), linewidth=0.8)
        axes_phase[idx].set_ylabel(f"{label} Phase (°)", fontname="Times New Roman")
        axes_phase[idx].grid(True, alpha=0.3)

    axes_phase[-1].set_xlabel("Time (s)", fontname="Times New Roman")
    plt.tight_layout()
    fig_phase.savefig(output_dir / "lockin_phase.png", dpi=200)
    fig_phase.savefig(output_dir / "lockin_phase.pdf")

    return fig_amp, fig_phase


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    npz_path = resolve_npz_path(sys.argv[1])
    print(f"加载录制文件: {npz_path}")

    recording = load_recording(npz_path)
    voltage = recording["voltage"]
    sample_rate_hz = recording["sample_rate_hz"]
    channels = recording["channels"]
    sensitivity = recording["sensitivity_mv_per_ut"]

    print(f"  采样率: {sample_rate_hz} Hz")
    print(f"  通道: {channels}")
    print(f"  样本数: {voltage.shape[0]}")
    print(f"  时长: {voltage.shape[0] / sample_rate_hz:.2f} s")
    print(f"  灵敏度: {sensitivity} mV/μT")

    # 采样率均衡
    if sample_rate_hz != DISPLAY_SAMPLE_RATE_HZ:
        from scipy.signal import resample
        new_n = int(round(voltage.shape[0] * DISPLAY_SAMPLE_RATE_HZ / sample_rate_hz))
        voltage = resample(voltage, new_n, axis=0)
        sample_rate_hz = DISPLAY_SAMPLE_RATE_HZ
        print(f"  已重采样至 {sample_rate_hz} Hz, 新样本数: {voltage.shape[0]}")

    # 电压 → 磁感应强度
    magnetic = voltage_to_magnetic_field(voltage, sensitivity)

    # 时间轴
    n_samples = voltage.shape[0]
    time_s = np.arange(n_samples, dtype=np.float64) / sample_rate_hz

    # 输出目录
    output_dir = npz_path.parent / OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  图片输出目录: {output_dir}")

    # 绘图
    print("绘制原始信号...")
    plot_raw_signal(time_s, magnetic, channels, output_dir)

    print("绘制 FFT 频谱...")
    plot_fft_spectrum(voltage, sample_rate_hz, channels, output_dir)

    print("计算锁相放大...")
    lockin_data = compute_sliding_lockin(
        voltage, sample_rate_hz, channels,
        LOCKIN_FREQUENCY_HZ, LOCKIN_WINDOW_SEC, LOCKIN_HOP_SEC,
    )
    print("绘制锁相结果...")
    plot_lockin_results(lockin_data, channels, output_dir)

    print(f"完成！共生成 6 个图片文件（PNG + PDF）在 {output_dir}")
    plt.show()


if __name__ == "__main__":
    main()
