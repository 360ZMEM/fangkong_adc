from __future__ import annotations

from dataclasses import dataclass, field
import time

import numpy as np

from network.reconnect_state import ConnectionState


@dataclass
class LockinResult:
    channel: int
    frequency_hz: float
    amplitude: float
    phase_rad: float
    i_component: float
    q_component: float


@dataclass
class FftResult:
    freqs: np.ndarray = field(default_factory=lambda: np.empty(0))
    spectra: dict[int, np.ndarray] = field(default_factory=dict)


@dataclass
class ProcessingStats:
    packets: int = 0
    parse_errors: int = 0
    channel_mismatch_count: int = 0
    dropped_chunks: int = 0
    dsp_latency_ms: float = 0.0
    bytes_received: int = 0
    recv_rate_bytes_per_sec: float = 0.0
    configured_sample_rate_hz: int = 2000
    packet_loss_count: int = 0
    filled_sample_count: int = 0


@dataclass
class LatestSnapshot:
    timestamp: float = field(default_factory=time.time)
    state: ConnectionState = ConnectionState.DISCONNECTED
    channels: list[int] = field(default_factory=lambda: [0, 1, 2])
    waveform: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    sample_rate_hz: int = 2000
    fft: FftResult = field(default_factory=FftResult)
    lockin: list[LockinResult] = field(default_factory=list)
    queue_size: int = 0
    stats: ProcessingStats = field(default_factory=ProcessingStats)
    status_message: str = "未连接"
    mode: str = "Debug"
    warning_message: str = ""
