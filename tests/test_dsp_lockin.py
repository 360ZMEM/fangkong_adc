import numpy as np

from core.dsp import compute_fft
from core.lockin import compute_lockin
from core.ring_buffer import RingBuffer


def test_lockin_50hz_sine_amplitude():
    fs = 2000
    t = np.arange(fs) / fs
    signal = 0.2 * np.cos(2 * np.pi * 50 * t)
    samples = signal.reshape(-1, 1)
    result = compute_lockin(samples, fs, [0], 50.0)[0]
    assert abs(result.amplitude - 0.2) < 0.01
    assert abs(result.phase_rad) < 0.05


def test_fft_peak_near_50hz():
    fs = 2000
    t = np.arange(fs) / fs
    samples = np.sin(2 * np.pi * 50 * t).reshape(-1, 1)
    fft = compute_fft(samples, fs, [0])
    peak = fft.freqs[np.argmax(fft.spectra[0])]
    assert abs(peak - 50) < 1.0


def test_ring_buffer_keeps_latest_samples():
    rb = RingBuffer(5, 1)
    rb.append(np.arange(10, dtype=float).reshape(-1, 1))
    latest = rb.latest()
    assert latest.shape == (5, 1)
    assert latest[:, 0].tolist() == [5, 6, 7, 8, 9]
