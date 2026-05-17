import time
from pathlib import Path

from config.config_manager import load_config
from core.acquisition_controller import AcquisitionController
from network.mock_sk2301_server import MockSk2301Server


def test_controller_can_run_against_mock_server(tmp_path: Path):
    server = MockSk2301Server()
    server.start()
    host, port = server.endpoint
    try:
        cfg = load_config("config/default_config.yaml")
        cfg.network.host = host
        cfg.network.port = port
        cfg.storage.root_dir = str(tmp_path / "data")
        cfg.storage.flush_interval_sec = 0.01
        cfg.dsp.window_size_samples = 256
        cfg.dsp.hop_size_samples = 64
        controller = AcquisitionController(cfg)

        controller._connect_impl()
        assert controller.state.name == "CONNECTED"

        controller._configure_impl()
        assert controller.state.name == "CONNECTED"

        controller._start_impl()
        deadline = time.time() + 1.5
        while time.time() < deadline:
            snapshot = controller.get_latest_snapshot()
            if snapshot.waveform.size > 0 and snapshot.lockin:
                break
            time.sleep(0.05)

        snapshot = controller.get_latest_snapshot()
        assert snapshot.waveform.size > 0
        assert snapshot.waveform.shape[1] == 3
        assert snapshot.lockin
        assert snapshot.stats.packets > 0
        assert snapshot.stats.channel_mismatch_count == 0
        controller._stop_impl()
    finally:
        server.stop()


def test_controller_auto_upload_mode_against_mock_server(tmp_path: Path):
    server = MockSk2301Server()
    server.start()
    host, port = server.endpoint
    try:
        cfg = load_config("config/default_config.yaml")
        cfg.network.host = host
        cfg.network.port = port
        cfg.runtime.transport_mode = "auto_upload"
        cfg.storage.root_dir = str(tmp_path / "data")
        cfg.storage.flush_interval_sec = 0.01
        cfg.dsp.window_size_samples = 256
        cfg.dsp.hop_size_samples = 64
        controller = AcquisitionController(cfg)

        controller._connect_impl()
        controller._configure_impl()
        controller._start_impl()

        deadline = time.time() + 1.5
        while time.time() < deadline:
            snapshot = controller.get_latest_snapshot()
            if snapshot.waveform.size > 0 and snapshot.lockin:
                break
            time.sleep(0.05)

        snapshot = controller.get_latest_snapshot()
        assert snapshot.waveform.size > 0
        assert snapshot.sample_rate_hz == cfg.device.sample_rate_hz
        assert snapshot.stats.packet_loss_count == 0
        controller._stop_impl()
    finally:
        server.stop()
