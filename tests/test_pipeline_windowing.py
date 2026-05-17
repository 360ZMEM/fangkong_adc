import queue
import threading

import numpy as np

import core.pipeline as pipeline_mod
from config.settings import AppConfig
from core.models import FftResult, LatestSnapshot, LockinResult
from core.pipeline import LatestDataStore, PipelineHandles, PipelineWorker
from core.ring_buffer import RingBuffer
from core.storage import DataStorage
from protocol.adc_decoder import encode_test_sample
from protocol.constants import CMD_READ_STREAM, REG_AD_STREAM
from protocol.frames import build_header, build_upload_wave_packet


def _poll_packet(raw_values: list[int], channel: int = 0) -> bytes:
    payload = b"".join(encode_test_sample(value, channel) for value in raw_values)
    return build_header(CMD_READ_STREAM, REG_AD_STREAM, len(payload)) + payload


def _upload_packet(
    pack_num: int,
    raw_values: list[int],
    channel: int = 0,
    sample_rate_hz: int = 2000,
) -> bytes:
    payload = b"".join(encode_test_sample(value, channel) for value in raw_values)
    return build_upload_wave_packet(
        pack_num=pack_num,
        sample_rate_hz=sample_rate_hz,
        channel_en=0x0001,
        payload=payload,
    )


def _worker(config: AppConfig) -> PipelineWorker:
    config.storage.enabled = False
    store = LatestDataStore(
        initial=LatestSnapshot(
            channels=list(config.device.active_channels),
            sample_rate_hz=config.device.sample_rate_hz,
        )
    )
    handles = PipelineHandles(
        ring_buffer=RingBuffer(
            capacity_samples=max(config.dsp.window_size_samples, 16),
            channel_count=len(config.device.active_channels),
        ),
        latest_store=store,
        storage=DataStorage(config.storage),
    )
    return PipelineWorker(config, queue.Queue(), threading.Event(), handles)


def test_pipeline_uses_fixed_window_and_fixed_sample_rate():
    cfg = AppConfig()
    cfg.device.active_channels = [0]
    cfg.dsp.window_size_samples = 4
    cfg.dsp.hop_size_samples = 2
    cfg.runtime.scope_total_window_ms = 200
    worker = _worker(cfg)

    for value in [100, 200, 300]:
        worker._handle_packet(_poll_packet([value]))
        worker._publish_snapshot()
        snapshot = worker.handles.latest_store.get()
        assert snapshot.sample_rate_hz == 2000
        assert snapshot.lockin == []

    worker._handle_packet(_poll_packet([400]))
    worker._publish_snapshot()
    snapshot = worker.handles.latest_store.get()
    assert snapshot.sample_rate_hz == 2000
    assert snapshot.waveform.shape == (4, 1)
    assert snapshot.lockin
    assert 0 in snapshot.fft.spectra


def test_pipeline_triggers_dsp_on_fixed_hops(monkeypatch):
    cfg = AppConfig()
    cfg.device.active_channels = [0]
    cfg.dsp.window_size_samples = 4
    cfg.dsp.hop_size_samples = 2
    worker = _worker(cfg)
    scale = 10.0 / float(1 << 23)
    fft_windows: list[np.ndarray] = []
    sample_rates: list[int] = []

    def fake_fft(samples: np.ndarray, sample_rate_hz: int, channels: list[int]) -> FftResult:
        fft_windows.append(samples.copy())
        sample_rates.append(sample_rate_hz)
        return FftResult(freqs=np.array([float(len(fft_windows))]), spectra={0: np.array([1.0])})

    def fake_lockin(
        samples: np.ndarray,
        sample_rate_hz: int,
        channels: list[int],
        frequency_hz: float,
    ) -> list[LockinResult]:
        return [
            LockinResult(
                channel=channels[0],
                frequency_hz=frequency_hz,
                amplitude=float(len(fft_windows)),
                phase_rad=0.0,
                i_component=0.0,
                q_component=0.0,
            )
        ]

    monkeypatch.setattr(pipeline_mod, "compute_fft", fake_fft)
    monkeypatch.setattr(pipeline_mod, "compute_lockin", fake_lockin)

    for value in [100, 200, 300, 400, 500, 600]:
        worker._handle_packet(_poll_packet([value]))
        worker._publish_snapshot()

    assert len(fft_windows) == 2
    assert sample_rates == [2000, 2000]
    assert np.allclose(fft_windows[0][:, 0], np.array([100, 200, 300, 400], dtype=np.float64) * scale)
    assert np.allclose(fft_windows[1][:, 0], np.array([300, 400, 500, 600], dtype=np.float64) * scale)
    snapshot = worker.handles.latest_store.get()
    assert snapshot.sample_rate_hz == 2000
    assert snapshot.lockin[0].amplitude == 2.0


def test_poll_mode_logs_packnum_limitation_once():
    cfg = AppConfig()
    cfg.device.active_channels = [0]
    worker = _worker(cfg)
    messages: list[str] = []
    worker.handles.storage.append_event = messages.append

    worker._handle_packet(_poll_packet([100]))
    worker._handle_packet(_poll_packet([200]))

    assert messages == ["Warning: poll 模式响应头不含 pack_num，无法做协议级丢包检测"]
    assert worker.stats.packet_loss_count == 0
    assert worker.stats.filled_sample_count == 0


def test_auto_upload_packet_loss_uses_zero_order_hold_fill():
    cfg = AppConfig()
    cfg.runtime.transport_mode = "auto_upload"
    cfg.device.active_channels = [0]
    cfg.dsp.window_size_samples = 2
    cfg.dsp.hop_size_samples = 1
    cfg.dsp.packet_loss_fill_mode = "zero_order_hold"
    worker = _worker(cfg)

    worker._handle_packet(_upload_packet(1, [100]))
    worker._handle_packet(_upload_packet(3, [300]))
    worker._publish_snapshot()

    latest = worker.handles.ring_buffer.latest(3)
    scale = 10.0 / float(1 << 23)
    assert worker.stats.packet_loss_count == 1
    assert worker.stats.filled_sample_count == 1
    assert latest.shape == (3, 1)
    assert np.allclose(latest[:, 0], [100 * scale, 100 * scale, 300 * scale])


def test_auto_upload_packet_loss_uses_zero_padding_fill():
    cfg = AppConfig()
    cfg.runtime.transport_mode = "auto_upload"
    cfg.device.active_channels = [0]
    cfg.dsp.window_size_samples = 2
    cfg.dsp.hop_size_samples = 1
    cfg.dsp.packet_loss_fill_mode = "zero_padding"
    worker = _worker(cfg)

    worker._handle_packet(_upload_packet(1, [100]))
    worker._handle_packet(_upload_packet(3, [300]))
    worker._publish_snapshot()

    latest = worker.handles.ring_buffer.latest(3)
    scale = 10.0 / float(1 << 23)
    assert worker.stats.packet_loss_count == 1
    assert worker.stats.filled_sample_count == 1
    assert latest.shape == (3, 1)
    assert np.allclose(latest[:, 0], [100 * scale, 0.0, 300 * scale])


def test_auto_upload_header_sample_rate_drives_snapshot():
    cfg = AppConfig()
    cfg.runtime.transport_mode = "auto_upload"
    cfg.device.active_channels = [0]
    cfg.dsp.window_size_samples = 2
    cfg.dsp.hop_size_samples = 1
    cfg.runtime.scope_total_window_ms = 1
    worker = _worker(cfg)

    worker._handle_packet(_upload_packet(1, [100], sample_rate_hz=4000))
    worker._handle_packet(_upload_packet(2, [200], sample_rate_hz=4000))
    worker._publish_snapshot()

    snapshot = worker.handles.latest_store.get()
    scale = 10.0 / float(1 << 23)
    assert snapshot.sample_rate_hz == 4000
    assert worker.stats.packet_loss_count == 0
    assert worker.stats.filled_sample_count == 0
    assert snapshot.waveform.shape == (2, 1)
    assert np.allclose(snapshot.waveform[:, 0], [100 * scale, 200 * scale])
