from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from config.settings import AppConfig
from protocol.adc_decoder import ActiveChannelDecoder
from protocol.constants import REG_AD_STREAM
from protocol.frames import parse_header, parse_upload_wave_header
from protocol.stream_parser import SlidingByteBuffer
from .dsp import compute_fft
from .lockin import compute_lockin
from .models import FftResult, LatestSnapshot, LockinResult, ProcessingStats
from .ring_buffer import RingBuffer
from .storage import DataStorage


class LatestDataStore:
    def __init__(self, initial: LatestSnapshot) -> None:
        self._snapshot = initial
        self._lock = threading.Lock()

    def update(self, snapshot: LatestSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def get(self) -> LatestSnapshot:
        with self._lock:
            return self._snapshot


@dataclass
class PipelineHandles:
    ring_buffer: RingBuffer
    latest_store: LatestDataStore
    storage: DataStorage


class PipelineWorker(threading.Thread):
    """消费者线程：批量取队列、滑动缓冲解析、ADC 解码、FFT/Lock-in。"""

    def __init__(
        self,
        config: AppConfig,
        raw_queue: queue.Queue[bytes],
        stop_event: threading.Event,
        handles: PipelineHandles,
    ) -> None:
        super().__init__(name="PipelineWorker", daemon=True)
        self.config = config
        self.raw_queue = raw_queue
        self.stop_event = stop_event
        self.handles = handles
        self.transport_mode = config.runtime.transport_mode
        self.parser = SlidingByteBuffer(packet_mode=self.transport_mode)
        self.stats = ProcessingStats(configured_sample_rate_hz=config.device.sample_rate_hz)
        self.channel_decoder = ActiveChannelDecoder(
            active_channels=list(config.device.active_channels),
            voltage_range=10.0,
        )
        self._active_channels = list(config.device.active_channels)
        self._window_size_samples = config.dsp.window_size_samples
        self._hop_size_samples = config.dsp.hop_size_samples
        self._pending_since_last_dsp = 0
        self._last_fft = FftResult()
        self._last_lockin: list[LockinResult] = []
        self._source_sample_rate_hz = config.device.sample_rate_hz
        self._last_pack_num: int | None = None
        self._last_sample_vector: np.ndarray | None = None
        self._logged_poll_packnum_limitation = False

    def run(self) -> None:
        while not self.stop_event.is_set():
            chunks = self._get_batch()
            if not chunks:
                continue
            start = time.perf_counter()
            for chunk in chunks:
                self.parser.feed(chunk)
            for packet in self.parser.extract_packets():
                self._handle_packet(packet)
            self.stats.dsp_latency_ms = (time.perf_counter() - start) * 1000.0
            self._publish_snapshot()

    def _get_batch(self) -> list[bytes]:
        chunks: list[bytes] = []
        try:
            chunks.append(self.raw_queue.get(timeout=0.1))
        except queue.Empty:
            return chunks
        for _ in range(max(0, self.config.queue.parser_batch_chunks - 1)):
            try:
                chunks.append(self.raw_queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    def _handle_packet(self, packet: bytes) -> None:
        try:
            decoded = None
            if self.transport_mode == "poll":
                header = parse_header(packet)
                payload = packet[16:]
                if header.reg_addr != REG_AD_STREAM or not payload:
                    self.stats.packets += 1
                    return
                if not self._logged_poll_packnum_limitation:
                    self.handles.storage.append_event(
                        "Warning: poll 模式响应头不含 pack_num，无法做协议级丢包检测"
                    )
                    self._logged_poll_packnum_limitation = True
                decoded = self.channel_decoder.decode(payload)
            else:
                header = parse_upload_wave_header(packet)
                self._source_sample_rate_hz = max(1, int(header.sample_rate_hz or self._source_sample_rate_hz))
                self._fill_missing_packets(header.pack_num, header.data_num)
                payload = packet[52:]
                decoded = self.channel_decoder.decode(payload)

            if decoded is not None:
                self.stats.channel_mismatch_count += decoded.stats.channel_mismatch_count
                if decoded.voltages.size > 0:
                    self.handles.ring_buffer.append(decoded.voltages)
                    decoded_count = int(decoded.voltages.shape[0])
                    self._pending_since_last_dsp += decoded_count
                    self._last_sample_vector = decoded.voltages[-1].copy()
            self.stats.packets += 1
        except Exception:
            self.stats.parse_errors += 1

    def _publish_snapshot(self) -> None:
        sample_rate = max(1, int(self._source_sample_rate_hz))
        waveform_window_samples = max(
            1,
            int(round(sample_rate * self.config.runtime.scope_total_window_ms / 1000.0)),
        )
        plot_count = min(self.handles.ring_buffer.size, waveform_window_samples)
        waveform = self.handles.ring_buffer.latest(plot_count)
        if (
            self.handles.ring_buffer.size >= self._window_size_samples
            and self._pending_since_last_dsp >= self._hop_size_samples
        ):
            dsp_window = self.handles.ring_buffer.latest_window(self._window_size_samples)
            self._last_fft = compute_fft(dsp_window, sample_rate, self._active_channels)
            self._last_lockin = compute_lockin(
                dsp_window,
                sample_rate,
                self._active_channels,
                self.config.dsp.lockin_frequency_hz,
            )
            self._pending_since_last_dsp %= self._hop_size_samples
        snapshot = LatestSnapshot(
            # Wall-clock only for logs/storage; DSP timing always comes from sample_rate_hz.
            timestamp=time.time(),
            channels=list(self._active_channels),
            waveform=waveform,
            sample_rate_hz=sample_rate,
            fft=self._last_fft,
            lockin=self._last_lockin,
            queue_size=self.raw_queue.qsize(),
            stats=self.stats,
            status_message="采集中",
        )
        self.handles.latest_store.update(snapshot)
        self.handles.storage.maybe_write_snapshot(snapshot)

    def _fill_missing_packets(self, current_pack_num: int, data_num: int) -> None:
        if self._last_pack_num is None:
            self._last_pack_num = current_pack_num
            return
        expected = (self._last_pack_num + 1) & 0xFFFFFFFF
        if current_pack_num == expected:
            self._last_pack_num = current_pack_num
            return
        missing_packets = (current_pack_num - expected) & 0xFFFFFFFF
        if missing_packets == 0 or missing_packets >= 0x80000000:
            self._last_pack_num = current_pack_num
            return

        frame_bytes = max(1, len(self._active_channels) * 4)
        samples_per_packet = max(1, data_num // frame_bytes)
        fill_count = missing_packets * samples_per_packet
        fill_samples = self._build_fill_samples(fill_count)
        if fill_samples.size > 0:
            self.handles.ring_buffer.append(fill_samples)
            self._pending_since_last_dsp += fill_count
            self._last_sample_vector = fill_samples[-1].copy()
        self.stats.packet_loss_count += missing_packets
        self.stats.filled_sample_count += fill_count
        self.handles.storage.append_event(
            "Warning: auto_upload pack_num 不连续，"
            f"expected={expected}, actual={current_pack_num}, "
            f"missing_packets={missing_packets}, filled_samples={fill_count}"
        )
        self._last_pack_num = current_pack_num

    def _build_fill_samples(self, count: int) -> np.ndarray:
        if count <= 0:
            return np.empty((0, len(self._active_channels)), dtype=np.float64)
        if (
            self.config.dsp.packet_loss_fill_mode == "zero_order_hold"
            and self._last_sample_vector is not None
        ):
            return np.tile(self._last_sample_vector, (count, 1))
        return np.zeros((count, len(self._active_channels)), dtype=np.float64)
