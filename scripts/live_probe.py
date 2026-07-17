from __future__ import annotations

import argparse
import time
from pathlib import Path

from network.tcp_client import TcpClient, TcpEndpoint
from protocol.adc_decoder import ActiveChannelDecoder, decode_24bit_samples
from protocol.constants import REG_AD_MODE, REG_AD_RANGE, REG_AD_START, REG_INIT_STATUS
from protocol.frames import (
    build_read_registers,
    build_read_stream,
    build_write_registers,
    parse_header,
)
from protocol.stream_parser import SlidingByteBuffer
from config.config_manager import load_merged_config
from config.runtime_paths import DEFAULT_DEVICE_HOST, DEFAULT_DEVICE_PORT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SK2301 真机流探测脚本")
    parser.add_argument(
        "--config",
        type=str,
        default="config/default_config.yaml",
        help="默认配置文件路径",
    )
    parser.add_argument(
        "--user-config",
        type=str,
        default="config/user_config.yaml",
        help="用户配置文件路径（覆盖默认值）",
    )
    parser.add_argument("--host", type=str, default="", help="临时覆盖设备 IP")
    parser.add_argument("--port", type=int, default=0, help="临时覆盖设备端口")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    config = load_merged_config(root / args.config, root / args.user_config)
    host = args.host or config.network.host or DEFAULT_DEVICE_HOST
    port = int(args.port or config.network.port or DEFAULT_DEVICE_PORT)
    client = TcpClient(
        TcpEndpoint(host, port),
        config.network.connect_timeout_sec,
        config.network.recv_timeout_sec,
    )
    parser = SlidingByteBuffer()
    active_channels = list(config.device.active_channels)
    aligned_decoder = ActiveChannelDecoder(active_channels)

    def reqresp(req: bytes, expect_reg: int, timeout: float = 2.0) -> bytes:
        client.send_all(req)
        deadline = time.time() + timeout
        parser.buffer.clear()
        while time.time() < deadline:
            chunk = client.recv_some(4096)
            if not chunk:
                continue
            parser.feed(chunk)
            for packet in parser.extract_packets():
                header = parse_header(packet)
                if header.reg_addr == expect_reg:
                    return packet
        raise RuntimeError(f"timeout reg={expect_reg}")

    client.connect()
    print(f"connected host={host} port={port} active_channels={active_channels}")
    for reg in [REG_INIT_STATUS, REG_AD_RANGE]:
        packet = reqresp(build_read_registers(reg, 1), reg)
        print("read_reg", reg, int.from_bytes(packet[16:18], "big"))

    freq = int(config.device.sample_rate_hz)
    channel_mask = 0
    for channel in active_channels:
        channel_mask |= 1 << channel
    values = [0x0000, (freq >> 16) & 0xFFFF, freq & 0xFFFF, channel_mask, 0x0000, 0x0002, 0x0001]
    packet = reqresp(build_write_registers(REG_AD_MODE, values), REG_AD_MODE)
    print("config_ack", parse_header(packet))
    packet = reqresp(build_write_registers(REG_AD_START, [1]), REG_AD_START)
    print("start_ack", parse_header(packet))

    rows = []
    request_bytes = int(config.device.read_bytes_per_request)
    for i in range(12):
        t0 = time.time()
        packet = reqresp(build_read_stream(19, request_bytes), 19, timeout=3.0)
        dt = time.time() - t0
        header = parse_header(packet)
        payload = packet[16:]
        ids = list(payload[3::4])
        unique_ids = sorted(set(ids))
        decoded16 = decode_24bit_samples(payload, active_channels=active_channels, total_channels=16)
        decoded3 = aligned_decoder.decode(payload)
        row = {
            "iter": i,
            "dt_ms": round(dt * 1000, 2),
            "data_num": header.data_num,
            "payload_len": len(payload),
            "unique_ids": unique_ids[:16],
            "first_24_ids": ids[:24],
            "samples16": int(decoded16.voltages.shape[0]),
            "samples_active": int(decoded3.voltages.shape[0]),
            "mismatch16": int(decoded16.stats.channel_mismatch_count),
            "mismatch_active": int(decoded3.stats.channel_mismatch_count),
        }
        rows.append(row)
        print(row)

    avg_dt_ms = sum(row["dt_ms"] for row in rows) / len(rows)
    print("avg_dt_ms", round(avg_dt_ms, 2), "packet_rate_hz", round(1000.0 / avg_dt_ms, 2))
    client.close()


if __name__ == "__main__":
    main()
