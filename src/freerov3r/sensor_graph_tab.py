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
from .sensors.scaling import normalize_values, sample_clock, sample_time


class SensorGraphTab(QWidget):
    def __init__(self, sensor_capture: SensorCapture, parent=None, settings_save_callback=None):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.known_sensor_ids = set()
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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setToolTip(
            "Start or stop a recording window and export the retained samples from that window."
        )
        self.record_btn.clicked.connect(self.toggle_record)
        toolbar.addWidget(self.record_btn)

        import_btn = QPushButton("Import CSV / JSONL")
        import_btn.clicked.connect(self.load_csv)
        toolbar.addWidget(import_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # Kept as a hidden compatibility model for OBD-II selection sync.
        # The visible sensor selection lives in the dashboard's picker.
        self.sensor_list = QListWidget(self)
        self.sensor_list.hide()
        self.dashboard_layout = QVBoxLayout()
        self.dashboard_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.dashboard_layout, 1)
        self.dashboard_widget = None
        self._last_stats_refresh = 0.0
        self.refresh_sensor_list()

    def set_dashboard_widget(self, widget):
        """Place the live multigraph workspace directly inside this tab."""
        if self.dashboard_widget is not None:
            self.dashboard_layout.removeWidget(self.dashboard_widget)
            self.dashboard_widget.setParent(None)
        self.dashboard_widget = widget
        widget.setParent(self)
        self.dashboard_layout.addWidget(widget, 1)
        if hasattr(widget, "set_selected_sensor_ids"):
            widget.set_selected_sensor_ids(self.selected_sensor_ids())

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
        self.known_sensor_ids = seen
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
        visible = {self._sensor_id(self.sensor_list.item(i)) for i in range(self.sensor_list.count())
                   if self.sensor_list.item(i).checkState() == Qt.Checked}
        return visible | set(self.synced_obd_sensor_ids)

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
        if self.dashboard_widget is not None and hasattr(self.dashboard_widget, "set_selected_sensor_ids"):
            self.dashboard_widget.set_selected_sensor_ids(selected)

    def update_statistics(self, force=False):
        """Sensor health is intentionally not part of the graph workspace."""
        return

    def refresh_favorite_groups(self, selected_name=None):
        """Favorites are managed in the Choose Sensors (PID) dialog."""
        return

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
        if not HAS_CHARTS or not hasattr(self, "chart"):
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
