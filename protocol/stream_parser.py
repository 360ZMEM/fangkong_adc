from __future__ import annotations

from dataclasses import dataclass

from .constants import HEADER_SIZE, MAGIC, MAX_STREAM_DATA_BYTES, UPLOAD_HEADER_SIZE
from .frames import (
    expected_response_length,
    expected_upload_packet_length,
    parse_header,
    parse_upload_wave_header,
)


@dataclass
class StreamParserStats:
    bytes_dropped: int = 0
    packets_extracted: int = 0
    invalid_headers: int = 0
    oversized_packets: int = 0


class SlidingByteBuffer:
    """TCP 粘包/半包滑动缓冲区。"""

    def __init__(self, max_data_num: int = MAX_STREAM_DATA_BYTES, packet_mode: str = "poll") -> None:
        self.buffer = bytearray()
        self.max_data_num = max_data_num
        self.packet_mode = packet_mode
        self.stats = StreamParserStats()

    def feed(self, data: bytes) -> None:
        if data:
            self.buffer.extend(data)

    def extract_packets(self) -> list[bytes]:
        packets: list[bytes] = []
        while True:
            magic_index = self.buffer.find(MAGIC)
            if magic_index < 0:
                self._keep_possible_magic_suffix()
                break
            if magic_index > 0:
                del self.buffer[:magic_index]
                self.stats.bytes_dropped += magic_index
            minimum_header_size = HEADER_SIZE if self.packet_mode == "poll" else UPLOAD_HEADER_SIZE
            if len(self.buffer) < minimum_header_size:
                break
            try:
                packet_len = self._expected_packet_length()
            except ValueError:
                del self.buffer[0]
                self.stats.invalid_headers += 1
                self.stats.bytes_dropped += 1
                continue
            if len(self.buffer) < packet_len:
                break
            packets.append(bytes(self.buffer[:packet_len]))
            del self.buffer[:packet_len]
            self.stats.packets_extracted += 1
        return packets

    def _keep_possible_magic_suffix(self) -> None:
        keep = min(len(self.buffer), len(MAGIC) - 1)
        dropped = len(self.buffer) - keep
        if dropped > 0:
            del self.buffer[:dropped]
            self.stats.bytes_dropped += dropped

    def __len__(self) -> int:
        return len(self.buffer)

    def _expected_packet_length(self) -> int:
        if self.packet_mode == "poll":
            header = parse_header(self.buffer)
            if header.magic != MAGIC:
                raise ValueError("invalid poll magic")
            if header.data_num > self.max_data_num:
                self.stats.oversized_packets += 1
                raise ValueError("oversized poll packet")
            return expected_response_length(header)

        if self.packet_mode == "auto_upload":
            header = parse_upload_wave_header(self.buffer)
            if header.magic != MAGIC:
                raise ValueError("invalid upload magic")
            if header.data_num > self.max_data_num:
                self.stats.oversized_packets += 1
                raise ValueError("oversized upload packet")
            return expected_upload_packet_length(header)

        raise ValueError(f"未知 packet_mode: {self.packet_mode}")
