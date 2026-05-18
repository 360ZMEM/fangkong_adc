from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    def __init__(self, capacity_samples: int, channel_count: int) -> None:
        if capacity_samples <= 0 or channel_count <= 0:
            raise ValueError("capacity_samples 和 channel_count 必须为正数")
        self.capacity_samples = capacity_samples
        self.channel_count = channel_count
        self._data = np.zeros((capacity_samples, channel_count), dtype=np.float64)
        self._write_index = 0
        self._size = 0
        self._lock = threading.Lock()

    def append(self, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        arr = np.asarray(samples, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != self.channel_count:
            raise ValueError(f"样本维度必须为 (n, {self.channel_count})")
        with self._lock:
            if arr.shape[0] >= self.capacity_samples:
                arr = arr[-self.capacity_samples :]
            first_count = min(arr.shape[0], self.capacity_samples - self._write_index)
            self._data[self._write_index : self._write_index + first_count] = arr[:first_count]
            remaining = arr.shape[0] - first_count
            if remaining > 0:
                self._data[:remaining] = arr[first_count:]
            self._write_index = (self._write_index + arr.shape[0]) % self.capacity_samples
            self._size = min(self._size + arr.shape[0], self.capacity_samples)

    def latest(self, count: int | None = None) -> np.ndarray:
        with self._lock:
            size = self._size if count is None else min(count, self._size)
            if size <= 0:
                return np.empty((0, self.channel_count), dtype=np.float64)
            start = (self._write_index - size) % self.capacity_samples
            if start + size <= self.capacity_samples:
                return self._data[start : start + size].copy()
            first = self._data[start:]
            second = self._data[: size - len(first)]
            return np.vstack([first, second]).copy()

    def latest_window(self, window_size: int) -> np.ndarray:
        return self.latest(window_size)

    def resize(self, new_capacity_samples: int) -> None:
        if new_capacity_samples <= 0:
            raise ValueError("new_capacity_samples 必须为正数")
        with self._lock:
            if new_capacity_samples == self.capacity_samples:
                return
            size = min(self._size, new_capacity_samples)
            if size <= 0:
                latest = np.empty((0, self.channel_count), dtype=np.float64)
            else:
                start = (self._write_index - size) % self.capacity_samples
                if start + size <= self.capacity_samples:
                    latest = self._data[start : start + size].copy()
                else:
                    first = self._data[start:]
                    second = self._data[: size - len(first)]
                    latest = np.vstack([first, second]).copy()
            self.capacity_samples = new_capacity_samples
            self._data = np.zeros((new_capacity_samples, self.channel_count), dtype=np.float64)
            if size > 0:
                self._data[:size] = latest
            self._write_index = size % new_capacity_samples
            self._size = size

    @property
    def size(self) -> int:
        with self._lock:
            return self._size
