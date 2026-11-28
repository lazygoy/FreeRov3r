"""Dockable multi-panel live sensor dashboard."""

import math
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QMargins
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
    QInputDialog, QFileDialog, QMessageBox,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .sensors.scaling import sample_clock, sample_time
from .sensors.correlation import correlate_sensor_series, make_event_marker
from .sensors.presets import PRESET_GROUPS, build_sensor_preset
from .sensor_waterfall import SensorWaterfallDialog
from .diagnostics.obd2 import OBD_PIDS


PANEL_COUNTS = (1, 2, 4)
GRAPH_PALETTE = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80", "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")
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
            "sensor_ids": sorted({str(value).strip() for value in ids if value is not None and str(value).strip()}),
            "window_seconds": window,
            "auto_scale": bool(config.get("auto_scale", True)),
        })
    return {"version": 1, "panel_count": count, "panels": panels}


class SensorCorrelationDialog(QDialog):
    """Compare two captured signals and annotate the current capture session."""

    def __init__(self, sensor_capture, vin_provider=None, parent=None):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.vin_provider = vin_provider or (lambda: None)
        self.setWindowTitle("Synchronized Sensor Comparison")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.sensor_a = QComboBox()
        self.sensor_b = QComboBox()
        self.max_gap = QComboBox()
        for label, seconds in (("250 ms", 0.25), ("500 ms", 0.5), ("1 second", 1.0),
                               ("2 seconds", 2.0), ("5 seconds", 5.0)):
            self.max_gap.addItem(label, seconds)
        controls.addWidget(QLabel("Signal A:"))
        controls.addWidget(self.sensor_a, 1)
        controls.addWidget(QLabel("Signal B:"))
        controls.addWidget(self.sensor_b, 1)
        controls.addWidget(QLabel("Max gap:"))
        controls.addWidget(self.max_gap)
        layout.addLayout(controls)
        self.summary = QLabel("Select two signals with overlapping samples.")
        layout.addWidget(self.summary)
        if HAS_CHARTS:
            self.chart = QChart()
            self.chart.legend().setVisible(True)
            self.chart.setAnimationOptions(QChart.NoAnimation)
            self.chart.setBackgroundBrush(QColor("#111827"))
            self.chart.setPlotAreaBackgroundBrush(QColor("#0B1220"))
            self.chart.setPlotAreaBackgroundVisible(True)
            self.chart.setTitleBrush(QColor("#E5E7EB"))
            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("Elapsed time (s)")
            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("Normalized value (0-100%)")
            for axis in (self.axis_x, self.axis_y):
                axis.setLabelsColor(QColor("#D1D5DB"))
                axis.setLinePenColor(QColor("#64748B"))
                axis.setGridLineColor(QColor("#334155"))
            self.chart.addAxis(self.axis_x, Qt.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignLeft)
            layout.addWidget(self.chart_view, 1)
        else:
            self.chart_view = None
            layout.addWidget(QLabel("Qt Charts unavailable. Correlation values remain available."))
        layout.addWidget(QLabel("Session event markers"))
        self.events = QListWidget()
        self.events.setMaximumHeight(115)
        layout.addWidget(self.events)
        actions = QHBoxLayout()
        add_button = QPushButton("Add event marker")
        add_button.clicked.connect(self.add_event)
        actions.addWidget(add_button)
        export_button = QPushButton("Export session notes")
        export_button.clicked.connect(self.export_session)
        actions.addWidget(export_button)
        actions.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.sensor_a.currentIndexChanged.connect(self.update_comparison)
        self.sensor_b.currentIndexChanged.connect(self.update_comparison)
        self.max_gap.currentIndexChanged.connect(self.update_comparison)
        self.refresh_choices()

    def _samples(self):
        vin = self.vin_provider()
        return [sample for sample in self.sensor_capture.samples
                if not vin or (sample.metadata or {}).get("vin", "UNASSIGNED") == vin]

    def refresh_choices(self):
        names = {}
        for sample in self._samples():
            names.setdefault(sample.sensor_id, sample.name)
        self.sensor_a.clear()
        self.sensor_b.clear()
        for sensor_id, name in sorted(names.items(), key=lambda item: item[1].casefold()):
            label = f"{name} ({sensor_id})"
            self.sensor_a.addItem(label, sensor_id)
            self.sensor_b.addItem(label, sensor_id)
        if self.sensor_b.count() > 1:
            self.sensor_b.setCurrentIndex(1)
        self.refresh_events()
        self.update_comparison()

    def update_comparison(self, *_):
        if not self.sensor_a.count() or not self.sensor_b.count():
            self.summary.setText("No captured sensor signals are available for this vehicle.")
            return
        a, b = self.sensor_a.currentData(), self.sensor_b.currentData()
        if a == b:
            self.summary.setText("Choose two different signals.")
            if self.chart_view:
                self.chart.removeAllSeries()
            return
        samples = self._samples()
        gap = float(self.max_gap.currentData())
        result = correlate_sensor_series(samples, a, b, max_gap_seconds=gap)
        if result.coefficient is None:
            self.summary.setText(
                f"{result.sample_count} aligned samples. Correlation unavailable: "
                "need at least 3 overlapping samples and non-constant signals."
            )
        else:
            self.summary.setText(
                f"Pearson r = {result.coefficient:+.4f} | {result.sample_count} aligned samples | "
                f"{result.clock.replace('_', ' ')} | max interpolation gap {gap:g}s"
            )
        if not self.chart_view:
            return
        self.chart.removeAllSeries()
        grouped = {}
        for sample in samples:
            if sample.sensor_id not in {a, b} or sample.quality != "valid":
                continue
            try:
                stamp = float(getattr(sample, result.clock))
                value = float(sample.value)
            except (TypeError, ValueError, AttributeError):
                continue
            if math.isfinite(stamp) and math.isfinite(value):
                grouped.setdefault(sample.sensor_id, []).append((stamp, value))
        if not grouped:
            self.axis_x.setRange(0, 1)
            return
        start = min(min(stamp for stamp, _ in points) for points in grouped.values())
        end = max(max(stamp for stamp, _ in points) for points in grouped.values())
        for series_index, (sensor_id, points) in enumerate(sorted(grouped.items())):
            points.sort()
            low = min(value for _, value in points)
            high = max(value for _, value in points)
            span = high - low
            series = QLineSeries()
            first = next(sample for sample in samples if sample.sensor_id == sensor_id)
            series.setName(f"{first.name} [{first.unit or 'unitless'}] ({low:.4g} to {high:.4g})")
            series.setPen(QPen(QColor(GRAPH_PALETTE[series_index % len(GRAPH_PALETTE)]), 2.8))
            for stamp, value in points[-5000:]:
                normalized = 50.0 if span == 0 else (value - low) * 100.0 / span
                series.append(stamp - start, normalized)
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)
        self.axis_x.setRange(0, max(0.1, end - start))
        self.axis_y.setRange(0, 100)

    def refresh_events(self):
        self.events.clear()
        for event in self.sensor_capture.events:
            try:
                when = datetime.fromtimestamp(float(event["timestamp"])).astimezone().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (KeyError, TypeError, ValueError, OSError):
                when = str(event.get("timestamp", ""))
            note = event.get("note", "")
            self.events.addItem(f"{when} | {event.get('label', 'Event')}" +
                                (f" | {note}" if note else ""))

    def add_event(self):
        label, accepted = QInputDialog.getText(self, "Capture event", "Event label:")
        if not accepted or not label.strip():
            return
        note, note_accepted = QInputDialog.getMultiLineText(
            self, "Session annotation", "Optional note:", ""
        )
        if not note_accepted:
            note = ""
        try:
            self.sensor_capture.add_event(make_event_marker(self._samples(), label, note))
        except ValueError as exc:
            QMessageBox.warning(self, "Event marker", str(exc))
            return
        self.refresh_events()

    def export_session(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export session annotations", "freerov3r-session.json", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            self.sensor_capture.export_session_json(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))


class SensorGraphPanel(QWidget):
    """One independently configured sensor graph."""

    def __init__(self, sensor_capture, index, dock):
        super().__init__(dock)
        self.sensor_capture = sensor_capture
        self.index = index
        self.dock = dock
        self.vehicle_vin = None
        self._last_sample_generation = None
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
        controls.addStretch(1)
        outer.addLayout(controls)

        self.sensor_list = QListWidget()
        self.sensor_list.setMaximumHeight(74)
        self.sensor_list.setToolTip(
            "Sensor selection is managed centrally in Choose Sensors (PID)."
        )
        self.sensor_list.itemChanged.connect(self.update_chart)
        self.sensor_list.itemChanged.connect(self.dock.persist_layout)
        self.sensor_list.hide()

        if HAS_CHARTS:
            self.chart = QChart()
            self.chart.setTheme(QChart.ChartThemeDark)
            self.chart.legend().setVisible(True)
            self.chart.legend().setLabelColor(QColor("#E5E7EB"))
            self.chart.legend().setBrush(QColor("#111827"))
            self.chart.setAnimationOptions(QChart.NoAnimation)
            self.chart.setBackgroundBrush(QColor("#111827"))
            self.chart.setPlotAreaBackgroundBrush(QColor("#0B1220"))
            self.chart.setPlotAreaBackgroundVisible(True)
            self.chart.setTitleBrush(QColor("#E5E7EB"))
            self.chart.setBackgroundRoundness(0)
            self.chart.setMargins(QMargins(12, 8, 12, 8))
            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.chart_view.setBackgroundBrush(QColor("#0B1220"))
            self.chart_view.setStyleSheet("QChartView { background: #0B1220; border: 0; }")
            self.chart_view.viewport().setStyleSheet("background: #0B1220;")
            self.chart_view.setRubberBand(QChartView.RectangleRubberBand)
            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("Elapsed time (seconds)")
            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("Signal value")
            for axis in (self.axis_x, self.axis_y):
                axis.setLabelsColor(QColor("#D1D5DB"))
                axis.setLinePenColor(QColor("#64748B"))
                axis.setGridLineColor(QColor("#334155"))
            self.chart.addAxis(self.axis_x, Qt.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignLeft)
            outer.addWidget(self.chart_view, 1)
        else:
            outer.addWidget(QLabel("Qt Charts is unavailable. Install the PySide6 Charts component."))

    def set_vehicle_vin(self, vin):
        generation = getattr(
            self.sensor_capture, "total_samples_added", len(self.sensor_capture.samples)
        )
        if vin == self.vehicle_vin and generation == self._last_sample_generation:
            return
        self.vehicle_vin = vin
        self._last_sample_generation = generation
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
        if not selected_ids:
            self.chart.setTitle("Select one or more signals above")
            self.axis_x.setRange(0, 1)
            self.axis_y.setRange(0, 1)
            return
        grouped = {}
        for sample in self.sensor_capture.samples:
            if sample.sensor_id not in selected_ids:
                continue
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            if sample.quality != "valid":
                continue
            try:
                value = float(sample.value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            grouped.setdefault(sample.sensor_id, []).append(sample)

        all_samples = [sample for values in grouped.values() for sample in values]
        if not all_samples:
            self.chart.setTitle("Select one or more signals above")
            self.axis_x.setRange(0, 1)
            self.axis_y.setRange(0, 1)
            return

        clock = sample_clock(all_samples)
        latest = max(sample_time(sample, clock) for sample in all_samples)
        window = int(self.window_combo.currentData())
        start = min(sample_time(sample, clock) for sample in all_samples)
        if window:
            start = max(start, latest - window)
        multi_signal = len(grouped) > 1
        self.chart.setTitle(
            "Multiple signals · each trace scaled independently to 0–100%"
            if multi_signal else "Single signal · native units"
        )
        self.axis_y.setTitleText(
            "Relative range (%) · independent per signal"
            if multi_signal else f"Value ({next(iter(grouped.values()))[0].unit or 'unitless'})"
        )
        plotted_values = []

        for index, (sensor_id, samples) in enumerate(sorted(grouped.items())):
            samples = sorted(samples, key=lambda sample: sample_time(sample, clock))
            samples = [
                sample for sample in samples
                if sample_time(sample, clock) >= start
            ][-2000:]
            if not samples:
                continue
            values = [float(sample.value) for sample in samples]
            low, high = min(values), max(values)
            span = high - low
            first = samples[-1]
            series = QLineSeries()
            series.setName(
                f"{first.name} [{first.unit or 'unitless'}] · {low:.4g} to {high:.4g}"
            )
            series.setPen(QPen(QColor(GRAPH_PALETTE[index % len(GRAPH_PALETTE)]), 3.4))
            for sample, value in zip(samples, values):
                if multi_signal:
                    plotted = 50.0 if span == 0 else (value - low) * 100.0 / span
                else:
                    plotted = value
                    plotted_values.append(value)
                series.append(sample_time(sample, clock) - start, plotted)
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)

        duration = max(0.1, latest - start)
        self.axis_x.setRange(0, duration)
        if multi_signal:
            self.axis_y.setRange(0, 100)
        elif plotted_values and self.auto_scale.isChecked():
            low, high = min(plotted_values), max(plotted_values)
            padding = max((high - low) * 0.12, abs(high) * 0.01, 0.1)
            self.axis_y.setRange(low - padding, high + padding)

class SensorDashboardDock(QWidget):
    """Embedded multi-graph workspace with a focused sensor picker."""

    def __init__(
        self, sensor_capture, parent=None, initial_sensor_ids=None, vin_provider=None,
        settings=None, save_settings_callback=None,
    ):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.vin_provider = vin_provider or (lambda: None)
        self.initial_sensor_ids = set(initial_sensor_ids or ())
        self.settings = settings if isinstance(settings, dict) else {}
        self.save_settings_callback = save_settings_callback
        self._loading_config = False
        self._waterfall_dialog = None
        self._correlation_dialog = None
        self.selection_changed_callback = None
        self.favorites_changed_callback = None
        self.setObjectName("sensorDashboardWorkspace")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(5)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Graphs:"))
        self.panel_count = QComboBox()
        for count in PANEL_COUNTS:
            self.panel_count.addItem(str(count), count)
        self.panel_count.setCurrentIndex(2)
        self.panel_count.currentIndexChanged.connect(self.reflow)
        self.panel_count.currentIndexChanged.connect(self.persist_layout)
        controls.addWidget(self.panel_count)
        self.choose_sensors_button = QPushButton("Choose Sensors (PID)")
        self.choose_sensors_button.clicked.connect(self.choose_sensors)
        controls.addWidget(self.choose_sensors_button)
        self.waterfall_button = QPushButton("2D / 3D Waterfall")
        self.waterfall_button.clicked.connect(self.open_waterfall)
        controls.addWidget(self.waterfall_button)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.grid_host = QWidget(self)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        outer.addWidget(self.grid_host, 1)

        self.panels = [
            SensorGraphPanel(sensor_capture, index, self)
            for index in range(max(PANEL_COUNTS))
        ]
        self._visible_count = 4
        self._restore_saved_layout()
        self.refresh()
        if self.initial_sensor_ids and not self.panels[0].selected_sensor_ids():
            self.panels[0].refresh_sensor_choices(self.initial_sensor_ids)
        self.reflow()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

    def open_correlation(self):
        if self._correlation_dialog is None:
            self._correlation_dialog = SensorCorrelationDialog(
                self.sensor_capture, vin_provider=self.vin_provider, parent=self
            )
        self._correlation_dialog.refresh_choices()
        self._correlation_dialog.show()
        self._correlation_dialog.raise_()
        self._correlation_dialog.activateWindow()

    def open_waterfall(self):
        if self._waterfall_dialog is None:
            self._waterfall_dialog = SensorWaterfallDialog(
                self.sensor_capture, vin_provider=self.vin_provider, parent=self
            )
        self._waterfall_dialog.showMaximized()
        self._waterfall_dialog.raise_()
        self._waterfall_dialog.activateWindow()

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

    def choose_sensors(self):
        """Choose captured signals or defined OBD-II PIDs for each graph panel."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose Sensors (PID)")
        dialog.resize(620, 680)
        layout = QVBoxLayout(dialog)
        top = QHBoxLayout()
        top.addWidget(QLabel("Assign to:"))
        target = QComboBox()
        for index in range(4):
            target.addItem(f"Graph {index + 1}", index)
        top.addWidget(target, 1)
        top.addWidget(QLabel("Favorites:"))
        favorites = QComboBox()
        favorites.addItem("Choose favorite…", None)
        groups = self.settings.get("obd_pid_favorites", {})
        if isinstance(groups, dict):
            for name in sorted(groups, key=str.casefold):
                favorites.addItem(name, name)
        top.addWidget(favorites, 1)
        load = QPushButton("Load")
        top.addWidget(load)
        layout.addLayout(top)
        hint = QLabel("Captured sensors and standard PID definitions. PID support depends on the vehicle and ECU.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        sensor_list = QListWidget()
        layout.addWidget(sensor_list, 1)

        vin = self.vin_provider()
        available = {}
        for sample in self.sensor_capture.samples:
            if vin and (sample.metadata or {}).get("vin", "UNASSIGNED") != vin:
                continue
            available.setdefault(sample.sensor_id, (sample.name, sample.unit or ""))
        for pid, name, unit in OBD_PIDS:
            available.setdefault(f"obd_{int(pid, 16):02X}", (name, unit))

        def fill_list(selected=None):
            selected = set(selected or ())
            sensor_list.clear()
            for sensor_id, (name, unit) in sorted(available.items(), key=lambda item: item[1][0].casefold()):
                label = f"{name} ({sensor_id})" + (f" · {unit}" if unit else "")
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, sensor_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if sensor_id in selected else Qt.Unchecked)
                if sensor_id.startswith("obd_") and not any(s.sensor_id == sensor_id for s in self.sensor_capture.samples):
                    item.setToolTip("PID definition available; vehicle support has not yet been confirmed.")
                sensor_list.addItem(item)

        def current_ids():
            return {sensor_list.item(i).data(Qt.UserRole) for i in range(sensor_list.count())
                    if sensor_list.item(i).checkState() == Qt.Checked}

        def target_changed(*_):
            fill_list(self.panels[int(target.currentData())].selected_sensor_ids())

        def load_group():
            name = favorites.currentData()
            stored = groups.get(name, []) if name and isinstance(groups, dict) else []
            ids = set()
            if isinstance(stored, (list, tuple, set)):
                for value in stored:
                    value = str(value).strip().lower()
                    if value.startswith("obd_"):
                        ids.add(value)
                    else:
                        try:
                            ids.add(f"obd_{int(value, 16):02X}")
                        except ValueError:
                            ids.add(value)
            fill_list(ids)

        def save_group():
            ids = sorted(current_ids())
            if not ids:
                QMessageBox.information(dialog, "No sensors selected", "Select at least one sensor to save a favorite.")
                return
            name, accepted = QInputDialog.getText(dialog, "Save sensor favorite", "Favorite name:")
            if not accepted or not name.strip():
                return
            updated = dict(self.settings.get("obd_pid_favorites", {}))
            updated[name.strip()] = ids
            self.settings["obd_pid_favorites"] = updated
            if callable(self.save_settings_callback):
                self.save_settings_callback(self.settings)
            if callable(self.favorites_changed_callback):
                self.favorites_changed_callback(name.strip())
            favorites.clear()
            favorites.addItem("Choose favorite…", None)
            for favorite_name in sorted(updated, key=str.casefold):
                favorites.addItem(favorite_name, favorite_name)
            favorites.setCurrentIndex(favorites.findData(name.strip()))

        load.clicked.connect(load_group)
        target.currentIndexChanged.connect(target_changed)
        fill_list(self.panels[0].selected_sensor_ids())
        actions = QHBoxLayout()
        save = QPushButton("Save Favorite")
        save.clicked.connect(save_group)
        actions.addWidget(save)
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        apply_button = QPushButton("Apply to Graph")
        apply_button.clicked.connect(dialog.accept)
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        if dialog.exec() == QDialog.Accepted:
            index = int(target.currentData())
            selected = current_ids()
            self.panels[index].refresh_sensor_choices(selected)
            needed = max(int(self.panel_count.currentData()), index + 1)
            self.panel_count.setCurrentIndex(1 if needed == 1 else 2 if needed == 2 else 4)
            self.reflow()
            self.persist_layout()
            if callable(self.selection_changed_callback):
                self.selection_changed_callback(self.panels[0].selected_sensor_ids())

    def set_selected_sensor_ids(self, sensor_ids):
        """Keep OBD-II selection synchronization anchored to graph one."""
        self.panels[0].refresh_sensor_choices(set(sensor_ids or ()))
        self.persist_layout()

    def refresh(self):
        if not self.isVisible():
            return
        vin = self.vin_provider()
        for panel in self.panels:
            panel.set_vehicle_vin(vin)

    def reflow(self, *_):
        count = int(self.panel_count.currentData())
        self._visible_count = count
        for panel in self.panels:
            self.grid.removeWidget(panel)
            panel.hide()
            panel.setParent(self.grid_host)
        rows, columns = panel_grid_dimensions(count)
        for index, panel in enumerate(self.panels[:count]):
            self.grid.addWidget(panel, index // columns, index % columns)
            panel.show()
        self.grid_host.updateGeometry()
