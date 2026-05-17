from protocol.constants import CMD_READ_STREAM, MAGIC, REG_AD_STREAM
from protocol.frames import (
    build_read_registers,
    build_read_stream,
    build_upload_wave_packet,
    build_write_registers,
    parse_header,
    parse_upload_wave_header,
)


def test_build_read_registers_big_endian():
    frame = build_read_registers(0x0012, 1)
    assert frame == bytes.fromhex("46 4B 66 6B 00 00 7A 01 00 12 00 01 00 00 00 00")


def test_build_write_registers_big_endian():
    frame = build_write_registers(0x0011, [1])
    assert frame == bytes.fromhex("46 4B 66 6B 00 00 7A 10 00 11 00 01 00 00 00 00 00 01")


def test_build_read_stream_header():
    frame = build_read_stream(REG_AD_STREAM, 1408)
    header = parse_header(frame)
    assert header.magic == MAGIC
    assert header.cmd_code == CMD_READ_STREAM
    assert header.reg_addr == REG_AD_STREAM
    assert header.data_num == 1408


def test_build_upload_wave_packet_roundtrip():
    frame = build_upload_wave_packet(pack_num=7, sample_rate_hz=2000, channel_en=0x0007, payload=b"abcd")
    header = parse_upload_wave_header(frame)
    assert header.magic == MAGIC
    assert header.pack_num == 7
    assert header.sample_rate_hz == 2000
    assert header.channel_en == 0x0007
    assert header.data_num == 4
