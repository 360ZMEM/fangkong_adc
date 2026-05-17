from __future__ import annotations

import numpy as np

try:  # pragma: no cover
    import pyqtgraph as pg
except ImportError:  # pragma: no cover
    pg = None


class WaveformPlot:
    def __init__(self, total_window_ms: int = 200, div_ms: int = 20, parent=None) -> None:
        if pg is None:
            raise RuntimeError("pyqtgraph 未安装")
        self.widget = pg.PlotWidget(parent=parent)
        self.widget.setLabel("left", "Voltage", units="V")
        self.widget.setLabel("bottom", "Time", units="ms")
        self.widget.addLegend()
        self.curves: dict[int, object] = {}
        self.total_window_ms = float(total_window_ms)
        self.div_ms = float(div_ms)
        self.channel_colors = {
            0: "#ff4d4f",
            1: "#52c41a",
            2: "#1677ff",
            3: "#faad14",
            4: "#722ed1",
            5: "#13c2c2",
        }
        self.widget.setClipToView(True)
        self.widget.enableAutoRange(axis="x", enable=False)
        self.widget.enableAutoRange(axis="y", enable=True)
        self.widget.showGrid(x=True, y=True, alpha=0.25)
        self.widget.getAxis("bottom").setTickSpacing(
            major=self.div_ms,
            minor=max(self.div_ms / 5.0, 1.0),
        )

    def update(self, waveform: np.ndarray, channels: list[int], sample_rate_hz: int) -> None:
        if waveform.size == 0:
            return
        max_points = max(1, int(round(sample_rate_hz * self.total_window_ms / 1000.0)))
        view = waveform[-max_points:]
        point_count = view.shape[0]
        x = (np.arange(point_count, dtype=np.float64) - (point_count - 1)) / float(sample_rate_hz) * 1000.0
        self.widget.setXRange(-self.total_window_ms, 0.0, padding=0.0)
        for idx, ch in enumerate(channels):
            if ch not in self.curves:
                color = self.channel_colors.get(ch, "#ffffff")
                self.curves[ch] = self.widget.plot(name=f"CH{ch}", pen=pg.mkPen(color=color, width=2))
            self.curves[ch].setData(x, view[:, idx])


class SpectrumPlot:
    def __init__(self, parent=None) -> None:
        if pg is None:
            raise RuntimeError("pyqtgraph 未安装")
        self.widget = pg.PlotWidget(parent=parent)
        self.widget.setLabel("left", "Amplitude")
        self.widget.setLabel("bottom", "Frequency", units="Hz")
        self.widget.addLegend()
        self.curves: dict[int, object] = {}
        self.channel_colors = {
            0: "#ff4d4f",
            1: "#52c41a",
            2: "#1677ff",
            3: "#faad14",
            4: "#722ed1",
            5: "#13c2c2",
        }
        self.widget.enableAutoRange(axis="x", enable=False)
        self.widget.setXRange(0.0, 200.0, padding=0.0)

    def update(self, freqs: np.ndarray, spectra: dict[int, np.ndarray]) -> None:
        if freqs.size == 0:
            return
        for ch, spec in spectra.items():
            if ch not in self.curves:
                color = self.channel_colors.get(ch, "#ffffff")
                self.curves[ch] = self.widget.plot(name=f"CH{ch}", pen=pg.mkPen(color=color, width=2))
            self.curves[ch].setData(freqs, spec)
