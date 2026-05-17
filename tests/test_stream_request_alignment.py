from config.settings import AppConfig
from core.acquisition_controller import AcquisitionController


def test_stream_request_bytes_align_to_active_channels():
    cfg = AppConfig()
    cfg.device.active_channels = [0, 1, 2]
    cfg.device.read_bytes_per_request = 1408
    controller = AcquisitionController(cfg)
    assert controller._effective_stream_request_bytes() == 1404


def test_stream_request_bytes_keep_aligned_value():
    cfg = AppConfig()
    cfg.device.active_channels = [0, 1, 2]
    cfg.device.read_bytes_per_request = 1404
    controller = AcquisitionController(cfg)
    assert controller._effective_stream_request_bytes() == 1404
