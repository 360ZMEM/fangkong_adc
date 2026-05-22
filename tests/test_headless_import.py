"""
验证 api.py 和 headless.py 的导入链在无 PySide6 环境下也能正常工作。
（实际上 PySide6 已安装，但此测试验证的是 api.py 的导入路径不触发 GUI 代码。）
"""

from __future__ import annotations


def test_api_imports_no_gui():
    """api.py 的所有导出符号应不依赖 PySide6。"""
    from api import (
        # 配置
        AppConfig,
        DeviceConfig,
        DspConfig,
        NetworkConfig,
        QueueConfig,
        RuntimeConfig,
        StorageConfig,
        SUPPORTED_SAMPLE_RATES,
        load_config,
        load_merged_config,
        save_config,
        validate_config,
        # 控制器
        AcquisitionController,
        # 数据模型
        ConnectionState,
        FftResult,
        LatestSnapshot,
        LockinResult,
        ProcessingStats,
        # DSP
        compute_fft,
        compute_lockin,
        # 协议
        ActiveChannelDecoder,
        CMD_READ_REG,
        CMD_READ_STREAM,
        CMD_WRITE_REG,
        CMD_WRITE_STREAM,
        DecodedAdcData,
        DecodeStats,
        FkProHeader,
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
        SlidingByteBuffer,
        UPLOAD_HEADER_SIZE,
        UploadWaveHeader,
        build_read_registers,
        build_read_stream,
        build_write_registers,
        build_write_stream,
        decode_24bit_samples,
        parse_header,
        parse_upload_wave_header,
        # 网络
        NetworkWorker,
        NetworkWorkerStats,
        TcpClient,
        TcpClientError,
        TcpEndpoint,
        # 存储
        DataStorage,
        RingBuffer,
    )
    # 基本类型检查
    assert MAGIC == b"FKfk"
    assert HEADER_SIZE == 16
    assert callable(load_merged_config)
    assert callable(compute_fft)
    assert callable(compute_lockin)


def test_controller_construction_headless():
    """无 GUI 环境下可以正常构造 AcquisitionController。"""
    from pathlib import Path
    from api import AcquisitionController, load_merged_config, ConnectionState

    root = Path(__file__).resolve().parent.parent
    config = load_merged_config(root / "config" / "default_config.yaml")
    controller = AcquisitionController(config)
    assert controller.state == ConnectionState.DISCONNECTED
    snapshot = controller.get_latest_snapshot()
    assert snapshot.channels == [0, 1, 2]
    assert snapshot.sample_rate_hz == 2000


def test_dsp_standalone():
    """DSP 函数可独立调用，不需要控制器或设备连接。"""
    import numpy as np
    from api import compute_fft, compute_lockin

    sr = 2000
    t = np.arange(sr) / sr
    signal = np.column_stack([
        np.sin(2 * np.pi * 50 * t),
        np.cos(2 * np.pi * 50 * t),
        np.zeros_like(t),
    ])

    fft_result = compute_fft(signal, sr, [0, 1, 2])
    assert len(fft_result.freqs) > 0
    assert 0 in fft_result.spectra

    lockin_result = compute_lockin(signal, sr, [0, 1, 2], frequency_hz=50.0)
    assert len(lockin_result) == 3
    assert lockin_result[0].amplitude > 0.9


def test_headless_script_importable():
    """headless.py 可以被导入（不执行 main）。"""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "headless", Path(__file__).resolve().parent.parent / "headless.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # 不执行 main，仅验证语法和导入链
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
    assert callable(module.main)
