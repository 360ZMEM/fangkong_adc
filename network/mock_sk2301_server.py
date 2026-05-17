from __future__ import annotations

import math
import socket
import threading
import time

from protocol.adc_decoder import encode_test_sample
from protocol.constants import (
    CMD_READ_REG,
    CMD_READ_STREAM,
    CMD_WRITE_REG,
    CMD_WRITE_STREAM,
    HEADER_SIZE,
    MAGIC,
    REG_AD_MODE,
    REG_CHANNEL_EN,
    REG_AD_RANGE,
    REG_AD_START,
    REG_AD_STATUS,
    REG_AD_STREAM,
    REG_INIT_STATUS,
)
from protocol.frames import build_header, build_upload_wave_packet, parse_header


class MockSk2301Server:
    """无真机环境下的本地 TCP 模拟设备。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._registers: dict[int, int] = {
            REG_INIT_STATUS: 1,
            REG_AD_RANGE: 0x0002,
            REG_AD_STATUS: 1,
            REG_AD_START: 0,
        }
        self._sample_index = 0
        self._channel_cursor = 0
        self._upload_pack_num = 0

    @property
    def endpoint(self) -> tuple[str, int]:
        if self._server is None:
            raise RuntimeError("mock server 尚未启动")
        return self._server.getsockname()

    def start(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, name="MockSk2301Server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                self._server.settimeout(0.2)
                client, _ = self._server.accept()
            except (OSError, socket.timeout):
                continue
            with client:
                client.settimeout(0.2)
                self._serve_client(client)

    def _serve_client(self, client: socket.socket) -> None:
        buffer = bytearray()
        while not self._stop.is_set():
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                self._maybe_send_auto_upload(client)
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer.extend(chunk)
            for packet in self._extract_requests(buffer):
                response = self._handle_request(packet)
                if response:
                    self._send_chunked(client, response)

    def _handle_request(self, packet: bytes) -> bytes:
        header = parse_header(packet)
        payload = packet[HEADER_SIZE:]
        if header.cmd_code == CMD_READ_REG:
            return self._build_read_register_response(header.reg_addr, header.data_num)
        if header.cmd_code == CMD_WRITE_REG:
            self._apply_write_registers(header.reg_addr, payload)
            return build_header(header.cmd_code, header.reg_addr, 0)
        if header.cmd_code == CMD_READ_STREAM and header.reg_addr == REG_AD_STREAM:
            data = self._build_stream_payload(header.data_num)
            return build_header(header.cmd_code, header.reg_addr, len(data)) + data
        return build_header(header.cmd_code, header.reg_addr, 0)

    def _build_read_register_response(self, reg_addr: int, count: int) -> bytes:
        words = []
        for offset in range(count):
            words.append(self._registers.get(reg_addr + offset, 0))
        payload = b"".join(int(word).to_bytes(2, "big") for word in words)
        return build_header(CMD_READ_REG, reg_addr, count) + payload

    def _apply_write_registers(self, reg_addr: int, payload: bytes) -> None:
        words = [
            int.from_bytes(payload[index : index + 2], "big")
            for index in range(0, len(payload), 2)
            if index + 2 <= len(payload)
        ]
        for offset, value in enumerate(words):
            self._registers[reg_addr + offset] = value
        if reg_addr == REG_AD_MODE and len(words) >= 6:
            self._registers[REG_AD_RANGE] = words[5]
        if reg_addr == REG_AD_START and words:
            self._registers[REG_AD_STATUS] = words[0]

    def _build_stream_payload(self, byte_count: int) -> bytes:
        payload = bytearray()
        sample_rate = float(self._register_sample_rate())
        base_freq = 50.0
        active_channels = self._active_channels()
        while len(payload) + 4 <= byte_count:
            t = self._sample_index / sample_rate
            channel = active_channels[self._channel_cursor]
            amplitude = 300_000 + channel * 10_000
            phase = channel * 0.2
            raw24 = int(amplitude * math.sin(2.0 * math.pi * base_freq * t + phase))
            payload.extend(encode_test_sample(raw24, channel))
            self._channel_cursor += 1
            if self._channel_cursor >= len(active_channels):
                self._channel_cursor = 0
                self._sample_index += 1
        return bytes(payload[:byte_count])

    def _active_channels(self) -> list[int]:
        mask = self._registers.get(REG_CHANNEL_EN, 0xFFFF)
        channels = [channel for channel in range(16) if mask & (1 << channel)]
        return channels or [0]

    def _register_sample_rate(self) -> int:
        high = self._registers.get(REG_AD_MODE + 1, 0)
        low = self._registers.get(REG_AD_MODE + 2, 2000)
        return ((high & 0xFFFF) << 16) | (low & 0xFFFF)

    def _maybe_send_auto_upload(self, client: socket.socket) -> None:
        if self._registers.get(REG_AD_MODE, 0) != 3:
            return
        if self._registers.get(REG_AD_START, 0) != 1:
            return
        active_channels = self._active_channels()
        byte_count = 1404 - (1404 % max(1, len(active_channels) * 4))
        payload = self._build_stream_payload(byte_count)
        packet = build_upload_wave_packet(
            pack_num=self._upload_pack_num,
            sample_rate_hz=self._register_sample_rate(),
            channel_en=self._registers.get(REG_CHANNEL_EN, 0xFFFF),
            payload=payload,
        )
        self._upload_pack_num = (self._upload_pack_num + 1) & 0xFFFFFFFF
        self._send_chunked(client, packet)

    def _send_chunked(self, client: socket.socket, response: bytes) -> None:
        midpoint = min(len(response), max(1, len(response) // 2))
        try:
            client.sendall(response[:midpoint])
            time.sleep(0.001)
            client.sendall(response[midpoint:])
        except OSError:
            pass

    def _extract_requests(self, buffer: bytearray) -> list[bytes]:
        packets: list[bytes] = []
        while True:
            magic_index = buffer.find(MAGIC)
            if magic_index < 0:
                if len(buffer) > len(MAGIC) - 1:
                    del buffer[: len(buffer) - (len(MAGIC) - 1)]
                break
            if magic_index > 0:
                del buffer[:magic_index]
            if len(buffer) < HEADER_SIZE:
                break
            header = parse_header(buffer)
            if header.cmd_code in {CMD_READ_REG, CMD_READ_STREAM}:
                packet_len = HEADER_SIZE
            elif header.cmd_code == CMD_WRITE_REG:
                packet_len = HEADER_SIZE + header.data_num * 2
            elif header.cmd_code == CMD_WRITE_STREAM:
                packet_len = HEADER_SIZE + header.data_num
            else:
                packet_len = HEADER_SIZE
            if len(buffer) < packet_len:
                break
            packets.append(bytes(buffer[:packet_len]))
            del buffer[:packet_len]
        return packets
