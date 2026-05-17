from protocol.constants import CMD_READ_STREAM, REG_AD_STREAM
from protocol.frames import build_header, build_upload_wave_packet
from protocol.stream_parser import SlidingByteBuffer


def _packet(payload: bytes) -> bytes:
    return build_header(CMD_READ_STREAM, REG_AD_STREAM, len(payload)) + payload


def test_extract_sticky_packets():
    p1 = _packet(b"abc")
    p2 = _packet(b"1234")
    parser = SlidingByteBuffer()
    parser.feed(p1 + p2)
    assert parser.extract_packets() == [p1, p2]


def test_extract_half_packet():
    p = _packet(b"abcdef")
    parser = SlidingByteBuffer()
    parser.feed(p[:10])
    assert parser.extract_packets() == []
    parser.feed(p[10:])
    assert parser.extract_packets() == [p]


def test_drop_garbage_before_magic():
    p = _packet(b"abc")
    parser = SlidingByteBuffer()
    parser.feed(b"garbage" + p)
    assert parser.extract_packets() == [p]
    assert parser.stats.bytes_dropped >= len(b"garbage")


def test_extract_auto_upload_packets():
    p1 = build_upload_wave_packet(pack_num=1, sample_rate_hz=2000, payload=b"abcd")
    p2 = build_upload_wave_packet(pack_num=2, sample_rate_hz=2000, payload=b"1234")
    parser = SlidingByteBuffer(packet_mode="auto_upload")
    parser.feed(p1 + p2)
    assert parser.extract_packets() == [p1, p2]
