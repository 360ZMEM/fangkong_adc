from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class StatusPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        self.mode_label = QLabel("模式: Debug 交互")
        self.state_label = QLabel("状态: 未连接")
        self.queue_label = QLabel("队列: 0")
        self.drop_label = QLabel("丢包: 0")
        self.parse_label = QLabel("解析错误: 0")
        self.rate_label = QLabel("接收速率: 0 B/s")
        self.latency_label = QLabel("DSP 延迟: 0 ms")
        self.warning_label = QLabel("告警: 无")
        self.lockin_label = QLabel("Lock-in: --")
        self.lockin_label.setWordWrap(True)
        for widget in [
            self.mode_label,
            self.state_label,
            self.queue_label,
            self.drop_label,
            self.parse_label,
            self.rate_label,
            self.latency_label,
            self.warning_label,
            self.lockin_label,
        ]:
            layout.addWidget(widget)

    def update_snapshot(self, snapshot) -> None:
        self.mode_label.setText(f"模式: {snapshot.mode}")
        self.state_label.setText(f"状态: {snapshot.state.name} / {snapshot.status_message}")
        self.queue_label.setText(f"队列: {snapshot.queue_size}")
        self.drop_label.setText(
            f"丢包: 网络={snapshot.stats.dropped_chunks} / 协议={snapshot.stats.packet_loss_count}"
        )
        self.parse_label.setText(
            f"解析错误: {snapshot.stats.parse_errors} / 通道错位: {snapshot.stats.channel_mismatch_count}"
        )
        self.rate_label.setText(f"接收速率: {snapshot.stats.recv_rate_bytes_per_sec:.1f} B/s")
        self.latency_label.setText(f"DSP 延迟: {snapshot.stats.dsp_latency_ms:.2f} ms")
        self.warning_label.setText(f"告警: {snapshot.warning_message or '无'}")
        if snapshot.lockin:
            text = " | ".join(
                f"CH{x.channel}: A={x.amplitude:.3e}, P={x.phase_rad:.2f}"
                for x in snapshot.lockin
            )
        else:
            text = "--"
        self.lockin_label.setText(f"Lock-in: {text}")
