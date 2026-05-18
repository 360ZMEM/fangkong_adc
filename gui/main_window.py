from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QSplitter, QVBoxLayout, QWidget

from .channel_panel import ChannelPanel
from .control_panel import ControlPanel
from .plot_widgets import SpectrumPlot, WaveformPlot
from .status_panel import StatusPanel


class MainWindow(QMainWindow):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("SK2301 以太网 ADC 实时采集")
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        left = QWidget()
        left.setMinimumWidth(360)
        left.setMaximumWidth(360)
        left_layout = QVBoxLayout(left)
        self.control_panel = ControlPanel(controller)
        self.channel_panel = ChannelPanel(controller.config.device.active_channels)
        self.status_panel = StatusPanel()
        left_layout.addWidget(self.control_panel)
        left_layout.addWidget(self.channel_panel)
        left_layout.addWidget(self.status_panel)

        plots = QWidget()
        plots_layout = QVBoxLayout(plots)
        self.waveform_plot = WaveformPlot(
            total_window_ms=controller.config.runtime.scope_total_window_ms,
            div_ms=controller.config.runtime.scope_div_ms,
            unit_mode=controller.config.runtime.waveform_y_unit,
            sensor_sensitivity_mv_per_ut=controller.config.device.sensor_sensitivity_mv_per_ut,
        )
        self.spectrum_plot = SpectrumPlot()
        plots_layout.addWidget(self.waveform_plot.widget)
        plots_layout.addWidget(self.spectrum_plot.widget)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(plots)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        interval_ms = max(1, int(1000 / controller.config.runtime.ui_refresh_hz))
        self.timer.start(interval_ms)

        for box in self.channel_panel.checkboxes:
            box.stateChanged.connect(self._on_channels_changed)

    def refresh(self) -> None:
        snapshot = self.controller.get_latest_snapshot()
        self.status_panel.update_snapshot(snapshot)
        self.waveform_plot.set_display_config(
            total_window_ms=self.controller.config.runtime.scope_total_window_ms,
            div_ms=self.controller.config.runtime.scope_div_ms,
            unit_mode=self.controller.config.runtime.waveform_y_unit,
            sensor_sensitivity_mv_per_ut=self.controller.config.device.sensor_sensitivity_mv_per_ut,
        )
        self.waveform_plot.update(snapshot.waveform, snapshot.channels, snapshot.sample_rate_hz)
        self.spectrum_plot.update(snapshot.fft.freqs, snapshot.fft.spectra)

    def _on_channels_changed(self) -> None:
        self.controller.set_active_channels(self.channel_panel.selected_channels())

    def closeEvent(self, event) -> None:  # pragma: no cover
        self.controller.shutdown()
        super().closeEvent(event)
