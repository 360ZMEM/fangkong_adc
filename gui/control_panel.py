from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

TIMEBASE_PRESETS = [
    (100, 10),
    (200, 20),
    (500, 50),
    (1000, 100),
    (2000, 200),
]


class ControlPanel(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.unit_label = QLabel("波形 Y 轴单位")
        self.unit_combo = QComboBox()
        self.unit_combo.addItem("电压 (V)", "voltage")
        self.unit_combo.addItem("磁场 (μT)", "magnetic_field")
        self.timebase_label = QLabel("波形 X 轴时基")
        self.timebase_combo = QComboBox()
        for total_ms, div_ms in TIMEBASE_PRESETS:
            self.timebase_combo.addItem(f"{total_ms} ms / {div_ms} ms每格", (total_ms, div_ms))
        self.connect_btn = QPushButton("连接")
        self.config_btn = QPushButton("设参")
        self.start_btn = QPushButton("启动采集")
        self.stop_btn = QPushButton("停止采集")
        self.save_btn = QPushButton("保存配置")
        unit_index = self.unit_combo.findData(controller.config.runtime.waveform_y_unit)
        if unit_index >= 0:
            self.unit_combo.setCurrentIndex(unit_index)
        current_timebase = (
            controller.config.runtime.scope_total_window_ms,
            controller.config.runtime.scope_div_ms,
        )
        timebase_index = self.timebase_combo.findData(current_timebase)
        if timebase_index >= 0:
            self.timebase_combo.setCurrentIndex(timebase_index)
        else:
            self.timebase_combo.addItem(
                f"{current_timebase[0]} ms / {current_timebase[1]} ms每格",
                current_timebase,
            )
            self.timebase_combo.setCurrentIndex(self.timebase_combo.count() - 1)
        layout.addWidget(self.unit_label)
        layout.addWidget(self.unit_combo)
        layout.addWidget(self.timebase_label)
        layout.addWidget(self.timebase_combo)
        for btn in [
            self.connect_btn,
            self.config_btn,
            self.start_btn,
            self.stop_btn,
            self.save_btn,
        ]:
            layout.addWidget(btn)
        self.connect_btn.clicked.connect(self.controller.connect)
        self.config_btn.clicked.connect(self.controller.configure_device)
        self.start_btn.clicked.connect(self.controller.start_acquisition)
        self.stop_btn.clicked.connect(self.controller.stop_acquisition)
        self.save_btn.clicked.connect(self.controller.save_user_config)
        self.unit_combo.currentIndexChanged.connect(self._on_waveform_unit_changed)
        self.timebase_combo.currentIndexChanged.connect(self._on_timebase_changed)

    def _on_waveform_unit_changed(self) -> None:
        unit_mode = self.unit_combo.currentData()
        if isinstance(unit_mode, str):
            self.controller.set_waveform_unit(unit_mode)

    def _on_timebase_changed(self) -> None:
        timebase = self.timebase_combo.currentData()
        if isinstance(timebase, tuple) and len(timebase) == 2:
            self.controller.set_scope_timebase(int(timebase[0]), int(timebase[1]))
