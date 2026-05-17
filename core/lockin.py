from __future__ import annotations

import math

import numpy as np

from .models import LockinResult


def compute_lockin(
    samples: np.ndarray,
    sample_rate_hz: int,
    channels: list[int],
    frequency_hz: float = 50.0,
) -> list[LockinResult]:
    if samples.size == 0:
        return []
    arr = np.asarray(samples, dtype=np.float64)
    n = arr.shape[0]
    if n < 2:
        return []
    t = np.arange(n, dtype=np.float64) / float(sample_rate_hz)
    cos_ref = np.cos(2.0 * np.pi * frequency_hz * t)
    sin_ref = np.sin(2.0 * np.pi * frequency_hz * t)
    results: list[LockinResult] = []
    for idx, channel in enumerate(channels):
        y = arr[:, idx] - np.mean(arr[:, idx])
        i_component = float(np.mean(y * cos_ref))
        q_component = float(np.mean(y * sin_ref))
        amplitude = 2.0 * math.hypot(i_component, q_component)
        phase = math.atan2(q_component, i_component)
        results.append(
            LockinResult(channel, frequency_hz, amplitude, phase, i_component, q_component)
        )
    return results
