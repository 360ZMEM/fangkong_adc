from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import time

import numpy as np

from config.settings import StorageConfig
from .models import LatestSnapshot, LockinResult


class DataStorage:
    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self.root = Path(config.root_dir)
        stamp = datetime.now().strftime("%Y%m%d/session_%H%M%S")
        self.raw_dir = self.root / "raw" / stamp
        self.feature_dir = self.root / "features" / stamp
        self._last_flush = 0.0
        self._feature_file = self.feature_dir / "lockin.csv"
        self._events_file = self.feature_dir / "events.csv"
        self._feature_header_written = False

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def maybe_write_snapshot(self, snapshot: LatestSnapshot) -> None:
        if not self.config.enabled:
            return
        now = time.monotonic()
        if now - self._last_flush < self.config.flush_interval_sec:
            return
        self._last_flush = now
        self.ensure_dirs()
        if self.config.raw_npz_enabled and snapshot.waveform.size:
            self.write_npz(snapshot)
        if self.config.feature_csv_enabled and snapshot.lockin:
            self.append_lockin(snapshot)

    def write_npz(self, snapshot: LatestSnapshot) -> None:
        path = self.raw_dir / f"waveform_{int(snapshot.timestamp * 1000)}.npz"
        np.savez_compressed(
            path,
            timestamp=snapshot.timestamp,
            sample_rate_hz=snapshot.sample_rate_hz,
            channels=np.array(snapshot.channels, dtype=np.int16),
            voltage=snapshot.waveform,
        )

    def append_lockin(self, snapshot: LatestSnapshot) -> None:
        self.ensure_dirs()
        write_header = not self._feature_header_written and not self._feature_file.exists()
        with self._feature_file.open("a", newline="", encoding="utf-8") as f:
            fieldnames = [
                "timestamp",
                "channel",
                "lockin_freq_hz",
                "amplitude",
                "phase_rad",
                "i_component",
                "q_component",
                "queue_size",
                "dropped_chunks",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
                self._feature_header_written = True
            for item in snapshot.lockin:
                writer.writerow(_lockin_row(snapshot, item))

    def append_event(self, message: str) -> None:
        if not self.config.enabled:
            return
        self.ensure_dirs()
        exists = self._events_file.exists()
        with self._events_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "message"])
            if not exists:
                writer.writeheader()
            writer.writerow({"timestamp": time.time(), "message": message})


def _lockin_row(snapshot: LatestSnapshot, item: LockinResult) -> dict[str, float | int]:
    return {
        "timestamp": snapshot.timestamp,
        "channel": item.channel,
        "lockin_freq_hz": item.frequency_hz,
        "amplitude": item.amplitude,
        "phase_rad": item.phase_rad,
        "i_component": item.i_component,
        "q_component": item.q_component,
        "queue_size": snapshot.queue_size,
        "dropped_chunks": snapshot.stats.dropped_chunks,
    }
