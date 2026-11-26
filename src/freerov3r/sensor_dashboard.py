"""Dockable multi-panel live sensor dashboard."""

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDockWidget, QGridLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .sensors.scaling import sample_clock, sample_time


PANEL_COUNTS = (1, 2, 4, 6, 8)
TIME_WINDOWS = (
    ("10 seconds", 10),
    ("30 seconds", 30),
    ("1 minute", 60),
    ("5 minutes", 300),
    ("15 minutes", 900),
    ("All samples", 0),
)


def panel_grid_dimensions(count):
    """Return a compact two-column dashboard grid for 1–8 panels."""
    if count not in PANEL_COUNTS:
        raise ValueError(f"panel count must be one of {PANEL_COUNTS}")
    return (1, 1) if count == 1 else (2, (count + 1) // 2)


def normalize_dashboard_layout(layout):
    """Validate persisted dashboard settings and fill missing panel defaults."""
    if not isinstance(layout, dict):
        layout = {}
    count = layout.get("panel_count", 4)
    if count not in PANEL_COUNTS:
        count = 4
    configs = layout.get("panels", [])
    if not isinstance(configs, list):
        configs = []
    allowed_windows = {seconds for _, seconds in TIME_WINDOWS}
    panels = []
    for index in range(max(PANEL_COUNTS)):
        config = configs[index] if index < len(configs) and isinstance(configs[index], dict) else {}
        ids = config.get("sensor_ids", [])
        if not isinstance(ids, (list, tuple, set)):
            ids = []
        window = config.get("window_seconds", 60)
        if window not in allowed_windows:
            window = 60
        panels.append({
            "sensor_ids": sorted({str(value) for value in ids if str(value).strip()}),
            "window_seconds": window,
            "auto_scale": bool(config.get("auto_scale", True)),
        })
    return {"version": 1, "panel_count": count, "panels": panels}


class _FloatingGraphWindow(QDialog):
    def __init__(self, dock, panel):
        super().__init__(dock)
        self.dock = dock
        self.panel = panel
        self._restoring = False
        self.setWindowTitle(f"FreeRov3r | {panel.windowTitle()}")
        self.resize(760, 460)
        layout = QVBoxLayout(self)
        panel.setParent(self)
        layout.addWidget(panel)

    def closeEvent(self, event):
        if not self._restoring:
            self.dock.restore_panel(self.panel, self)
        event.accept()


class SensorGraphPanel(QWidget):
    """One independently configured sensor graph."""

    def __init__(self, sensor_capture, index, dock):
        super().__init__(dock)
        self.sensor_capture = sensor_capture
        self.index = index
        self.dock = dock
        self.vehicle_vin = None
        self._floating_host = None
        self.setWindowTitle(f"Graph {index + 1}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        outer.setSpacing(4)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(f"GRAPH {index + 1}"))
        self.window_combo = QComboBox()
        for label, seconds in TIME_WINDOWS:
            self.window_combo.addItem(label, seconds)
        self.window_combo.setCurrentIndex(2)
        self.window_combo.currentIndexChanged.connect(self.update_chart)
        self.window_combo.currentIndexChanged.connect(self.dock.persist_layout)
        controls.addWidget(self.window_combo)
        self.auto_scale = QCheckBox("Auto scale")
        self.auto_scale.setChecked(True)
        self.auto_scale.toggled.connect(self.update_chart)
        self.auto_scale.toggled.connect(self.dock.persist_layout)
        controls.addWidget(self.auto_scale)
        self.popout_button = QPushButton("Pop out")
        self.popout_button.clicked.connect(self.toggle_popout)
        controls.addWidget(self.popout_button)
        self.topmost = QCheckBox("Stay on top")
        self.topmost.setEnabled(False)
        self.topmost.toggled.connect(self._set_topmost)
        controls.addWidget(self.topmost)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.sensor_list = QListWidget()
        self.sensor_list.setMaximumHeight(74)
        self.sensor_list.setToolTip(
            "Select one or more signals for this graph. Each graph has its own sensor selection."
        )
        self.sensor_list.itemChanged.connect(self.update_chart)
        self.sensor_list.itemChanged.connect(self.dock.persist_layout)
        outer.addWidget(self.sensor_list)

        if HAS_CHARTS:
            self.chart = QChart()
            self.chart.legend().setVisible(True)
            self.chart.setAnimationOptions(QChart.NoAnimation)
            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.chart_view.setRubberBand(QChartView.RectangleRubberBand)
            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("Elapsed time (s)")
            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("Value")
            self.chart.addAxis(self.axis_x, Qt.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignLeft)
            outer.addWidget(self.chart_view, 1)
        else:
            outer.addWidget(QLabel("Qt Charts is unavailable. Install the PySide6 Charts component."))

    def set_vehicle_vin(self, vin):
        self.vehicle_vin = vin
        self.refresh_sensor_choices()

    def refresh_sensor_choices(self, initial_ids=None):
        selected = {
            self._item_sensor_id(self.sensor_list.item(i))
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        }
        if initial_ids is not None:
            selected = set(initial_ids)
        available = {}
        for sample in self.sensor_capture.samples:
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            available.setdefault(sample.sensor_id, sample.name)
        for sensor_id in selected:
            available.setdefault(sensor_id, sensor_id)
        existing = {
            self._item_sensor_id(self.sensor_list.item(i)): self.sensor_list.item(i).text()
            for i in range(self.sensor_list.count())
        }
        expected = {sensor_id: f"{name} ({sensor_id})" for sensor_id, name in available.items()}
        if existing == expected:
            self.update_chart()
            return
        self.sensor_list.blockSignals(True)
        self.sensor_list.clear()
        for sensor_id, name in sorted(available.items(), key=lambda item: item[1].casefold()):
            item = QListWidgetItem(f"{name} ({sensor_id})")
            item.setData(Qt.UserRole, sensor_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if sensor_id in selected else Qt.Unchecked)
            self.sensor_list.addItem(item)
        self.sensor_list.blockSignals(False)
        self.update_chart()

    @staticmethod
    def _item_sensor_id(item):
        return item.data(Qt.UserRole)

    def selected_sensor_ids(self):
        return {
            self._item_sensor_id(self.sensor_list.item(i))
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        }

    def update_chart(self, *_):
        if not HAS_CHARTS:
            return
        self.chart.removeAllSeries()
        selected_ids = self.selected_sensor_ids()
        grouped = {}
        for sample in self.sensor_capture.samples:
            if sample.sensor_id not in selected_ids:
                continue
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            if sample.quality != "valid" or not math.isfinite(sample.value):
                continue
            grouped.setdefault(sample.sensor_id, []).append(sample)

        all_samples = [sample for values in grouped.values() for sample in values]
        if not all_samples:
            self.axis_x.setRange(0, 1)
            self.axis_y.setRange(0, 1)
            return

        clock = sample_clock(all_samples)
        latest = max(sample_time(sample, clock) for sample in all_samples)
        window = int(self.window_combo.currentData())
        start = min(sample_time(sample, clock) for sample in all_samples)
        if window:
            start = max(start, latest - window)
        plotted_values = []

        for sensor_id, samples in grouped.items():
            samples = sorted(samples, key=lambda sample: sample_time(sample, clock))
            samples = [
                sample for sample in samples
                if sample_time(sample, clock) >= start
            ][-2000:]
            if not samples:
                continue
            series = QLineSeries()
            first = samples[0]
            series.setName(f"{first.name} [{first.unit or 'unitless'}]")
            hue = sum(sensor_id.encode("utf-8")) % 360
            series.setColor(QColor.fromHsv(hue, 190, 220))
            for sample in samples:
                value = float(sample.value)
                series.append(sample_time(sample, clock) - start, value)
                plotted_values.append(value)
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)

        duration = max(0.1, latest - start)
        self.axis_x.setRange(0, duration)
        if plotted_values:
            low, high = min(plotted_values), max(plotted_values)
            if self.auto_scale.isChecked():
                padding = max((high - low) * 0.12, abs(high) * 0.01, 0.1)
                self.axis_y.setRange(low - padding, high + padding)

    def toggle_popout(self):
        if self._floating_host is None:
            self.dock.popout_panel(self)
        else:
            self.dock.restore_panel(self, self._floating_host)

    def _refresh_favorites(self, selected_name=None):
        groups = self.settings.get("obd_pid_favorites", {})
        self.favorite_combo.blockSignals(True)
        self.favorite_combo.clear()
        self.favorite_combo.addItem("Choose sensor favorite…", None)
        if isinstance(groups, dict):
            for name in sorted(groups, key=str.casefold):
                self.favorite_combo.addItem(name, name)
        if selected_name:
            index = self.favorite_combo.findData(selected_name)
            if index >= 0:
                self.favorite_combo.setCurrentIndex(index)
        self.favorite_combo.blockSignals(False)
        self.load_favorite_button.setEnabled(self.favorite_combo.currentData() is not None)
        self.save_favorite_button.setEnabled(self.favorite_combo.currentData() is not None)

    def _favorite_selection_changed(self, *_):
        enabled = self.favorite_combo.currentData() is not None
        self.load_favorite_button.setEnabled(enabled)
        self.save_favorite_button.setEnabled(enabled)

    def _layout_payload(self):
        return normalize_dashboard_layout({
            "version": 1,
            "panel_count": int(self.panel_count.currentData()),
            "panels": [
                {
                    "sensor_ids": sorted(panel.selected_sensor_ids()),
                    "window_seconds": int(panel.window_combo.currentData()),
                    "auto_scale": panel.auto_scale.isChecked(),
                }
                for panel in self.panels
            ],
        })

    def persist_layout(self, *_):
        if self._loading_config:
            return
        self.settings["sensor_dashboard_layout"] = self._layout_payload()
        if callable(self.save_settings_callback):
            self.save_settings_callback(self.settings)

    def _restore_saved_layout(self):
        stored = self.settings.get("sensor_dashboard_layout")
        if not isinstance(stored, dict):
            return
        layout = normalize_dashboard_layout(stored)
        self._loading_config = True
        try:
            count = layout["panel_count"]
            self.panel_count.setCurrentIndex(PANEL_COUNTS.index(count))
            configs = layout["panels"]
            for index, panel in enumerate(self.panels):
                config = configs[index] if index < len(configs) and isinstance(configs[index], dict) else {}
                ids = config.get("sensor_ids", [])
                if not isinstance(ids, list):
                    ids = []
                panel.refresh_sensor_choices(ids)
                seconds = config.get("window_seconds", 60)
                window_index = panel.window_combo.findData(seconds)
                panel.window_combo.setCurrentIndex(window_index if window_index >= 0 else 2)
                panel.auto_scale.setChecked(bool(config.get("auto_scale", True)))
        finally:
            self._loading_config = False

    def load_favorite(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        self._refresh_favorites(name)
        layouts = self.settings.get("sensor_dashboard_favorites", {})
        layout = layouts.get(name) if isinstance(layouts, dict) else None
        if isinstance(layout, dict):
            self._apply_layout(layout)
        else:
            groups = self.settings.get("obd_pid_favorites", {})
            sensor_ids = groups.get(name, []) if isinstance(groups, dict) else []
            if not isinstance(sensor_ids, (list, tuple, set)):
                sensor_ids = []
            self._loading_config = True
            try:
                for index, panel in enumerate(self.panels):
                    panel.refresh_sensor_choices(set(sensor_ids) if index == 0 else set())
                self.panel_count.setCurrentIndex(0)
            finally:
                self._loading_config = False
            self.reflow()
            self.persist_layout()

    def _apply_layout(self, layout):
        layout = normalize_dashboard_layout(layout)
        self._loading_config = True
        try:
            count = layout["panel_count"]
            self.panel_count.setCurrentIndex(PANEL_COUNTS.index(count))
            configs = layout["panels"]
            for index, panel in enumerate(self.panels):
                config = configs[index] if index < len(configs) and isinstance(configs[index], dict) else {}
                ids = config.get("sensor_ids", [])
                panel.refresh_sensor_choices(set(ids) if isinstance(ids, list) else set())
                seconds = config.get("window_seconds", 60)
                window_index = panel.window_combo.findData(seconds)
                panel.window_combo.setCurrentIndex(window_index if window_index >= 0 else 2)
                panel.auto_scale.setChecked(bool(config.get("auto_scale", True)))
        finally:
            self._loading_config = False
        self.reflow()
        self.persist_layout()

    def save_layout_to_favorite(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        layouts = self.settings.get("sensor_dashboard_favorites", {})
        if not isinstance(layouts, dict):
            layouts = {}
        layouts = dict(layouts)
        layouts[name] = self._layout_payload()
        self.settings["sensor_dashboard_favorites"] = layouts
        if callable(self.save_settings_callback):
            self.save_settings_callback(self.settings)
        self._refresh_favorites(name)

    def _set_topmost(self, checked):
        if self._floating_host is None:
            return
        host = self._floating_host
        host.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        host.show()


class SensorDashboardDock(QDockWidget):
    """Application-wide dock containing up to eight independently configured graphs."""

    def __init__(
        self, sensor_capture, parent=None, initial_sensor_ids=None, vin_provider=None,
        settings=None, save_settings_callback=None,
    ):
        super().__init__("Sensor Dashboard", parent)
        self.sensor_capture = sensor_capture
        self.vin_provider = vin_provider or (lambda: None)
        self.initial_sensor_ids = set(initial_sensor_ids or ())
        self.settings = settings if isinstance(settings, dict) else {}
        self.save_settings_callback = save_settings_callback
        self._loading_config = False
        self.setObjectName("sensorDashboardDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )

        container = QWidget(self)
        self.container = container
        outer = QVBoxLayout(container)
        outer.setContentsMargins(6, 6, 6, 6)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Visible graphs:"))
        self.panel_count = QComboBox()
        for count in PANEL_COUNTS:
            self.panel_count.addItem(str(count), count)
        self.panel_count.setCurrentIndex(2)
        self.panel_count.currentIndexChanged.connect(self.reflow)
        self.panel_count.currentIndexChanged.connect(self.persist_layout)
        controls.addWidget(self.panel_count)
        controls.addWidget(QLabel("Sensor favorite:"))
        self.favorite_combo = QComboBox()
        self.favorite_combo.setMinimumWidth(150)
        self.favorite_combo.currentIndexChanged.connect(self._favorite_selection_changed)
        controls.addWidget(self.favorite_combo)
        self.load_favorite_button = QPushButton("Load")
        self.load_favorite_button.clicked.connect(self.load_favorite)
        controls.addWidget(self.load_favorite_button)
        self.save_favorite_button = QPushButton("Save layout")
        self.save_favorite_button.clicked.connect(self.save_layout_to_favorite)
        controls.addWidget(self.save_favorite_button)
        controls.addStretch(1)
        self.topmost = QCheckBox("Floating dashboard stays on top")
        self.topmost.toggled.connect(self._set_topmost)
        controls.addWidget(self.topmost)
        outer.addLayout(controls)

        self.grid_host = QWidget(container)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        outer.addWidget(self.grid_host, 1)
        self.setWidget(container)

        self.panels = [
            SensorGraphPanel(sensor_capture, index, self)
            for index in range(max(PANEL_COUNTS))
        ]
        self._visible_count = 4
        self._refresh_favorites()
        self._restore_saved_layout()
        self.refresh()
        if self.initial_sensor_ids and not self.panels[0].selected_sensor_ids():
            self.panels[0].refresh_sensor_choices(self.initial_sensor_ids)
        self.reflow()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(750)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

    def _set_topmost(self, checked):
        if checked and not self.isFloating():
            self.setFloating(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def refresh(self):
        vin = self.vin_provider()
        for panel in self.panels:
            panel.set_vehicle_vin(vin)
        self._refresh_favorites(self.favorite_combo.currentData())

    def reflow(self, *_):
        count = int(self.panel_count.currentData())
        self._visible_count = count
        for panel in self.panels:
            self.grid.removeWidget(panel)
            panel.hide()
            if panel._floating_host is None:
                panel.setParent(self.grid_host)
        rows, columns = panel_grid_dimensions(count)
        for index, panel in enumerate(self.panels[:count]):
            if panel._floating_host is not None:
                continue
            self.grid.addWidget(panel, index // columns, index % columns)
            panel.show()
        self.grid_host.updateGeometry()

    def popout_panel(self, panel):
        if panel._floating_host is not None:
            return
        self.grid.removeWidget(panel)
        panel.hide()
        host = _FloatingGraphWindow(self, panel)
        panel._floating_host = host
        panel.popout_button.setText("Dock back")
        panel.topmost.setEnabled(True)
        host.show()

    def restore_panel(self, panel, host):
        if panel._floating_host is not host:
            return
        host._restoring = True
        host.hide()
        panel._floating_host = None
        panel.topmost.blockSignals(True)
        panel.topmost.setChecked(False)
        panel.topmost.blockSignals(False)
        panel.topmost.setEnabled(False)
        panel.popout_button.setText("Pop out")
        panel.setParent(self.grid_host)
        panel.show()
        self.reflow()
        host.deleteLater()
