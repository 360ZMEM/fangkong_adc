from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox


class ChannelPanel(QGroupBox):
    def __init__(self, active_channels: list[int], parent=None) -> None:
        super().__init__("通道选择", parent)
        layout = QGridLayout(self)
        self.checkboxes: list[QCheckBox] = []
        for ch in range(16):
            box = QCheckBox(f"CH{ch}")
            box.setChecked(ch in active_channels)
            self.checkboxes.append(box)
            layout.addWidget(box, ch // 4, ch % 4)

    def selected_channels(self) -> list[int]:
        return [idx for idx, box in enumerate(self.checkboxes) if box.isChecked()]
