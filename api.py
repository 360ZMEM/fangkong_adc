"""
fangkong_adc 统一 API 入口
===========================

本文件将项目各子包的公开符号集中导出，供 headless 脚本或外部模块直接使用：

    from api import AcquisitionController, load_merged_config, compute_fft

所有导入均不依赖 PySide6，可在无 GUI 环境下安全使用。
"""

from __future__ import annotations

# --- 配置 ---
from config.config_manager import load_config, load_merged_config, save_config, validate_config
from config.runtime_paths import (
    DEFAULT_CALIBRATION_PROFILE,
    DEFAULT_DEVICE_HOST,
    DEFAULT_DEVICE_PORT,
    project_root,
    relativize_to_project,
    resolve_repo_path,
)
from config.settings import (
    AppConfig,
    DeviceConfig,
    DspConfig,
    NetworkConfig,
    QueueConfig,
    RuntimeConfig,
    StorageConfig,
    SUPPORTED_SAMPLE_RATES,
)

# --- 控制器 (Facade) ---
from core.acquisition_controller import AcquisitionController

# --- 数据模型 ---
from core.models import FftResult, LatestSnapshot, LockinResult, ProcessingStats
from network.reconnect_state import ConnectionState

# --- DSP 算法 (可独立调用) ---
from core.dsp import compute_fft
from core.lockin import compute_lockin
from core.calibration import (
    MagnetometerCalibration,
    apply_calibration,
    voltage_to_magnetic_field,
)

# --- 协议工具 (底层) ---
from protocol.adc_decoder import (
    ActiveChannelDecoder,
    DecodedAdcData,
    DecodeStats,
    decode_24bit_samples,
)
from protocol.constants import (
    CMD_READ_REG,
    CMD_READ_STREAM,
    CMD_WRITE_REG,
    CMD_WRITE_STREAM,
    HEADER_SIZE,
    MAGIC,
    MAX_STREAM_DATA_BYTES,
    REG_AD_MODE,
    REG_AD_RANGE,
    REG_AD_START,
    REG_AD_STATUS,
    REG_AD_STREAM,
    REG_CHANNEL_EN,
    REG_INIT_STATUS,
    UPLOAD_HEADER_SIZE,
)
from protocol.frames import (
    FkProHeader,
    UploadWaveHeader,
    build_read_registers,
    build_read_stream,
    build_write_registers,
    build_write_stream,
    parse_header,
    parse_upload_wave_header,
)
from protocol.stream_parser import SlidingByteBuffer

# --- 网络 ---
from network.network_worker import NetworkWorker, NetworkWorkerStats
from network.tcp_client import TcpClient, TcpClientError, TcpEndpoint

# --- 存储 ---
from core.ring_buffer import RingBuffer
from core.storage import DataStorage

__all__ = [
    # 配置
    "load_config",
    "load_merged_config",
    "save_config",
    "validate_config",
    "project_root",
    "resolve_repo_path",
    "relativize_to_project",
    "DEFAULT_DEVICE_HOST",
    "DEFAULT_DEVICE_PORT",
    "DEFAULT_CALIBRATION_PROFILE",
    "AppConfig",
    "NetworkConfig",
    "DeviceConfig",
    "RuntimeConfig",
    "QueueConfig",
    "DspConfig",
    "StorageConfig",
    "SUPPORTED_SAMPLE_RATES",
    # 控制器
    "AcquisitionController",
    # 数据模型
    "LatestSnapshot",
    "LockinResult",
    "FftResult",
    "ProcessingStats",
    "ConnectionState",
    # DSP
    "compute_fft",
    "compute_lockin",
    "MagnetometerCalibration",
    "apply_calibration",
    "voltage_to_magnetic_field",
    # 协议
    "MAGIC",
    "HEADER_SIZE",
    "UPLOAD_HEADER_SIZE",
    "MAX_STREAM_DATA_BYTES",
    "CMD_READ_REG",
    "CMD_WRITE_REG",
    "CMD_READ_STREAM",
    "CMD_WRITE_STREAM",
    "REG_INIT_STATUS",
    "REG_AD_MODE",
    "REG_CHANNEL_EN",
    "REG_AD_RANGE",
    "REG_AD_START",
    "REG_AD_STATUS",
    "REG_AD_STREAM",
    "FkProHeader",
    "UploadWaveHeader",
    "build_read_registers",
    "build_write_registers",
    "build_read_stream",
    "build_write_stream",
    "parse_header",
    "parse_upload_wave_header",
    "SlidingByteBuffer",
    "ActiveChannelDecoder",
    "DecodedAdcData",
    "DecodeStats",
    "decode_24bit_samples",
    # 网络
    "TcpClient",
    "TcpEndpoint",
    "TcpClientError",
    "NetworkWorker",
    "NetworkWorkerStats",
    # 存储
    "DataStorage",
    "RingBuffer",
]
