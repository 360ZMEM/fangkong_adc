from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class ControlPanel(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.connect_btn = QPushButton("连接")
        self.config_btn = QPushButton("设参")
        self.start_btn = QPushButton("启动采集")
        self.stop_btn = QPushButton("停止采集")
        self.save_btn = QPushButton("保存配置")
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
