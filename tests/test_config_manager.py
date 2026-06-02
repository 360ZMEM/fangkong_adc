from pathlib import Path

from config.config_manager import load_merged_config, save_config
from config.settings import AppConfig


def test_load_merged_config(tmp_path: Path):
    default_path = tmp_path / "default.yaml"
    user_path = tmp_path / "user.yaml"
    default_path.write_text(
        "network:\n  host: '192.168.1.198'\ndevice:\n  sample_rate_hz: 2000\n  active_channels: [0, 1, 2]\n  total_channels: 16\n  adc_bits: 24\n  voltage_range: '+/-10V'\n  configure_voltage_range: false\n  read_bytes_per_request: 1408\nruntime:\n  auto_start: false\n  hide_window_on_auto_start: false\n  ui_refresh_hz: 30\nqueue:\n  raw_queue_max_chunks: 512\n  raw_queue_drop_policy: 'drop_oldest'\n  parser_batch_chunks: 16\n  warning_threshold_ratio: 0.8\ndsp:\n  fft_window_sec: 1.0\n  fft_overlap: 0.5\n  lockin_frequency_hz: 50.0\n  lockin_window_sec: 1.0\n  lockin_reference: 'software'\nstorage:\n  enabled: true\n  root_dir: 'data'\n  raw_npz_enabled: true\n  feature_csv_enabled: true\n  flush_interval_sec: 5.0\n",
        encoding="utf-8",
    )
    user_path.write_text(
        "network:\n  host: '127.0.0.1'\ndevice:\n  active_channels: [1, 2, 3]\n",
        encoding="utf-8",
    )
    cfg = load_merged_config(default_path, user_path)
    assert cfg.network.host == "127.0.0.1"
    assert cfg.device.active_channels == [1, 2, 3]
    assert cfg.device.sample_rate_hz == 2000


def test_save_config_roundtrip(tmp_path: Path):
    cfg = AppConfig()
    cfg.runtime.waveform_y_unit = "magnetic_field"
    cfg.device.sensor_sensitivity_mv_per_ut = [20.02, 19.98, 19.96]
    path = tmp_path / "user.yaml"
    save_config(cfg, path)
    assert path.exists()
    loaded = load_merged_config(path)
    assert loaded.runtime.waveform_y_unit == "magnetic_field"
    assert loaded.device.sensor_sensitivity_mv_per_ut == [20.02, 19.98, 19.96]
