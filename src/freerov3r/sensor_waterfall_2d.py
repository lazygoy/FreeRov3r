"""Synchronized 2D sensor lanes for precise vehicle signal analysis."""
from __future__ import annotations

from bisect import bisect_left

import pyqtgraph as pg
from pyqtgraph import SignalProxy
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPen
from PySide6.QtWidgets import (
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

BACKGROUND = "#0B1220"
GRID = "#263449"
TEXT = "#CBD5E1"
LOCKED = "#FACC15"
PALETTE = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80",
           "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")


class _SensorPlotWidget(pg.PlotWidget):
    """PlotWidget that reports pointer entry/exit without stealing mouse input."""
    entered = Signal()
    left = Signal()

    def enterEvent(self, event):
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.left.emit()
        super().leaveEvent(event)


class SharedCrosshairStackedPlot(QWidget):
    """Stacked native-unit sensor plots with a shared, lockable time cursor.

    Each sensor retains its own Y scale. X coordinates are elapsed seconds from
    the same capture window, so cross-sensor timing comparisons remain honest.
    """
    cursorMoved = Signal(float)
    cursorLocked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lanes = []
        self.plots = []
        self._vertical_lines = []
        self._horizontal_lines = []
        self._proxies = []
        self._active_index = None
        self._cursor_time = None
        self._locked = False
        self._colors = {}
        self._updating_x = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: {BACKGROUND}; border: 0; }}"
        )
        self.content = QWidget()
        self.content.setStyleSheet(f"background: {BACKGROUND};")
        self.plot_layout = QVBoxLayout(self.content)
        self.plot_layout.setContentsMargins(4, 4, 4, 4)
        self.plot_layout.setSpacing(3)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        self.setStyleSheet(f"background: {BACKGROUND};")

    def set_lanes(self, lanes, colors=None):
        self.lanes = list(lanes or [])[:8]
        self._colors = dict(colors or {})
        self._clear_plots()
        if not self.lanes:
            placeholder = pg.LabelItem("Select one or more captured sensors")
            self.plot_layout.addWidget(placeholder)
            return

        for index, lane in enumerate(self.lanes):
            plot = _SensorPlotWidget()
            plot.setMinimumHeight(118)
            plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            plot.setBackground(BACKGROUND)
            plot.showGrid(x=True, y=True, alpha=0.22)
            plot.getAxis("left").setTextPen(QColor(TEXT))
            plot.getAxis("bottom").setTextPen(QColor(TEXT))
            plot.getAxis("left").setPen(QColor("#64748B"))
            plot.getAxis("bottom").setPen(QColor("#64748B"))
            plot.getAxis("left").setWidth(105)
            plot.setLabel("left", f'{lane["name"]} ({lane["unit"]})',
                          color=TEXT)
            if index == len(self.lanes) - 1:
                plot.setLabel("bottom", "Elapsed time", units="s", color=TEXT)
            else:
                plot.hideAxis("bottom")
            plot.getViewBox().setMouseEnabled(x=False, y=False)
            plot.getViewBox().setMenuEnabled(False)
            points = lane.get("raw_points") or lane.get("points") or []
            if points:
                x_values = [float(point[0]) for point in points]
                y_values = [float(point[1]) for point in points]
                color = self._colors.get(
                    lane["sensor_id"], PALETTE[index % len(PALETTE)]
                )
                curve = plot.plot(
                    x_values, y_values, pen=pg.mkPen(color, width=1.8),
                    connect="finite", antialias=True,
                )
                curve.setDownsampling(auto=True, method="peak")
                low, high = min(y_values), max(y_values)
                padding = max((high - low) * 0.12, abs(high) * 0.01, 0.01)
                plot.setYRange(low - padding, high + padding, padding=0)
            if self.plots:
                plot.setXLink(self.plots[0])
            vertical = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen("#94A3B8", width=1, style=Qt.DashLine),
            )
            horizontal = pg.InfiniteLine(
                angle=0, movable=False,
                pen=pg.mkPen("#64748B", width=1, style=Qt.DotLine),
            )
            plot.addItem(vertical, ignoreBounds=True)
            plot.addItem(horizontal, ignoreBounds=True)
            vertical.hide()
            horizontal.hide()
            self._vertical_lines.append(vertical)
            self._horizontal_lines.append(horizontal)
            self.plot_layout.addWidget(plot, 1)
            self.plots.append(plot)
            plot.entered.connect(lambda i=index: self._set_active(i))
            plot.left.connect(self._handle_plot_leave)
            proxy = SignalProxy(
                plot.scene().sigMouseMoved, rateLimit=60,
                slot=lambda event, i=index: self._mouse_moved(event, i),
            )
            self._proxies.append(proxy)
            plot.scene().sigMouseClicked.connect(
                lambda event, i=index: self._mouse_clicked(event, i)
            )

        self._sync_x_ranges()

    def _clear_plots(self):
        self._proxies.clear()
        self.plots.clear()
        self._vertical_lines.clear()
        self._horizontal_lines.clear()
        self._active_index = None
        while self.plot_layout.count():
            item = self.plot_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _sync_x_ranges(self):
        if not self.plots:
            return
        end = max(
            (float(point[0]) for lane in self.lanes
             for point in (lane.get("raw_points") or lane.get("points") or [])),
            default=1.0,
        )
        self.plots[0].setXRange(0.0, max(end, 0.1), padding=0)

    def _set_active(self, index):
        self._active_index = index
        for current, line in enumerate(self._horizontal_lines):
            line.setVisible(current == index and self._cursor_time is not None)

    def _handle_plot_leave(self):
        if self._locked:
            return
        # Moving between stacked plots should not clear the shared cursor.
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._hide_cursor()

    def _hide_cursor(self):
        if self._locked:
            return
        for line in self._vertical_lines + self._horizontal_lines:
            line.hide()
        self._active_index = None

    def _mouse_moved(self, event, index):
        if not event:
            return
        scene_pos = event[0]
        plot = self.plots[index]
        if not plot.sceneBoundingRect().contains(scene_pos):
            return
        point = plot.getViewBox().mapSceneToView(scene_pos)
        elapsed = float(point.x())
        self._cursor_time = elapsed
        self._active_index = index
        pen = pg.mkPen(LOCKED if self._locked else "#CBD5E1",
                       width=1.6 if self._locked else 1,
                       style=Qt.SolidLine if self._locked else Qt.DashLine)
        for current, line in enumerate(self._vertical_lines):
            line.setPos(elapsed)
            line.setPen(pen)
            line.show()
            horizontal = self._horizontal_lines[current]
            if current == index:
                horizontal.setPos(float(point.y()))
                horizontal.show()
            else:
                horizontal.hide()
        self.cursorMoved.emit(elapsed)

    def _mouse_clicked(self, event, index):
        if event.button() != Qt.LeftButton:
            return
        scene_pos = event.scenePos()
        plot = self.plots[index]
        if not plot.sceneBoundingRect().contains(scene_pos):
            return
        elapsed = float(plot.getViewBox().mapSceneToView(scene_pos).x())
        self._cursor_time = elapsed
        self._locked = not self._locked
        pen = pg.mkPen(LOCKED if self._locked else "#CBD5E1",
                       width=1.6 if self._locked else 1,
                       style=Qt.SolidLine if self._locked else Qt.DashLine)
        for line in self._vertical_lines:
            line.setPos(elapsed)
            line.setPen(pen)
            line.show()
        if self._locked:
            self.cursorLocked.emit(elapsed)
        else:
            self.cursorMoved.emit(elapsed)

    def clear_lock(self):
        self._locked = False
        self._hide_cursor()
