from __future__ import annotations

from dataclasses import dataclass
import struct

from .constants import (
    CMD_READ_REG,
    CMD_READ_STREAM,
    CMD_WRITE_REG,
    CMD_WRITE_STREAM,
    DEFAULT_CRC,
    DEFAULT_ERR_TYPE,
    DEFAULT_INST_ADDR,
    HEADER_SIZE,
    MAGIC,
    UPLOAD_HEADER_SIZE,
)

_HEADER_STRUCT = struct.Struct(">4sHHHHHH")
_UPLOAD_WAVE_HEADER_STRUCT = struct.Struct(">4sBBBBII16sHIHIHBBHH")


@dataclass(frozen=True)
class FkProHeader:
    magic: bytes
    inst_addr: int
    cmd_code: int
    reg_addr: int
    data_num: int
    err_type: int
    crc: int

    @property
    def ok(self) -> bool:
        return self.magic == MAGIC and self.err_type == 0


@dataclass(frozen=True)
class UploadWaveHeader:
    magic: bytes
    protocol_ver: int
    inst_addr: int
    pack_type: int
    pack_code: int
    pack_num: int
    event_num: int
    inst_id: bytes
    crc: int
    unix_time_sec: int
    nop: int
    sample_rate_hz: int
    channel_en: int
    sec_sync: int
    data_type: int
    err_type: int
    data_num: int

    @property
    def ok(self) -> bool:
        return self.magic == MAGIC and self.err_type == 0


def build_header(
    cmd_code: int,
    reg_addr: int,
    data_num: int,
    inst_addr: int = DEFAULT_INST_ADDR,
    err_type: int = DEFAULT_ERR_TYPE,
    crc: int = DEFAULT_CRC,
) -> bytes:
    return _HEADER_STRUCT.pack(MAGIC, inst_addr, cmd_code, reg_addr, data_num, err_type, crc)


def parse_header(packet: bytes | bytearray | memoryview) -> FkProHeader:
    if len(packet) < HEADER_SIZE:
        raise ValueError(f"数据不足，无法解析 FkPro 头: {len(packet)} < {HEADER_SIZE}")
    magic, inst_addr, cmd_code, reg_addr, data_num, err_type, crc = _HEADER_STRUCT.unpack(
        bytes(packet[:HEADER_SIZE])
    )
    return FkProHeader(magic, inst_addr, cmd_code, reg_addr, data_num, err_type, crc)


def parse_upload_wave_header(packet: bytes | bytearray | memoryview) -> UploadWaveHeader:
    if len(packet) < UPLOAD_HEADER_SIZE:
        raise ValueError(f"数据不足，无法解析自动上传头: {len(packet)} < {UPLOAD_HEADER_SIZE}")
    unpacked = _UPLOAD_WAVE_HEADER_STRUCT.unpack(bytes(packet[:UPLOAD_HEADER_SIZE]))
    return UploadWaveHeader(*unpacked)


def build_read_registers(reg_addr: int, count: int) -> bytes:
    _validate_u16(reg_addr, "reg_addr")
    _validate_u16(count, "count")
    return build_header(CMD_READ_REG, reg_addr, count)


def build_write_registers(reg_addr: int, values: list[int] | tuple[int, ...]) -> bytes:
    _validate_u16(reg_addr, "reg_addr")
    if not values:
        raise ValueError("values 不能为空")
    payload = bytearray()
    for value in values:
        _validate_u16(value, "register value")
        payload.extend(struct.pack(">H", value))
    return build_header(CMD_WRITE_REG, reg_addr, len(values)) + bytes(payload)


def build_read_stream(reg_addr: int, byte_count: int) -> bytes:
    _validate_u16(reg_addr, "reg_addr")
    _validate_u16(byte_count, "byte_count")
    return build_header(CMD_READ_STREAM, reg_addr, byte_count)


def build_write_stream(reg_addr: int, data: bytes) -> bytes:
    _validate_u16(reg_addr, "reg_addr")
    if len(data) > 0xFFFF:
        raise ValueError("串行写入数据过长")
    return build_header(CMD_WRITE_STREAM, reg_addr, len(data)) + data


def expected_response_length(header: FkProHeader) -> int:
    if header.cmd_code == CMD_READ_STREAM:
        return HEADER_SIZE + header.data_num
    if header.cmd_code == CMD_READ_REG:
        return HEADER_SIZE + header.data_num * 2
    if header.cmd_code in {CMD_WRITE_REG, CMD_WRITE_STREAM}:
        return HEADER_SIZE
    return HEADER_SIZE + header.data_num


def expected_upload_packet_length(header: UploadWaveHeader) -> int:
    return UPLOAD_HEADER_SIZE + header.data_num


def build_upload_wave_packet(
    *,
    protocol_ver: int = 1,
    inst_addr: int = 0,
    pack_type: int = 0x02,
    pack_code: int = 0x01,
    pack_num: int = 0,
    event_num: int = 0,
    inst_id: bytes = b"\x00" * 16,
    crc: int = 0,
    unix_time_sec: int = 0,
    nop: int = 0,
    sample_rate_hz: int = 2000,
    channel_en: int = 0x0007,
    sec_sync: int = 0,
    data_type: int = 1,
    err_type: int = 0,
    payload: bytes = b"",
) -> bytes:
    if len(inst_id) != 16:
        raise ValueError("inst_id 必须正好 16 字节")
    header = _UPLOAD_WAVE_HEADER_STRUCT.pack(
        MAGIC,
        protocol_ver,
        inst_addr,
        pack_type,
        pack_code,
        pack_num,
        event_num,
        inst_id,
        crc,
        unix_time_sec,
        nop,
        sample_rate_hz,
        channel_en,
        sec_sync,
        data_type,
        err_type,
        len(payload),
    )
    return header + payload


def _validate_u16(value: int, name: str) -> None:
    if not 0 <= int(value) <= 0xFFFF:
        raise ValueError(f"{name} 必须是 0..65535: {value}")
