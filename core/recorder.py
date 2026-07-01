"""信号录制引擎：将原始电压采样累积并以 npz 格式落盘。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from .calibration import MagnetometerCalibration, calibration_to_npz_metadata


class Recorder:
    """线程安全的录制器。状态机: IDLE -> RECORDING -> IDLE。"""

    def __init__(self, output_dir: str = "raw_data") -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._start_time: float = 0.0
        self._sample_rate_hz: int = 2000
        self._channels: list[int] = []
        self._output_dir = output_dir

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self, channels: list[int], sample_rate_hz: int) -> None:
        with self._lock:
            if self._recording:
                return
            self._recording = True
            self._chunks = []
            self._start_time = time.time()
            self._sample_rate_hz = sample_rate_hz
            self._channels = list(channels)

    def feed(self, voltage_samples: np.ndarray) -> None:
        """在 pipeline 线程中被调用，追加新采样。"""
        with self._lock:
            if not self._recording:
                return
            if voltage_samples.size > 0:
                self._chunks.append(voltage_samples.copy())

    def stop_and_save(
        self,
        sensitivity_mv_per_ut: list[float],
        calibration: MagnetometerCalibration | None = None,
        calibration_enabled: bool = False,
    ) -> str:
        """停止录制并保存 npz。返回保存路径。"""
        with self._lock:
            if not self._recording:
                return ""
            self._recording = False
            chunks = self._chunks
            self._chunks = []
            start_time = self._start_time
            sample_rate = self._sample_rate_hz
            channels = self._channels

        if not chunks:
            return ""

        voltage = np.vstack(chunks)  # (N, n_channels)
        n_samples = voltage.shape[0]

        # 采样率均衡：若实际采样率非 2000Hz，重采样到 2000Hz
        target_rate = 2000
        if sample_rate != target_rate and sample_rate > 0:
            from scipy.signal import resample

            new_n = int(round(n_samples * target_rate / sample_rate))
            voltage = resample(voltage, new_n, axis=0)
            sample_rate = target_rate

        # 构建 UNIX 时间戳文件名：精确到微秒（6位小数）
        # 格式: raw_data/1780403603_060227
        ts_int = int(start_time)
        ts_frac = int(round((start_time - ts_int) * 1e6))
        filename = f"{ts_int}_{ts_frac:06d}"
        out_dir = Path(self._output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        filepath = out_dir / f"{filename}.npz"

        # 保存 npz
        np.savez_compressed(
            filepath,
            voltage=voltage.astype(np.float64),
            sample_rate_hz=np.int32(sample_rate),
            channels=np.array(channels, dtype=np.int16),
            start_timestamp=np.float64(start_time),
            sensitivity_mv_per_ut=np.array(sensitivity_mv_per_ut, dtype=np.float64),
            **calibration_to_npz_metadata(calibration, calibration_enabled),
        )
        return str(filepath)
