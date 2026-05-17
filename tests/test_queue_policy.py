import queue
import threading

from network.network_worker import NetworkWorker


class DummyClient:
    pass


def test_drop_oldest_when_queue_full():
    q: queue.Queue[bytes] = queue.Queue(maxsize=2)
    worker = NetworkWorker(DummyClient(), q, threading.Event())  # type: ignore[arg-type]
    worker._put_chunk(b"old1")
    worker._put_chunk(b"old2")
    worker._put_chunk(b"new")
    assert worker.stats.dropped_chunks == 1
    assert q.get_nowait() == b"old2"
    assert q.get_nowait() == b"new"
