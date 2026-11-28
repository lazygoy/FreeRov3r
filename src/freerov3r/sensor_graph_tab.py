"""Sensor capture graphing and sensor-group workspace."""

import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .diagnostics.obd2 import OBD_PIDS
from .sensors.capture import SensorCapture
from .sensors.analysis import summarize_sensor_samples
from .sensors.scaling import normalize_values, sample_clock, sample_time
from .sensors.thresholds import evaluate_sensor_threshold, normalize_sensor_thresholds


class SensorGraphTab(QWidget):
    def __init__(self, sensor_capture: SensorCapture, parent=None, settings_save_callback=None):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.series_map = {}
        self.color_map = {}
        self.hidden_sensor_ids = set()
        self.vehicle_vin = None
        self.recording = False
        self.record_start = None
        self.record_start_index = None
        self.record_vehicle_vin = None
        self.last_sample_time = {}
        self.activity_phase = True
        self.synced_obd_sensor_ids = set()
        self.selection_changed_callback = None
        self.favorites_changed_callback = None
        self.navigate_to_obd_callback = None
        self.open_dashboard_callback = None
        self.parent_settings = {}
        self.settings_save_callback = settings_save_callback

        layout = QVBoxLayout(self)
        if not HAS_CHARTS:
            msg = QLabel(
                "<b>Graphing unavailable</b><br><br>"
                "PySide6.QtCharts is not installed.<br>"
                "Run: <code>python -m pip install --upgrade PySide6</code> then restart.<br><br>"
                "CSV load/export still works."
            )
            msg.setWordWrap(True)
            msg.setAlignment(Qt.AlignCenter)
            layout.addWidget(msg)

        controls = QHBoxLayout()
        self.sensor_list = QListWidget()
        self.sensor_list.setMaximumHeight(150)
        self.sensor_list.setToolTip("Check multiple sensors to plot them together. Uncheck a sensor to hide it.")
        self.sensor_list.itemChanged.connect(self._on_sensor_item_changed)
        controls.addWidget(self.sensor_list, 2)

        right = QVBoxLayout()
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setToolTip(\
            "Marks a recording window in the retained sensor stream. Samples continue to be buffered; "
            "stopping exports only the samples collected since Start Recording."
        )
        self.record_btn.clicked.connect(self.toggle_record)
        right.addWidget(self.record_btn)

        if HAS_CHARTS:
            color_btn = QPushButton("Set Color for Selected")
            color_btn.clicked.connect(self.set_color)
            right.addWidget(color_btn)

            self.independent_scale = QCheckBox("Scale each sensor independently")
            self.independent_scale.setChecked(True)
            self.independent_scale.setToolTip(
                "Maps each sensor's own min/max to 0–100% so signals with different units "
                "and magnitudes remain visible together. The legend retains each raw range."
            )
            self.independent_scale.toggled.connect(self.update_chart)
            right.addWidget(self.independent_scale)

            self.auto_scale = QCheckBox("Auto shared Y-scale")
            self.auto_scale.setChecked(True)
            self.auto_scale.toggled.connect(self.update_chart)
            right.addWidget(self.auto_scale)

            point_row = QHBoxLayout()
            point_row.addWidget(QLabel("Points per signal:"))
            self.plot_point_limit = QSpinBox()
            self.plot_point_limit.setRange(100, 10000)
            self.plot_point_limit.setSingleStep(100)
            self.plot_point_limit.setValue(2000)
            self.plot_point_limit.setToolTip(
                "Maximum recent samples drawn for each signal. The underlying capture is retained separately."
            )
            self.plot_point_limit.valueChanged.connect(self.update_chart)
            point_row.addWidget(self.plot_point_limit)
            right.addLayout(point_row)

            scale_row = QHBoxLayout()
            scale_row.addWidget(QLabel("Y min:"))
            self.ymin = QLineEdit("-10")
            scale_row.addWidget(self.ymin)
            scale_row.addWidget(QLabel("Y max:"))
            self.ymax = QLineEdit("100")
            scale_row.addWidget(self.ymax)
            apply_btn = QPushButton("Apply")
            apply_btn.clicked.connect(self.update_chart)
            scale_row.addWidget(apply_btn)
            right.addLayout(scale_row)

        load_btn = QPushButton("Import CSV / JSONL")
        load_btn.clicked.connect(self.load_csv)
        right.addWidget(load_btn)
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_sensor_list)
        right.addWidget(refresh_btn)
        dashboard_btn = QPushButton("Open Multi-Graph Dashboard")
        dashboard_btn.setToolTip("Open up to eight independently configured live graphs. The dock remains available across workspaces.")
        dashboard_btn.clicked.connect(lambda: self.open_dashboard_callback() if self.open_dashboard_callback else None)
        right.addWidget(dashboard_btn)
        controls.addLayout(right, 1)
        layout.addLayout(controls)

        stats_group = QGroupBox("LIVE SENSOR HEALTH")
        stats_layout = QVBoxLayout(stats_group)
        self.stats_table = QTableWidget(0, 10)
        self.stats_table.setHorizontalHeaderLabels([
            "Sensor", "Current", "Min", "Average", "Max", "Rate", "Age", "Samples", "Status", "Alert"
        ])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 10):
            self.stats_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setMaximumHeight(170)
        self.stats_table.setToolTip(
            "Valid finite samples only. Signals become stale after five seconds. "
            "Alerts use only thresholds you explicitly configure; no OEM limits are assumed."
        )
        stats_layout.addWidget(self.stats_table)
        threshold_row = QHBoxLayout()
        self.threshold_button = QPushButton("Configure Alert for Selected Sensor")
        self.threshold_button.clicked.connect(self.configure_sensor_threshold)
        threshold_row.addWidget(self.threshold_button)
        threshold_note = QLabel("User-defined only. Alerts are OFF until enabled.")
        threshold_note.setWordWrap(True)
        threshold_row.addWidget(threshold_note, 1)
        stats_layout.addLayout(threshold_row)
        layout.addWidget(stats_group)
        self._last_stats_refresh = 0.0

        favorite_row = QHBoxLayout()
        favorite_row.addWidget(QLabel("Shared sensor group:"))
        self.favorite_combo = QComboBox()
        favorite_row.addWidget(self.favorite_combo, 1)
        self.load_group_btn = QPushButton("Load")
        self.load_group_btn.clicked.connect(self.load_favorite_group)
        favorite_row.addWidget(self.load_group_btn)
        save_group_btn = QPushButton("Save graph selection as…")
        save_group_btn.clicked.connect(self.save_favorite_group)
        favorite_row.addWidget(save_group_btn)
        self.delete_group_btn = QPushButton("Delete")
        self.delete_group_btn.clicked.connect(self.delete_favorite_group)
        favorite_row.addWidget(self.delete_group_btn)
        self.open_obd_btn = QPushButton("Open OBD-II")
        self.open_obd_btn.clicked.connect(lambda: self.navigate_to_obd_callback() if self.navigate_to_obd_callback else None)
        favorite_row.addWidget(self.open_obd_btn)
        self.favorite_combo.currentIndexChanged.connect(self._favorite_selection_changed)
        layout.addLayout(favorite_row)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(1000)
        self.activity_timer.timeout.connect(self._update_activity_indicators)
        self.activity_timer.start()
        self.refresh_favorite_groups()

        if HAS_CHARTS:
            info = QLabel(
                "Independent scaling is a trend-comparison view, not a shared physical scale. "
                "Raw units and min/max remain visible in each legend entry."
            )
            info.setWordWrap(True)
            layout.addWidget(info)
            self.chart = QChart()
            self.chart.setTitle("Multi-sensor / PID Graph")
            self.chart.legend().setVisible(True)
            self.chart.setAnimationOptions(QChart.NoAnimation)
            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.chart_view.setRubberBand(QChartView.RectangleRubberBand)
            layout.addWidget(self.chart_view)
            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("Time (s from start)")
            self.axis_y = QValueAxis()
            self.chart.addAxis(self.axis_x, Qt.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignLeft)
        else:
            self.placeholder = QPlainTextEdit()
            self.placeholder.setReadOnly(True)
            layout.addWidget(self.placeholder)

        self.refresh_sensor_list()

    def refresh_sensor_list(self):
        self.sensor_list.blockSignals(True)
        self.sensor_list.clear()
        seen = set()
        for sample in self.sensor_capture.samples:
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            if sample.sensor_id not in seen:
                seen.add(sample.sensor_id)
                item = QListWidgetItem(f"● {sample.name} ({sample.sensor_id})")
                item.setData(Qt.UserRole, sample.sensor_id)
                item.setData(Qt.UserRole + 1, sample.name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked if sample.sensor_id in self.hidden_sensor_ids else Qt.Checked)
                self.sensor_list.addItem(item)
        self.sensor_list.blockSignals(False)
        self.update_statistics(force=True)
        if HAS_CHARTS:
            self.update_chart()
        elif hasattr(self, "placeholder"):
            self.placeholder.setPlainText(
                f"{len(self.sensor_capture.samples)} samples loaded.\n{len(seen)} unique sensors."
            )

    def set_vehicle_vin(self, vin):
        self.vehicle_vin = vin
        self.refresh_sensor_list()

    def _sensor_id(self, item):
        return item.data(Qt.UserRole) or item.text().split("(")[-1].rstrip(")")

    def selected_sensor_ids(self):
        return {self._sensor_id(self.sensor_list.item(i)) for i in range(self.sensor_list.count())
                if self.sensor_list.item(i).checkState() == Qt.Checked}

    def set_selected_sensor_ids(self, sensor_ids):
        selected = {str(value).lower() for value in sensor_ids}
        self.synced_obd_sensor_ids = {value for value in selected if value.startswith("obd_")}
        known = {self._sensor_id(self.sensor_list.item(i)) for i in range(self.sensor_list.count())}
        known.update(f"obd_{int(pid, 16):02X}" for pid, _name, _unit in OBD_PIDS)
        self.hidden_sensor_ids.update(known - selected)
        self.hidden_sensor_ids.difference_update(selected)
        self.sensor_list.blockSignals(True)
        for i in range(self.sensor_list.count()):
            item = self.sensor_list.item(i)
            item.setCheckState(Qt.Checked if self._sensor_id(item) in selected else Qt.Unchecked)
        self.sensor_list.blockSignals(False)
        self.update_chart()

    def update_statistics(self, force=False):
        """Refresh read-only sensor health summaries from the retained capture."""
        if not hasattr(self, "stats_table"):
            return
        now = time.monotonic()
        if not force and now - self._last_stats_refresh < 1.5:
            return
        self._last_stats_refresh = now
        samples = []
        for sample in self.sensor_capture.samples:
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            samples.append(sample)
        summaries = summarize_sensor_samples(samples, stale_after=5.0)
        self.stats_table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            values = (
                summary.name, f"{summary.current:.4g} {summary.unit}".strip(),
                f"{summary.minimum:.4g}", f"{summary.average:.4g}", f"{summary.maximum:.4g}",
                f"{summary.rate_hz:.2f} Hz" if summary.rate_hz is not None else "—",
                f"{summary.age_seconds:.1f} s", str(summary.sample_count),
                "STALE" if summary.stale else "LIVE",
                "N/A" if summary.stale else evaluate_sensor_threshold(
                    summary.current,
                    (self.parent_settings.get("sensor_thresholds", {}) or {}).get(summary.sensor_id, {}),
                ),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, summary.sensor_id)
                elif column == 8:
                    item.setForeground(QColor("#d9a441") if summary.stale else QColor("#39d98a"))
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 9:
                    item.setTextAlignment(Qt.AlignCenter)
                    if value in ("LOW", "HIGH"):
                        item.setForeground(QColor("#e05a5a"))
                    elif value == "OK":
                        item.setForeground(QColor("#39d98a"))
                    else:
                        item.setForeground(QColor("#77818c"))
                elif column in (1, 2, 3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.stats_table.setItem(row, column, item)

    def configure_sensor_threshold(self):
        row = self.stats_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a sensor", "Select a sensor row in the health table first.")
            return
        sensor_item = self.stats_table.item(row, 0)
        if sensor_item is None:
            return
        sensor_id = sensor_item.data(Qt.UserRole)
        if not sensor_id:
            return
        stored = self.parent_settings.get("sensor_thresholds", {})
        config = normalize_sensor_thresholds(stored.get(sensor_id, {}) if isinstance(stored, dict) else {})
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Alert Threshold | {sensor_item.text()}")
        form = QFormLayout(dialog)
        enabled = QCheckBox("Enable user-defined alert")
        enabled.setChecked(config["enabled"])
        minimum_enabled = QCheckBox("Minimum")
        maximum_enabled = QCheckBox("Maximum")
        minimum = QDoubleSpinBox()
        maximum = QDoubleSpinBox()
        for control in (minimum, maximum):
            control.setRange(-1000000000.0, 1000000000.0)
            control.setDecimals(4)
            control.setKeyboardTracking(False)
        minimum_enabled.setChecked(config["minimum"] is not None)
        maximum_enabled.setChecked(config["maximum"] is not None)
        minimum.setValue(config["minimum"] if config["minimum"] is not None else 0.0)
        maximum.setValue(config["maximum"] if config["maximum"] is not None else 0.0)
        minimum.setEnabled(minimum_enabled.isChecked())
        maximum.setEnabled(maximum_enabled.isChecked())
        minimum_enabled.toggled.connect(minimum.setEnabled)
        maximum_enabled.toggled.connect(maximum.setEnabled)
        form.addRow(enabled)
        min_row = QHBoxLayout()
        min_row.addWidget(minimum_enabled)
        min_row.addWidget(minimum)
        form.addRow("Low alert:", min_row)
        max_row = QHBoxLayout()
        max_row.addWidget(maximum_enabled)
        max_row.addWidget(maximum)
        form.addRow("High alert:", max_row)
        note = QLabel("These are your own alert limits, not Land Rover specifications.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        low = minimum.value() if minimum_enabled.isChecked() else None
        high = maximum.value() if maximum_enabled.isChecked() else None
        if low is not None and high is not None and low >= high:
            QMessageBox.warning(self, "Invalid alert limits", "The minimum must be lower than the maximum.")
            return
        thresholds = self.parent_settings.setdefault("sensor_thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}
            self.parent_settings["sensor_thresholds"] = thresholds
        thresholds[str(sensor_id)] = {"enabled": enabled.isChecked(), "minimum": low, "maximum": high}
        if self.settings_save_callback:
            self.settings_save_callback(self.parent_settings)
        self.update_statistics(force=True)

    def mark_sample(self, sensor_id):
        """Record sample arrival; the activity timer owns widget refreshes."""
        self.last_sample_time[str(sensor_id)] = time.monotonic()

    def _update_activity_indicators(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        self.activity_phase = not self.activity_phase
        for i in range(self.sensor_list.count()):
            item = self.sensor_list.item(i)
            sensor_id = self._sensor_id(item)
            active = now - self.last_sample_time.get(sensor_id, 0) <= 5.0
            item.setText(f"{'●' if active else '○'} {item.data(Qt.UserRole + 1)} ({sensor_id})")
            item.setForeground(QColor("#39d98a") if active and self.activity_phase else
                               QColor("#27885b") if active else QColor("#77818c"))
            item.setToolTip("Live data arriving" if active else "No recent samples")

    def refresh_favorite_groups(self, selected_name=None):
        groups = self.parent_settings.get("obd_pid_favorites", {})
        self.favorite_combo.blockSignals(True)
        self.favorite_combo.clear()
        self.favorite_combo.addItem("Choose saved group…", None)
        if isinstance(groups, dict):
            for name in sorted(groups, key=str.casefold):
                self.favorite_combo.addItem(name, name)
        if selected_name:
            index = self.favorite_combo.findData(selected_name)
            if index >= 0:
                self.favorite_combo.setCurrentIndex(index)
        self.favorite_combo.blockSignals(False)
        enabled = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(enabled)
        self.delete_group_btn.setEnabled(enabled)

    def _favorite_selection_changed(self, *_):
        enabled = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(enabled)
        self.delete_group_btn.setEnabled(enabled)

    def _group_sensor_ids(self, values):
        result = set()
        for value in values if isinstance(values, (list, tuple, set)) else []:
            text = str(value).strip().lower()
            if text.startswith("obd_"):
                result.add(text)
            else:
                try:
                    result.add(f"obd_{int(text, 16):02X}")
                except ValueError:
                    result.add(text)
        return result

    def load_favorite_group(self):
        name = self.favorite_combo.currentData()
        groups = self.parent_settings.get("obd_pid_favorites", {})
        if name and isinstance(groups, dict):
            selected = self._group_sensor_ids(groups.get(name, []))
            self.set_selected_sensor_ids(selected)
            if self.selection_changed_callback:
                self.selection_changed_callback(selected)

    def save_favorite_group(self):
        selected = self.selected_sensor_ids()
        visible_ids = {self._sensor_id(self.sensor_list.item(i)) for i in range(self.sensor_list.count())}
        selected.update(self.synced_obd_sensor_ids - visible_ids)
        if not selected:
            QMessageBox.information(self, "No sensors selected", "Select at least one sensor before saving a group.")
            return
        name, accepted = QInputDialog.getText(self, "Save sensor group", "Group name:")
        name = name.strip()
        if not accepted or not name:
            return
        groups = dict(self.parent_settings.get("obd_pid_favorites", {}))
        groups[name] = sorted(selected)
        self.parent_settings["obd_pid_favorites"] = groups
        save_settings(self.parent_settings)
        self.refresh_favorite_groups(name)
        if self.favorites_changed_callback:
            self.favorites_changed_callback(name)

    def delete_favorite_group(self):
        name = self.favorite_combo.currentData()
        if name:
            groups = dict(self.parent_settings.get("obd_pid_favorites", {}))
            groups.pop(name, None)
            self.parent_settings["obd_pid_favorites"] = groups
            save_settings(self.parent_settings)
            self.refresh_favorite_groups()
            if self.favorites_changed_callback:
                self.favorites_changed_callback()

    def _on_sensor_item_changed(self, item):
        sensor_id = self._sensor_id(item)
        if item.checkState() == Qt.Checked:
            self.hidden_sensor_ids.discard(sensor_id)
        else:
            self.hidden_sensor_ids.add(sensor_id)
        self.update_chart()
        if self.selection_changed_callback:
            visible_ids = {self._sensor_id(self.sensor_list.item(i)) for i in range(self.sensor_list.count())}
            selected_ids = self.selected_sensor_ids()
            selected_ids.update(self.synced_obd_sensor_ids - visible_ids)
            self.synced_obd_sensor_ids = {value for value in selected_ids if value.startswith("obd_")}
            self.selection_changed_callback(selected_ids)

    def toggle_record(self):
        if not self.recording:
            self.recording = True
            self.record_start = time.time()
            self.record_start_index = self.sensor_capture.total_samples_added
            self.record_vehicle_vin = self.vehicle_vin
            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet("background-color: #c0392b; color: white;")
            return

        self.recording = False
        start_index = self.record_start_index
        record_vin = self.record_vehicle_vin
        self.record_start = None
        self.record_start_index = None
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("")
        recorded = self.sensor_capture.samples_since(start_index or 0)
        if record_vin:
            recorded = [
                sample for sample in recorded
                if (sample.metadata or {}).get("vin", "UNASSIGNED") == record_vin
            ]
        if not recorded:
            QMessageBox.information(
                self, "Sensor recording", "No retained sensor samples were collected in that window."
            )
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save sensor recording", "sensor_recording.csv",
            "CSV (*.csv);;JSON Lines (*.jsonl)"
        )
        if not path:
            return
        try:
            if selected_filter.startswith("JSON Lines") or path.lower().endswith(".jsonl"):
                self.sensor_capture.export_jsonl(path, samples=recorded, vin=record_vin)
            else:
                self.sensor_capture.export_csv(path, vin=record_vin, samples=recorded)
        except OSError as exc:
            QMessageBox.warning(self, "Sensor recording", f"Could not save recording: {exc}")
            return

        dropped_during_recording = max(
            0, self.sensor_capture.dropped_samples - (start_index or 0)
        )
        if dropped_during_recording:
            QMessageBox.warning(
                self, "Incomplete sensor recording",
                f"Saved {len(recorded)} retained samples, but {dropped_during_recording} "
                "samples were dropped from the rolling capture buffer while recording. "
                "Those samples cannot be recovered from this export."
            )

    def set_color(self):
        if not HAS_CHARTS:
            return
        items = self.sensor_list.selectedItems()
        if not items:
            return
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        for item in items:
            sensor_id = self._sensor_id(item)
            self.color_map[sensor_id] = color
        self.update_chart()

    def update_chart(self):
        if not HAS_CHARTS:
            return
        self.chart.removeAllSeries()
        self.series_map.clear()
        selected_ids = {
            self._sensor_id(self.sensor_list.item(i))
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        }

        grouped = {}
        for sample in self.sensor_capture.samples:
            sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
            if self.vehicle_vin and sample_vin != self.vehicle_vin:
                continue
            if sample.sensor_id not in selected_ids or sample.quality != "valid" or not math.isfinite(sample.value):
                continue
            grouped.setdefault(sample.sensor_id, []).append(sample)

        if not grouped:
            self.axis_x.setRange(0, 1)
            self.axis_y.setTitleText("Value")
            return

        all_samples = [sample for values in grouped.values() for sample in values]
        clock = sample_clock(all_samples)
        time_value = lambda sample: sample_time(sample, clock)
        base_time = min(time_value(sample) for sample in all_samples)
        min_t = min(time_value(sample) - base_time for sample in all_samples)
        max_t = max(time_value(sample) - base_time for sample in all_samples)
        self.axis_x.setTitleText(
            "Elapsed time (s, monotonic)" if clock == "monotonic_timestamp"
            else "Elapsed time (s, wall clock)"
        )

        independent = self.independent_scale.isChecked()
        self.axis_y.setTitleText("Relative scale per sensor (%)" if independent else "Value (shared scale)")
        raw_min = min(sample.value for sample in all_samples)
        raw_max = max(sample.value for sample in all_samples)

        for sensor_id, samples in grouped.items():
            samples.sort(key=time_value)
            samples = samples[-self.plot_point_limit.value():]
            raw_values = [sample.value for sample in samples]
            if independent:
                plotted_values, low, high = normalize_values(raw_values)
                unit = samples[0].unit or "unitless"
                legend_name = (
                    f"{samples[0].name} ({sensor_id}) [{low:.4g}–{high:.4g} {unit}]"
                )
            else:
                plotted_values = raw_values
                legend_name = f"{samples[0].name} ({sensor_id}) [{samples[0].unit}]"

            series = QLineSeries()
            series.setName(legend_name)
            color = self.color_map.get(
                sensor_id, QColor.fromHsv(abs(hash(sensor_id)) % 360, 180, 220)
            )
            series.setColor(color)
            for sample, plotted in zip(samples, plotted_values):
                series.append(time_value(sample) - base_time, plotted)
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)
            self.series_map[sensor_id] = series

        self.axis_x.setRange(min_t, max_t + (0.5 if max_t == min_t else 0.01))
        if independent:
            self.axis_y.setRange(0, 100)
        elif self.auto_scale.isChecked():
            pad = max((raw_max - raw_min) * 0.15, 1.0)
            self.axis_y.setRange(raw_min - pad, raw_max + pad)
        else:
            try:
                low, high = float(self.ymin.text()), float(self.ymax.text())
                if low < high:
                    self.axis_y.setRange(low, high)
            except ValueError:
                pass

    def load_csv(self):
        path, selected_filter = QFileDialog.getOpenFileName(
            self, "Import sensor samples", "",
            "Sensor data (*.csv *.jsonl);;CSV (*.csv);;JSON Lines (*.jsonl)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".jsonl") or selected_filter.startswith("JSON Lines"):
                count = self.sensor_capture.import_jsonl(path, default_vin=self.vehicle_vin)
            else:
                count = self.sensor_capture.import_csv(path, default_vin=self.vehicle_vin)
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", f"Could not read sensor data: {exc}")
            return
        self.refresh_sensor_list()
        QMessageBox.information(
            self, "Sensor import",
            f"Imported {count} valid samples. Malformed or non-finite rows were skipped."
        )
