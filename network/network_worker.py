from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .tcp_client import TcpClient, TcpClientError


@dataclass
class NetworkWorkerStats:
    bytes_received: int = 0
    chunks_received: int = 0
    dropped_chunks: int = 0
    last_error: str = ""
    last_recv_monotonic: float = 0.0


class NetworkWorker(threading.Thread):
    """生产者线程：仅负责 socket.recv() 并推入原始字节队列。"""

    def __init__(
        self,
        client: TcpClient,
        raw_queue: queue.Queue[bytes],
        stop_event: threading.Event,
        stats: NetworkWorkerStats | None = None,
        on_error: Callable[[Exception], None] | None = None,
        recv_size: int = 4096,
    ) -> None:
        super().__init__(name="NetworkWorker", daemon=True)
        self.client = client
        self.raw_queue = raw_queue
        self.stop_event = stop_event
        self.stats = stats or NetworkWorkerStats()
        self.on_error = on_error
        self.recv_size = recv_size

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                chunk = self.client.recv_some(self.recv_size)
                if not chunk:
                    continue
                self._put_chunk(chunk)
                self.stats.bytes_received += len(chunk)
                self.stats.chunks_received += 1
                self.stats.last_recv_monotonic = time.monotonic()
            except TcpClientError as exc:
                self.stats.last_error = str(exc)
                if self.on_error:
                    self.on_error(exc)
                break

    def _put_chunk(self, chunk: bytes) -> None:
        try:
            self.raw_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self.raw_queue.get_nowait()
                self.stats.dropped_chunks += 1
            except queue.Empty:
                pass
            self.raw_queue.put_nowait(chunk)
