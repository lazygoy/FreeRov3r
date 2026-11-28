"""Dockable multi-panel live sensor dashboard."""

import math
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QMargins
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDockWidget, QGridLayout, QHBoxLayout,
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


PANEL_COUNTS = (1, 2, 4, 6, 8)
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


class _FloatingGraphWindow(QDialog):
    def __init__(self, dock, panel):
        super().__init__(None, Qt.Window)
        self.dock = dock
        self.panel = panel
        self._restoring = False
        self.setWindowTitle(f"FreeRov3r | {panel.windowTitle()}")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(900, 560)
        self.resize(1100, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
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

    def toggle_popout(self):
        if self._floating_host is None:
            self.dock.popout_panel(self)
        else:
            self.dock.restore_panel(self, self._floating_host)

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
        self._waterfall_dialog = None
        self._correlation_dialog = None
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
        self.waterfall_button = QPushButton("Sensor Scope (2D / 3D)")
        self.waterfall_button.clicked.connect(self.open_waterfall)
        controls.addWidget(self.waterfall_button)
        self.compare_button = QPushButton("Compare / Events")
        self.compare_button.clicked.connect(self.open_correlation)
        controls.addWidget(self.compare_button)
        controls.addWidget(QLabel("Quick preset:"))
        self.preset_combo = QComboBox()
        for preset_name in PRESET_GROUPS:
            self.preset_combo.addItem(preset_name, preset_name)
        controls.addWidget(self.preset_combo)
        self.apply_preset_button = QPushButton("Apply")
        self.apply_preset_button.clicked.connect(self.apply_sensor_preset)
        controls.addWidget(self.apply_preset_button)
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

    def apply_sensor_preset(self):
        name = self.preset_combo.currentData()
        vin = self.vin_provider()
        available = {
            sample.sensor_id for sample in self.sensor_capture.samples
            if not vin or (sample.metadata or {}).get("vin", "UNASSIGNED") == vin
        }
        layout = build_sensor_preset(name, available)
        if layout is None:
            QMessageBox.information(
                self, "No matching captured signals",
                f"The {name} preset has no matching signals in the current capture. "
                "It does not send PID requests or assume vehicle support."
            )
            return
        self._apply_layout(layout)

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
        if checked and not self.isFloating():
            self.setFloating(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def refresh(self):
        vin = self.vin_provider()
        for panel in self.panels:
            panel.set_vehicle_vin(vin)

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
        # Reparenting a hidden widget hides it in Qt; explicitly show the
        # graph panel inside its new top-level window.
        panel.show()
        host.showNormal()
        host.raise_()
        host.activateWindow()

    def restore_panel(self, panel, host):
        if panel._floating_host is not host:
            return
        host._restoring = True
        if host.layout() is not None:
            host.layout().removeWidget(panel)
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
