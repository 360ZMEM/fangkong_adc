"""
headless.py - 无 GUI Headless 采集入口
========================================

演示如何在无 PySide6 / 无图形界面的环境下使用本项目的 API：
  加载配置 → 创建控制器 → 连接 → 设参 → 采集 N 秒 → 输出快照 → 停止

用法:
    python headless.py                    # 默认采集 10 秒
    python headless.py --duration 30      # 采集 30 秒
    python headless.py --help             # 显示帮助

适用场景:
    - AUV 嵌入式部署（无显示器）
    - 自动化测试 / CI
    - 后台长期监控采集
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from api import (
    AcquisitionController,
    ConnectionState,
    load_merged_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SK2301 ADC Headless 采集脚本（无 GUI）"
    )
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
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="采集持续时间（秒），默认 10",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="快照轮询间隔（秒），默认 1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent

    # 1. 加载配置
    config = load_merged_config(
        root / args.config,
        root / args.user_config,
    )
    print(f"[headless] 配置加载完成: host={config.network.host}, "
          f"port={config.network.port}, "
          f"sample_rate={config.device.sample_rate_hz} Hz, "
          f"channels={config.device.active_channels}")

    # 2. 创建控制器
    controller = AcquisitionController(config)

    # 3. 优雅退出信号处理
    stop_flag = False

    def on_signal(sig, frame):
        nonlocal stop_flag
        stop_flag = True
        print("\n[headless] 收到退出信号，正在停止...")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # 4. 连接
    print("[headless] 正在连接设备...")
    controller._connect_impl()
    snapshot = controller.get_latest_snapshot()
    if snapshot.state not in (ConnectionState.CONNECTED, ConnectionState.CONFIGURING):
        print(f"[headless] 连接失败: {snapshot.status_message}")
        return 1
    print(f"[headless] {snapshot.status_message}")

    # 5. 设参
    print("[headless] 正在配置设备...")
    controller._configure_impl()
    snapshot = controller.get_latest_snapshot()
    print(f"[headless] {snapshot.status_message}")

    # 6. 启动采集
    print(f"[headless] 启动采集，持续 {args.duration} 秒...")
    controller._start_impl()

    # 7. 轮询快照
    start_time = time.monotonic()
    try:
        while not stop_flag:
            elapsed = time.monotonic() - start_time
            if elapsed >= args.duration:
                break
            time.sleep(args.poll_interval)
            snapshot = controller.get_latest_snapshot()
            print(
                f"[headless] t={elapsed:.1f}s | "
                f"state={snapshot.state.name} | "
                f"queue={snapshot.queue_size} | "
                f"recv={snapshot.stats.recv_rate_bytes_per_sec:.0f} B/s | "
                f"samples={snapshot.waveform.shape[0]} | "
                f"dropped={snapshot.stats.dropped_chunks}"
            )
            if snapshot.lockin:
                for li in snapshot.lockin:
                    print(
                        f"         Lock-in CH{li.channel}: "
                        f"A={li.amplitude:.6f}, P={li.phase_rad:.4f} rad"
                    )
    except KeyboardInterrupt:
        pass

    # 8. 停止
    print("[headless] 停止采集...")
    controller._stop_impl()

    # 9. 最终快照
    final = controller.get_latest_snapshot()
    print(f"[headless] 完成。"
          f"总包数={final.stats.packets}, "
          f"解析错误={final.stats.parse_errors}, "
          f"丢包={final.stats.dropped_chunks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
