from __future__ import annotations

import queue
import threading
import time

from config.config_manager import save_config
from config.runtime_paths import relativize_to_project, resolve_repo_path
from config.settings import AppConfig
from .calibration import MagnetometerCalibration, calibration_summary
from network.network_worker import NetworkWorker, NetworkWorkerStats
from network.reconnect_state import ConnectionState
from network.tcp_client import TcpClient, TcpClientError, TcpEndpoint
from protocol.constants import REG_AD_MODE, REG_AD_RANGE, REG_AD_START, REG_AD_STATUS, REG_INIT_STATUS
from protocol.frames import build_read_registers, build_read_stream, build_write_registers, parse_header
from protocol.stream_parser import SlidingByteBuffer
from .models import LatestSnapshot
from .pipeline import LatestDataStore, PipelineHandles, PipelineWorker
from .recorder import Recorder
from .ring_buffer import RingBuffer
from .storage import DataStorage


class AcquisitionController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.raw_queue: queue.Queue[bytes] = queue.Queue(maxsize=config.queue.raw_queue_max_chunks)
        self.stop_event = threading.Event()
        initial = LatestSnapshot(
            channels=list(config.device.active_channels),
            sample_rate_hz=config.device.sample_rate_hz,
        )
        initial.stats.configured_sample_rate_hz = config.device.sample_rate_hz
        self.latest_store = LatestDataStore(initial)
        self.state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self.client = TcpClient(
            TcpEndpoint(config.network.host, config.network.port),
            config.network.connect_timeout_sec,
            config.network.recv_timeout_sec,
        )
        self.network_stats = NetworkWorkerStats()
        self.network_worker: NetworkWorker | None = None
        self.pipeline_worker: PipelineWorker | None = None
        self.storage = DataStorage(config.storage)
        self.ring_buffer = RingBuffer(
            capacity_samples=self._ring_buffer_capacity(),
            channel_count=len(config.device.active_channels),
        )
        self._auto_thread: threading.Thread | None = None
        self._pump_thread: threading.Thread | None = None
        self._command_lock = threading.Lock()
        self._parser_for_sync = SlidingByteBuffer()
        self._last_rate_sample_time = time.monotonic()
        self._last_rate_bytes = 0
        self._user_config_path = resolve_repo_path("config/user_config.yaml")
        self.recorder = Recorder(output_dir="raw_data")
        self.calibration_profile: MagnetometerCalibration | None = None
        if self.config.calibration.profile_path:
            try:
                resolved_profile = resolve_repo_path(self.config.calibration.profile_path)
                if resolved_profile is None:
                    raise FileNotFoundError("calibration.profile_path 为空")
                self.calibration_profile = MagnetometerCalibration.load(resolved_profile)
                self.config.calibration.profile_path = relativize_to_project(resolved_profile)
            except Exception as exc:
                self.config.calibration.enabled = False
                self.storage.append_event(f"标定文件加载失败: {exc}")

    def set_state(self, state: ConnectionState, message: str = "") -> None:
        with self._state_lock:
            self.state = state
            snapshot = self.latest_store.get()
            snapshot.state = state
            if message:
                snapshot.status_message = message
            snapshot.queue_size = self.raw_queue.qsize()
            snapshot.stats.dropped_chunks = self.network_stats.dropped_chunks
            self.latest_store.update(snapshot)

    def get_latest_snapshot(self) -> LatestSnapshot:
        snapshot = self.latest_store.get()
        snapshot.state = self.state
        snapshot.queue_size = self.raw_queue.qsize()
        snapshot.stats.dropped_chunks = self.network_stats.dropped_chunks
        snapshot.stats.bytes_received = self.network_stats.bytes_received
        snapshot.stats.configured_sample_rate_hz = self.config.device.sample_rate_hz
        snapshot.stats.recv_rate_bytes_per_sec = self._compute_recv_rate()
        snapshot.mode = "AUV 自动化" if self.config.runtime.auto_start else "Debug 交互"
        snapshot.warning_message = self._compute_warning_message(snapshot.queue_size)
        return snapshot

    def connect(self) -> None:
        self._run_async(self._connect_impl, "ConnectWorker")

    def _connect_impl(self) -> None:
        self.set_state(ConnectionState.CONNECTING, "连接中")
        self.client.connect()
        init_status = self._read_register_value(REG_INIT_STATUS)
        if init_status not in (0, 1):
            self.storage.append_event(f"初始化状态返回异常值: {init_status}")
        message = "已连接，初始化完成" if init_status == 1 else "已连接，设备初始化中"
        self.set_state(ConnectionState.CONNECTED, message)

    def configure_device(self) -> None:
        self._run_async(self._configure_impl, "ConfigureWorker")

    def _configure_impl(self) -> None:
        self.set_state(ConnectionState.CONFIGURING, "设参中")
        freq = self.config.device.sample_rate_hz
        channel_mask = 0
        for ch in self.config.device.active_channels:
            channel_mask |= 1 << ch

        current_range = self._read_register_value(REG_AD_RANGE)

        values = [
            0x0003 if self.config.runtime.transport_mode == "auto_upload" else 0x0000,
            (freq >> 16) & 0xFFFF,
            freq & 0xFFFF,
            channel_mask & 0xFFFF,
            0x0000,
            current_range,
            0x0001,
        ]
        self._request_response(build_write_registers(REG_AD_MODE, values), expect_reg=REG_AD_MODE)
        status_value = self._read_register_value(REG_AD_STATUS)
        self.storage.append_event(
            f"设参完成: freq={freq}, channels={self.config.device.active_channels}, status={status_value}"
        )
        self.set_state(ConnectionState.CONNECTED, "设参完成")

    def start_acquisition(self) -> None:
        self._run_async(self._start_impl, "StartWorker")

    def _start_impl(self) -> None:
        self.stop_event.clear()
        self._start_pipeline_if_needed()
        self._request_response(build_write_registers(REG_AD_START, [1]), expect_reg=REG_AD_START)
        self._start_network_if_needed()
        if self.config.runtime.transport_mode == "poll":
            self._start_reader_pump()
        self.set_state(ConnectionState.ACQUIRING, "采集中")

    def stop_acquisition(self) -> None:
        self._run_async(self._stop_impl, "StopWorker")

    def _stop_impl(self) -> None:
        self.set_state(ConnectionState.STOPPING, "停止中")
        self.stop_event.set()
        self.client.close()
        self.set_state(ConnectionState.DISCONNECTED, "已停止")

    def set_active_channels(self, channels: list[int]) -> None:
        normalized = sorted(set(channels))
        if not normalized:
            self.set_state(self.state, "至少启用一个通道")
            return
        if any(ch < 0 or ch >= self.config.device.total_channels for ch in normalized):
            self.set_state(self.state, "通道号超出范围")
            return
        if self.state == ConnectionState.ACQUIRING:
            self.set_state(self.state, "采集中不允许切换通道")
            return
        self.config.device.active_channels = normalized
        self.ring_buffer = RingBuffer(
            capacity_samples=self._ring_buffer_capacity(),
            channel_count=len(normalized),
        )
        snapshot = self.latest_store.get()
        snapshot.channels = list(normalized)
        snapshot.waveform = snapshot.waveform[:0]
        self.latest_store.update(snapshot)
        self.set_state(self.state, f"已选择通道: {normalized}")
        self.save_user_config()

    def start_auto_mode(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._auto_thread = threading.Thread(target=self._auto_loop, name="AutoMode", daemon=True)
        self._auto_thread.start()

    def set_waveform_unit(self, unit_mode: str) -> None:
        if unit_mode not in {"voltage", "magnetic_field"}:
            self.set_state(self.state, "波形单位无效")
            return
        self.config.runtime.waveform_y_unit = unit_mode
        self.set_state(self.state, f"波形单位: {'V' if unit_mode == 'voltage' else 'μT'}")
        self.save_user_config()

    def set_scope_timebase(self, total_window_ms: int, div_ms: int) -> None:
        if total_window_ms <= 0 or div_ms <= 0 or total_window_ms < div_ms:
            self.set_state(self.state, "时基参数无效")
            return
        self.config.runtime.scope_total_window_ms = int(total_window_ms)
        self.config.runtime.scope_div_ms = int(div_ms)
        self.ring_buffer.resize(self._ring_buffer_capacity())
        self.set_state(self.state, f"时基: {total_window_ms} ms / {div_ms} ms每格")
        self.save_user_config()

    def set_lockin_frequency(self, freq_hz: float) -> None:
        if freq_hz <= 0:
            self.set_state(self.state, "锁相频率必须为正数")
            return
        self.config.dsp.lockin_frequency_hz = float(freq_hz)
        self.set_state(self.state, f"锁相频率: {freq_hz:.1f} Hz")
        self.save_user_config()

    def start_recording(self) -> None:
        self.recorder.start(
            channels=list(self.config.device.active_channels),
            sample_rate_hz=self.config.device.sample_rate_hz,
        )
        self.set_state(self.state, "录制中...")

    def stop_recording(self) -> str:
        path = self.recorder.stop_and_save(
            sensitivity_mv_per_ut=list(self.config.device.sensor_sensitivity_mv_per_ut),
            calibration=self.calibration_profile,
            calibration_enabled=self.config.calibration.enabled,
        )
        if path:
            self.set_state(self.state, f"录制完成！已保存: {path}")
        else:
            self.set_state(self.state, "录制停止（无数据）")
        return path

    def load_calibration_profile(self, path: str) -> None:
        try:
            resolved_path = resolve_repo_path(path)
            if resolved_path is None:
                raise FileNotFoundError("未提供有效标定文件路径")
            profile = MagnetometerCalibration.load(resolved_path)
            self.calibration_profile = profile
            self.config.calibration.profile_path = relativize_to_project(resolved_path)
            self.config.calibration.enabled = True
            self.set_state(self.state, calibration_summary(profile, True))
            self.save_user_config()
        except Exception as exc:
            self.config.calibration.enabled = False
            self.set_state(self.state, f"标定加载失败: {exc}")

    def set_calibration_enabled(self, enabled: bool) -> None:
        if enabled and self.calibration_profile is None:
            self.config.calibration.enabled = False
            self.set_state(self.state, "请先加载标定文件")
            return
        self.config.calibration.enabled = bool(enabled)
        self.set_state(self.state, calibration_summary(self.calibration_profile, self.config.calibration.enabled))
        self.save_user_config()

    def shutdown(self) -> None:
        self.stop_acquisition()

    def save_user_config(self) -> None:
        if self._user_config_path is None:
            raise RuntimeError("user_config.yaml 路径解析失败")
        save_config(self.config, self._user_config_path)

    def load_user_config(self) -> None:
        # GUI 层会重新从控制器状态刷新，不在此重建整个对象图。
        self.save_user_config()

    def _auto_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if not self.client.connected:
                    self._connect_impl()
                self._configure_impl()
                self._start_impl()
                while self.state == ConnectionState.ACQUIRING and not self.stop_event.is_set():
                    time.sleep(0.5)
            except Exception as exc:
                self.set_state(ConnectionState.RECONNECT_WAIT, f"重连等待: {exc}")
                self.storage.append_event(f"重连等待: {exc}")
                self.client.close()
                time.sleep(self.config.network.reconnect_interval_sec)

    def _start_network_if_needed(self) -> None:
        if self.network_worker and self.network_worker.is_alive():
            return
        self.network_worker = NetworkWorker(
            self.client,
            self.raw_queue,
            self.stop_event,
            stats=self.network_stats,
            on_error=lambda exc: self.set_state(ConnectionState.RECONNECT_WAIT, str(exc)),
        )
        self.network_worker.start()

    def _start_pipeline_if_needed(self) -> None:
        if self.pipeline_worker and self.pipeline_worker.is_alive():
            return
        handles = PipelineHandles(self.ring_buffer, self.latest_store, self.storage, self.recorder)
        self.pipeline_worker = PipelineWorker(self.config, self.raw_queue, self.stop_event, handles)
        self.pipeline_worker.start()

    def _start_reader_pump(self) -> None:
        if self._pump_thread and self._pump_thread.is_alive():
            return

        def pump() -> None:
            request_bytes = self._effective_stream_request_bytes()
            request = build_read_stream(19, request_bytes)
            frame_bytes = max(1, len(self.config.device.active_channels)) * 4
            samples_per_request = max(1.0, request_bytes / frame_bytes)
            request_interval_sec = max(
                0.002,
                samples_per_request / max(1, self.config.device.sample_rate_hz),
            )
            self.storage.append_event(
                "读流参数: "
                f"request_bytes={request_bytes}, frame_bytes={frame_bytes}, "
                f"samples_per_request={samples_per_request:.1f}, interval={request_interval_sec:.4f}s"
            )
            next_deadline = time.monotonic()
            while not self.stop_event.is_set() and self.client.connected:
                try:
                    self.client.send_all(request)
                    next_deadline += request_interval_sec
                    sleep_sec = next_deadline - time.monotonic()
                    if sleep_sec > 0:
                        time.sleep(sleep_sec)
                    else:
                        next_deadline = time.monotonic()
                except TcpClientError as exc:
                    self.set_state(ConnectionState.RECONNECT_WAIT, str(exc))
                    self.storage.append_event(f"读流失败: {exc}")
                    break

        self._pump_thread = threading.Thread(target=pump, name="ReadStreamPump", daemon=True)
        self._pump_thread.start()

    def _run_async(self, target, name: str) -> None:
        def runner() -> None:
            with self._command_lock:
                try:
                    target()
                except Exception as exc:
                    self.set_state(ConnectionState.ERROR, str(exc))
                    self.storage.append_event(f"{name} 失败: {exc}")

        threading.Thread(target=runner, name=name, daemon=True).start()

    def _read_register_value(self, reg_addr: int) -> int:
        packet = self._request_response(build_read_registers(reg_addr, 1), expect_reg=reg_addr)
        if len(packet) < 18:
            raise RuntimeError(f"寄存器 {reg_addr} 响应长度不足")
        return int.from_bytes(packet[16:18], byteorder="big", signed=False)

    def _request_response(self, request: bytes, expect_reg: int, timeout_sec: float = 2.0) -> bytes:
        self.client.send_all(request)
        deadline = time.monotonic() + timeout_sec
        self._parser_for_sync = SlidingByteBuffer()
        while time.monotonic() < deadline:
            chunk = self.client.recv_some(4096)
            if not chunk:
                continue
            self._parser_for_sync.feed(chunk)
            for packet in self._parser_for_sync.extract_packets():
                header = parse_header(packet)
                if header.reg_addr == expect_reg:
                    return packet
        raise RuntimeError(f"等待寄存器 {expect_reg} 响应超时")

    def _compute_recv_rate(self) -> float:
        now = time.monotonic()
        elapsed = now - self._last_rate_sample_time
        if elapsed < 0.2:
            snapshot = self.latest_store.get()
            return snapshot.stats.recv_rate_bytes_per_sec
        delta = self.network_stats.bytes_received - self._last_rate_bytes
        rate = delta / max(elapsed, 1e-6)
        self._last_rate_sample_time = now
        self._last_rate_bytes = self.network_stats.bytes_received
        return rate

    def _compute_warning_message(self, queue_size: int) -> str:
        max_chunks = max(1, self.config.queue.raw_queue_max_chunks)
        ratio = queue_size / max_chunks
        protocol_packet_loss = self.latest_store.get().stats.packet_loss_count
        if protocol_packet_loss > 0:
            return "检测到协议级丢包，已执行补点"
        if self.network_stats.dropped_chunks > 0:
            return "发生丢包，已执行 drop_oldest"
        if ratio >= self.config.queue.warning_threshold_ratio:
            return "原始队列积压接近阈值"
        return ""

    def _effective_stream_request_bytes(self) -> int:
        preferred = self.config.device.read_bytes_per_request
        frame_bytes = max(1, len(self.config.device.active_channels)) * 4
        aligned = preferred - (preferred % frame_bytes)
        if aligned <= 0:
            aligned = frame_bytes
        if aligned != preferred:
            self.storage.append_event(
                f"read_bytes_per_request 已按激活通道对齐: {preferred} -> {aligned}"
            )
        return aligned

    def _ring_buffer_capacity(self) -> int:
        waveform_samples = max(
            1,
            int(round(self.config.device.sample_rate_hz * self.config.runtime.scope_total_window_ms / 1000.0)),
        )
        return max(self.config.dsp.window_size_samples, waveform_samples)
