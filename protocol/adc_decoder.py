from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class DecodeStats:
    samples_total: int = 0
    channel_mismatch_count: int = 0
    truncated_bytes: int = 0


@dataclass
class DecodedAdcData:
    voltages: np.ndarray
    raw24: np.ndarray
    channel_ids: np.ndarray
    channels: list[int]
    stats: DecodeStats


@dataclass
class ActiveChannelDecodeState:
    pending_raw: list[int] = field(default_factory=list)
    pending_ids: list[int] = field(default_factory=list)


class ActiveChannelDecoder:
    """按激活通道序列重组跨包样本，解决非 16 通道模式下的对齐问题。"""

    def __init__(self, active_channels: list[int], voltage_range: float = 10.0) -> None:
        if not active_channels:
            raise ValueError("active_channels 不能为空")
        self.active_channels = list(active_channels)
        self.active_channel_set = set(active_channels)
        self.voltage_range = voltage_range
        self.state = ActiveChannelDecodeState()

    def decode(self, payload: bytes) -> DecodedAdcData:
        raw24_signed, channel_ids_flat, stats = _parse_payload(payload)
        current_raw = list(self.state.pending_raw)
        current_ids = list(self.state.pending_ids)
        expected_idx = len(current_ids)
        frames: list[list[int]] = []
        frame_ids: list[list[int]] = []

        for raw_value, channel_id in zip(raw24_signed.tolist(), channel_ids_flat.tolist()):
            if channel_id not in self.active_channel_set:
                stats.channel_mismatch_count += 1
                continue

            expected_channel = self.active_channels[expected_idx]
            if channel_id == expected_channel:
                current_raw.append(raw_value)
                current_ids.append(channel_id)
                expected_idx += 1
                if expected_idx == len(self.active_channels):
                    frames.append(current_raw)
                    frame_ids.append(current_ids)
                    current_raw = []
                    current_ids = []
                    expected_idx = 0
                continue

            stats.channel_mismatch_count += 1
            if channel_id == self.active_channels[0]:
                current_raw = [raw_value]
                current_ids = [channel_id]
                expected_idx = 1
            else:
                current_raw = []
                current_ids = []
                expected_idx = 0

        self.state.pending_raw = current_raw
        self.state.pending_ids = current_ids
        stats.truncated_bytes += len(current_raw) * 4
        if not frames:
            empty = np.empty((0, len(self.active_channels)), dtype=np.float64)
            return DecodedAdcData(
                voltages=empty,
                raw24=np.empty((0, len(self.active_channels)), dtype=np.int32),
                channel_ids=np.empty((0, len(self.active_channels)), dtype=np.uint8),
                channels=list(self.active_channels),
                stats=stats,
            )

        raw24_matrix = np.asarray(frames, dtype=np.int32)
        channel_matrix = np.asarray(frame_ids, dtype=np.uint8)
        stats.samples_total = int(raw24_matrix.shape[0] * raw24_matrix.shape[1])
        scale = self.voltage_range / float(1 << 23)
        voltages = raw24_matrix.astype(np.float64) * scale
        return DecodedAdcData(
            voltages=voltages,
            raw24=raw24_matrix,
            channel_ids=channel_matrix,
            channels=list(self.active_channels),
            stats=stats,
        )


def decode_24bit_samples(
    payload: bytes,
    active_channels: list[int],
    total_channels: int = 16,
    voltage_range: float = 10.0,
) -> DecodedAdcData:
    if total_channels <= 0:
        raise ValueError("total_channels 必须为正数")
    if any(ch < 0 or ch >= total_channels for ch in active_channels):
        raise ValueError("active_channels 存在非法通道号")

    raw24_signed, channel_ids_flat, stats = _parse_payload(payload)

    full_frames = len(raw24_signed) // total_channels
    stats.truncated_bytes += (len(raw24_signed) - full_frames * total_channels) * 4
    if full_frames == 0:
        empty = np.empty((0, len(active_channels)), dtype=np.float64)
        return DecodedAdcData(
            empty,
            np.empty((0, 0), dtype=np.int32),
            np.empty((0, 0), dtype=np.uint8),
            active_channels,
            stats,
        )

    raw24_matrix = raw24_signed[: full_frames * total_channels].reshape(full_frames, total_channels)
    channel_matrix = channel_ids_flat[: full_frames * total_channels].reshape(full_frames, total_channels)
    expected = np.tile(np.arange(total_channels, dtype=np.uint8), (full_frames, 1))
    stats.channel_mismatch_count = int(np.count_nonzero(channel_matrix != expected))
    stats.samples_total = int(full_frames * total_channels)

    scale = voltage_range / 0x80000000
    volt_full = raw24_matrix.astype(np.float64) * scale
    voltages = volt_full[:, active_channels]
    return DecodedAdcData(voltages, raw24_matrix, channel_matrix, active_channels, stats)


def _parse_payload(payload: bytes) -> tuple[np.ndarray, np.ndarray, DecodeStats]:
    usable_len = (len(payload) // 4) * 4
    stats = DecodeStats(truncated_bytes=len(payload) - usable_len)
    if usable_len == 0:
        return np.empty(0, dtype=np.int32), np.empty(0, dtype=np.uint8), stats

    raw = np.frombuffer(payload[:usable_len], dtype=np.uint8).reshape(-1, 4)
    high = raw[:, 0].astype(np.int32)
    mid = raw[:, 1].astype(np.int32)
    low = raw[:, 2].astype(np.int32)
    channel_ids_flat = raw[:, 3].astype(np.uint8)

    raw24_flat = (high << 16) | (mid << 8) | low
    sign_mask = 1 << 23
    raw24_signed = ((raw24_flat ^ sign_mask) - sign_mask).astype(np.int32)
    return raw24_signed, channel_ids_flat, stats


def encode_test_sample(raw24: int, channel_id: int) -> bytes:
    if not -(1 << 23) <= raw24 < (1 << 23):
        raise ValueError("raw24 超出 24bit 有符号范围")
    unsigned = raw24 & 0xFFFFFF
    return bytes(
        [
            (unsigned >> 16) & 0xFF,
            (unsigned >> 8) & 0xFF,
            unsigned & 0xFF,
            channel_id & 0xFF,
        ]
    )
