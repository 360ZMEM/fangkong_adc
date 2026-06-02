from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SUPPORTED_SAMPLE_RATES = {
    1,
    5,
    10,
    20,
    40,
    50,
    100,
    200,
    250,
    400,
    500,
    800,
    1000,
    2000,
    4000,
    6400,
    8000,
    12800,
    16000,
    25600,
    32000,
    51200,
    64000,
    128000,
}


@dataclass
class NetworkConfig:
    host: str = "192.168.1.198"
    port: int = 1600
    connect_timeout_sec: float = 3.0
    recv_timeout_sec: float = 1.0
    reconnect_interval_sec: float = 2.0


@dataclass
class DeviceConfig:
    sample_rate_hz: int = 2000
    active_channels: list[int] = field(default_factory=lambda: [0, 1, 2])
    total_channels: int = 16
    adc_bits: int = 24
    voltage_range: str = "+/-10V"
    configure_voltage_range: bool = False
    read_bytes_per_request: int = 1404
    sensor_sensitivity_mv_per_ut: list[float] = field(
        default_factory=lambda: [20.02, 19.98, 19.96]
    )

    def __post_init__(self) -> None:
        # 兼容旧配置中 sensor_sensitivity_mv_per_ut 为单个 float 的情况
        if isinstance(self.sensor_sensitivity_mv_per_ut, (int, float)):
            self.sensor_sensitivity_mv_per_ut = [float(self.sensor_sensitivity_mv_per_ut)] * 3


@dataclass
class RuntimeConfig:
    auto_start: bool = False
    hide_window_on_auto_start: bool = False
    ui_refresh_hz: int = 30
    transport_mode: str = "poll"
    scope_total_window_ms: int = 200
    scope_div_ms: int = 20
    waveform_y_unit: str = "voltage"


@dataclass
class QueueConfig:
    raw_queue_max_chunks: int = 512
    raw_queue_drop_policy: str = "drop_oldest"
    parser_batch_chunks: int = 16
    warning_threshold_ratio: float = 0.8


@dataclass
class DspConfig:
    window_size_samples: int = 4000
    hop_size_samples: int = 200
    fft_window_sec: float = 1.0
    fft_overlap: float = 0.5
    lockin_frequency_hz: float = 50.0
    lockin_window_sec: float = 1.0
    lockin_reference: str = "software"
    packet_loss_fill_mode: str = "zero_order_hold"


@dataclass
class StorageConfig:
    enabled: bool = True
    root_dir: str = "data"
    raw_npz_enabled: bool = True
    feature_csv_enabled: bool = True
    flush_interval_sec: float = 5.0


@dataclass
class AppConfig:
    network: NetworkConfig = field(default_factory=NetworkConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    dsp: DspConfig = field(default_factory=DspConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def validate(self) -> None:
        if self.device.sample_rate_hz not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"不支持的采样率: {self.device.sample_rate_hz}")
        if self.device.total_channels != 16:
            raise ValueError("首版仅支持 16 通道 SK2301")
        if self.device.adc_bits != 24:
            raise ValueError("首版仅支持 24bit ADC")
        if not self.device.active_channels:
            raise ValueError("至少启用一个通道")
        invalid = [
            channel
            for channel in self.device.active_channels
            if channel < 0 or channel >= self.device.total_channels
        ]
        if invalid:
            raise ValueError(f"通道号超出范围: {invalid}")
        if not 1 <= self.runtime.ui_refresh_hz <= 60:
            raise ValueError("ui_refresh_hz 必须在 1..60")
        if self.runtime.transport_mode not in {"poll", "auto_upload"}:
            raise ValueError("transport_mode 必须是 poll 或 auto_upload")
        if self.runtime.scope_total_window_ms <= 0 or self.runtime.scope_div_ms <= 0:
            raise ValueError("示波器时基必须为正数")
        if self.runtime.scope_total_window_ms < self.runtime.scope_div_ms:
            raise ValueError("scope_total_window_ms 不能小于 scope_div_ms")
        if self.runtime.waveform_y_unit not in {"voltage", "magnetic_field"}:
            raise ValueError("waveform_y_unit 必须是 voltage 或 magnetic_field")
        if self.queue.raw_queue_drop_policy != "drop_oldest":
            raise ValueError("首版仅支持 drop_oldest 队列策略")
        frame_bytes = max(1, len(self.device.active_channels)) * 4
        if self.device.read_bytes_per_request <= 0 or self.device.read_bytes_per_request > 1440:
            raise ValueError("read_bytes_per_request 必须在 1..1440")
        if self.device.read_bytes_per_request < frame_bytes:
            raise ValueError("read_bytes_per_request 不能小于激活通道的单帧字节数")
        if not self.device.sensor_sensitivity_mv_per_ut:
            raise ValueError("sensor_sensitivity_mv_per_ut 不能为空列表")
        if any(v <= 0 for v in self.device.sensor_sensitivity_mv_per_ut):
            raise ValueError("sensor_sensitivity_mv_per_ut 中每个值必须为正数")
        if self.dsp.window_size_samples < 2:
            raise ValueError("window_size_samples 必须至少为 2")
        if self.dsp.hop_size_samples < 1:
            raise ValueError("hop_size_samples 必须至少为 1")
        if self.dsp.hop_size_samples > self.dsp.window_size_samples:
            raise ValueError("hop_size_samples 不能大于 window_size_samples")
        if self.dsp.lockin_reference != "software":
            raise ValueError("首版仅支持 software Lock-in 参考")
        if self.dsp.packet_loss_fill_mode not in {"zero_order_hold", "zero_padding"}:
            raise ValueError("packet_loss_fill_mode 必须是 zero_order_hold 或 zero_padding")


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"配置段 {key} 必须是字典")
    return value


def app_config_from_dict(data: dict[str, Any]) -> AppConfig:
    cfg = AppConfig(
        network=NetworkConfig(**_section(data, "network")),
        device=DeviceConfig(**_section(data, "device")),
        runtime=RuntimeConfig(**_section(data, "runtime")),
        queue=QueueConfig(**_section(data, "queue")),
        dsp=DspConfig(**_section(data, "dsp")),
        storage=StorageConfig(**_section(data, "storage")),
    )
    cfg.validate()
    return cfg
