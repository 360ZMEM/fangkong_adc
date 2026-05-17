from __future__ import annotations

import numpy as np

from .models import FftResult


def compute_fft(samples: np.ndarray, sample_rate_hz: int, channels: list[int]) -> FftResult:
    if samples.size == 0 or len(samples) < 2:
        return FftResult()
    arr = np.asarray(samples, dtype=np.float64)
    n = arr.shape[0]
    window = np.hanning(n)
    coherent_gain = max(window.mean(), 1e-12)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    spectra: dict[int, np.ndarray] = {}
    for idx, channel in enumerate(channels):
        y = arr[:, idx] - np.mean(arr[:, idx])
        spec = np.abs(np.fft.rfft(y * window)) * 2.0 / (n * coherent_gain)
        spectra[channel] = spec
    return FftResult(freqs=freqs, spectra=spectra)
