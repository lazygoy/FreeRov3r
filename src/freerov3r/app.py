"""FreeRov3r – user-friendly diagnostic interface with graphing, OBD-II, and modules."""
import csv
import json
import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtGui import QPalette, QColor, QFont, QFontDatabase, QPainter, QBrush
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow,
    QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QGroupBox,
    QFormLayout, QCheckBox, QSpinBox, QStackedWidget, QColorDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QGridLayout, QToolButton, QButtonGroup,
    QDialog, QFrame,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .hardware.serial_ports import list_serial_ports
from .hardware.python_can_adapter import PythonCanAdapter
from .hardware.esp32_serial_adapter import Esp32SerialAdapter
from .hardware.simulated_vehicle import SimulatedVehicleAdapter, decode_mode01
from .session import CaptureSession
from .can_monitor import CanMonitor
from .sensors.capture import SensorCapture
from .sensors.models import SensorSample
from .sensors.scaling import normalize_values
from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .vehicle_history import VehicleHistoryStore
from .diagnostics.vin_decoder import VinFrameDecoder
from .ui_feedback import QuickDrawer, ToastManager

SETTINGS_DIR = Path.home() / ".freerov3r"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "interface": "virtual",
    "channel": "freerov3r",
    "bitrate": 500000,
    "max_log_lines": 5000,
    "dark_mode": True,
    "vehicles": {},
    "current_vin": None,
    "auto_refresh_graph": True,
    "graph_refresh_ms": 1000,
    "show_startup_splash": True,
}

# Common OBD-II PIDs (Mode 01)
OBD_PIDS = [
    ("0C", "Engine RPM", "rpm"),
    ("0D", "Vehicle Speed", "km/h"),
    ("05", "Engine Coolant Temp", "°C"),
    ("0F", "Intake Air Temp", "°C"),
    ("11", "Throttle Position", "%"),
    ("04", "Calculated Engine Load", "%"),
    ("0B", "Intake Manifold Pressure", "kPa"),
    ("10", "MAF Air Flow Rate", "g/s"),
    ("1F", "Run Time Since Engine Start", "s"),
    ("21", "Distance Traveled with MIL On", "km"),
    ("2F", "Fuel Tank Level", "%"),
    ("42", "Control Module Voltage", "V"),
    ("46", "Ambient Air Temp", "°C"),
    ("5C", "Engine Oil Temp", "°C"),
]

# Placeholder L319 modules (do not treat addresses as verified)
L319_MODULES = [
    ("ECM", "Engine Control Module", "TBD"),
    ("TCM", "Transmission Control Module", "TBD"),
    ("ABS", "Anti-lock Braking System", "TBD"),
    ("BCM", "Body Control Module", "TBD"),
    ("IPC", "Instrument Pack", "TBD"),
    ("HVAC", "Climate Control", "TBD"),
    ("RCM", "Restraints Control Module", "TBD"),
    ("PAM", "Parking Aid Module", "TBD"),
]


def load_settings() -> dict:
    SETTINGS_DIR.mkdir(exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    SETTINGS_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


class Receiver(QThread):
    frame_received = Signal(object)
    status = Signal(str)

    def __init__(self, adapter):
        super().__init__()
        self.adapter = adapter
        self.running = True

    def run(self):
        try:
            self.adapter.open()
            self.status.emit(f"Connected: {self.adapter.description}")
            while self.running:
                frame = self.adapter.receive(0.15)
                if frame is not None:
                    self.frame_received.emit(frame)
        except Exception as exc:
            self.status.emit(f"Adapter error: {exc}")
        finally:
            try:
                self.adapter.close()
            except Exception:
                pass

    def stop(self):
        self.running = False
        self.wait(2000)


class SensorGraphTab(QWidget):
    def __init__(self, sensor_capture: SensorCapture, parent=None):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.series_map = {}
        self.color_map = {}
        self.hidden_sensor_ids = set()
        self.vehicle_vin = None
        self.recording = False
        self.record_start = None

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

        load_btn = QPushButton("Load CSV")
        load_btn.clicked.connect(self.load_csv)
        right.addWidget(load_btn)
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_sensor_list)
        right.addWidget(refresh_btn)
        controls.addLayout(right, 1)
        layout.addLayout(controls)

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
                item = QListWidgetItem(f"{sample.name} ({sample.sensor_id})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked if sample.sensor_id in self.hidden_sensor_ids else Qt.Checked)
                self.sensor_list.addItem(item)
        self.sensor_list.blockSignals(False)
        if HAS_CHARTS:
            self.update_chart()
        elif hasattr(self, "placeholder"):
            self.placeholder.setPlainText(
                f"{len(self.sensor_capture.samples)} samples loaded.\n{len(seen)} unique sensors."
            )

    def set_vehicle_vin(self, vin):
        self.vehicle_vin = vin
        self.refresh_sensor_list()

    def _on_sensor_item_changed(self, item):
        sensor_id = item.text().split("(")[-1].rstrip(")")
        if item.checkState() == Qt.Checked:
            self.hidden_sensor_ids.discard(sensor_id)
        else:
            self.hidden_sensor_ids.add(sensor_id)
        self.update_chart()

    def toggle_record(self):
        self.recording = not self.recording
        if self.recording:
            self.record_start = time.time()
            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet("background-color: #c0392b; color: white;")
        else:
            self.record_btn.setText("Start Recording")
            self.record_btn.setStyleSheet("")
            path, _ = QFileDialog.getSaveFileName(
                self, "Save sensor recording", "sensor_recording.csv", "CSV (*.csv)"
            )
            if path:
                self.sensor_capture.export_csv(path, vin=self.vehicle_vin)

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
            sensor_id = item.text().split("(")[-1].rstrip(")")
            self.color_map[sensor_id] = color
        self.update_chart()

    def update_chart(self):
        if not HAS_CHARTS:
            return
        self.chart.removeAllSeries()
        self.series_map.clear()
        selected_ids = {
            self.sensor_list.item(i).text().split("(")[-1].rstrip(")")
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
        base_time = min(sample.timestamp for sample in all_samples)
        min_t = min(sample.timestamp - base_time for sample in all_samples)
        max_t = max(sample.timestamp - base_time for sample in all_samples)

        independent = self.independent_scale.isChecked()
        self.axis_y.setTitleText("Relative scale per sensor (%)" if independent else "Value (shared scale)")
        raw_min = min(sample.value for sample in all_samples)
        raw_max = max(sample.value for sample in all_samples)

        for sensor_id, samples in grouped.items():
            samples.sort(key=lambda sample: sample.timestamp)
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
                series.append(sample.timestamp - base_time, plotted)
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
        path, _ = QFileDialog.getOpenFileName(self, "Load sensor CSV", "", "CSV (*.csv)")
        if not path:
            return
        count = 0
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    sample = SensorSample(
                        timestamp=float(row.get("timestamp", time.time())),
                        sensor_id=row.get("sensor_id", "unknown"),
                        name=row.get("name", row.get("sensor_id", "unknown")),
                        value=float(row["value"]),
                        unit=row.get("unit", ""),
                        source=row.get("source", "imported"),
                        metadata={"vin": self.vehicle_vin or "UNASSIGNED"},
                    )
                    self.sensor_capture.add(sample)
                    count += 1
                except (KeyError, ValueError):
                    continue
        self.refresh_sensor_list()
        QMessageBox.information(self, "Loaded", f"Imported {count} samples.")


class OBDTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        note = QLabel(
            "<b>OBD-II</b><br>"
            "Transmit/request support is disabled by default for safety. "
            "The simulator streams clearly labeled synthetic Mode 01 values; real vehicles "
            "only populate this table when matching response frames are observed."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(len(OBD_PIDS), 4)
        self.pid_rows = {pid: row for row, (pid, _, _) in enumerate(OBD_PIDS)}
        self.table.setHorizontalHeaderLabels(["PID", "Description", "Unit", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for row, (pid, desc, unit) in enumerate(OBD_PIDS):
            self.table.setItem(row, 0, QTableWidgetItem(pid))
            self.table.setItem(row, 1, QTableWidgetItem(desc))
            self.table.setItem(row, 2, QTableWidgetItem(unit))
            self.table.setItem(row, 3, QTableWidgetItem("—"))
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.request_btn = QPushButton("Request Selected PIDs (disabled)")
        self.request_btn.setEnabled(False)
        self.request_btn.setToolTip("Transmit is disabled by SafetyPolicy")
        btn_row.addWidget(self.request_btn)
        clear_btn = QPushButton("Clear Values")
        clear_btn.clicked.connect(self.clear_values)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def update_value(self, pid, value):
        row = self.pid_rows.get(f"{pid:02X}")
        if row is not None:
            self.table.item(row, 3).setText(f"{value:.2f}".rstrip("0").rstrip("."))

    def clear_values(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 3).setText("—")


class ModulesTab(QWidget):
    def __init__(self, network: SimulatedModuleNetwork, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.network = network
        self.simulation_enabled = False
        self.current_module_code = None
        layout = QVBoxLayout(self)
        note = QLabel("<b>Module diagnostics simulator</b><br>Synthetic L319-style module categories and example DTCs. This is a test fixture, not a scan of a real vehicle. Real ECU addressing and UDS services are not enabled.")
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        self.scan_one_btn = QPushButton("Scan Selected Module")
        self.scan_one_btn.clicked.connect(self.scan_selected)
        actions.addWidget(self.scan_one_btn)
        self.scan_all_btn = QPushButton("Scan All Modules")
        self.scan_all_btn.clicked.connect(self.scan_all)
        actions.addWidget(self.scan_all_btn)
        self.clear_module_btn = QPushButton("Clear Selected Module")
        self.clear_module_btn.clicked.connect(self.clear_module)
        actions.addWidget(self.clear_module_btn)
        self.clear_all_btn = QPushButton("Clear All Simulated DTCs")
        self.clear_all_btn.clicked.connect(self.clear_all)
        actions.addWidget(self.clear_all_btn)
        layout.addLayout(actions)

        split = QHBoxLayout()
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Category / module", "DTCs", "Last scan"])
        self.module_tree.setMinimumWidth(390)
        self.module_tree.itemSelectionChanged.connect(self.show_selected_module)
        split.addWidget(self.module_tree, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Diagnostic trouble codes"))
        self.dtc_table = QTableWidget(0, 4)
        self.dtc_table.setHorizontalHeaderLabels(["Code", "Description", "Status", "Severity"])
        self.dtc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.dtc_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dtc_table.setSelectionMode(QTableWidget.SingleSelection)
        right.addWidget(self.dtc_table, 2)
        self.clear_code_btn = QPushButton("Clear Selected DTC")
        self.clear_code_btn.clicked.connect(self.clear_selected_code)
        right.addWidget(self.clear_code_btn)
        self.result_log = QPlainTextEdit()
        self.result_log.setReadOnly(True)
        self.result_log.setMaximumBlockCount(1000)
        right.addWidget(self.result_log, 1)
        split.addLayout(right, 2)
        layout.addLayout(split)
        self.set_simulation_enabled(False)
        self.refresh_tree()

    def set_network(self, network: SimulatedModuleNetwork):
        self.network = network
        self.current_module_code = None
        self.refresh_tree()
        self.dtc_table.setRowCount(0)

    def set_simulation_enabled(self, enabled: bool):
        self.simulation_enabled = bool(enabled)
        for control in (self.scan_one_btn, self.scan_all_btn, self.clear_module_btn, self.clear_all_btn, self.clear_code_btn):
            control.setEnabled(self.simulation_enabled)
        if enabled:
            self.result_log.appendPlainText("SIMULATOR ACTIVE: operations affect synthetic in-memory data only.")
        else:
            self.result_log.appendPlainText("Simulator inactive. Select the simulated vehicle interface to enable module operations.")

    def refresh_tree(self):
        selected = self.current_module_code
        self.module_tree.clear()
        groups = {}
        for module in self.network.modules:
            parent = groups.get(module.category)
            if parent is None:
                parent = QTreeWidgetItem([module.category, "", ""])
                self.module_tree.addTopLevelItem(parent)
                groups[module.category] = parent
            item = QTreeWidgetItem([f"{module.code} — {module.name}", str(len(module.dtcs)), module.last_scan or "Not scanned"])
            item.setData(0, Qt.UserRole, module.code)
            parent.addChild(item)
            if module.code == selected:
                self.module_tree.setCurrentItem(item)
        self.module_tree.expandAll()
        refresh_overview = getattr(self, "network_overview_refresh", None)
        if refresh_overview:
            refresh_overview()

    def _selected_code(self):
        item = self.module_tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def show_selected_module(self):
        code = self._selected_code()
        if not code:
            self.dtc_table.setRowCount(0)
            return
        self.current_module_code = code
        module = self.network.get_module(code)
        self.dtc_table.setRowCount(len(module.dtcs))
        for row, dtc in enumerate(module.dtcs):
            for col, value in enumerate((dtc.code, dtc.description, dtc.status, dtc.severity)):
                self.dtc_table.setItem(row, col, QTableWidgetItem(value))

    def _require_vehicle(self):
        vin = self.vin_provider()
        if not vin:
            QMessageBox.warning(self, "Vehicle not selected", "Add and select a vehicle by VIN in the Sensors tab before running or clearing diagnostics.")
            return None
        return vin

    def scan_selected(self):
        code = self._selected_code()
        if not self.simulation_enabled or not code:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        module = self.network.scan_module(code)
        self.result_log.appendPlainText(f"SCAN {code}: response received, {len(module.dtcs)} DTC(s).")
        self.history_callback("module_scan", f"{code} scan completed", {
            "module": code, "module_name": module.name, "category": module.category,
            "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs],
        }, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def scan_all(self):
        if not self.simulation_enabled:
            return
        vin = self.vin_provider()
        if not vin:
            QMessageBox.warning(self, "Vehicle not selected", "Add and select a vehicle by VIN in the Sensors tab before recording diagnostic history.")
            return
        modules = self.network.scan_all()
        total = sum(len(module.dtcs) for module in modules)
        self.result_log.appendPlainText(f"FULL SCAN: {len(modules)} simulated modules responded; {total} DTC(s) found.")
        self.history_callback("full_module_scan", "Full module scan completed", {
            "modules_scanned": len(modules), "dtc_count": total,
            "modules": [{"code": m.code, "name": m.name, "category": m.category,
                        "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in m.dtcs]}
                       for m in modules],
        }, vin=vin)
        self.refresh_tree()

    def clear_selected_code(self):
        code = self._selected_code()
        row = self.dtc_table.currentRow()
        if not self.simulation_enabled or not code or row < 0 or not self.dtc_table.item(row, 0):
            return
        vin = self._require_vehicle()
        if not vin:
            return
        dtc = self.dtc_table.item(row, 0).text()
        if self.network.clear_code(code, dtc):
            self.result_log.appendPlainText(f"CLEAR {code} {dtc}: removed from simulated module memory.")
            self.history_callback("dtc_cleared", f"Cleared {dtc} from {code}", {"module": code, "dtc": dtc}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def clear_module(self):
        code = self._selected_code()
        if not self.simulation_enabled or not code:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        before = [d.code for d in self.network.get_module(code).dtcs]
        count = self.network.clear_module(code)
        self.result_log.appendPlainText(f"CLEAR MODULE {code}: {count} simulated DTC(s) cleared.")
        self.history_callback("module_dtcs_cleared", f"Cleared all DTCs from {code}", {"module": code, "dtcs_cleared": before}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def clear_all(self):
        if not self.simulation_enabled:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        answer = QMessageBox.question(self, "Clear all simulated DTCs", "Remove every DTC from every simulated module?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        before = {m.code: [d.code for d in m.dtcs] for m in self.network.modules if m.dtcs}
        count = self.network.clear_all()
        self.result_log.appendPlainText(f"CLEAR ALL: {count} simulated DTC(s) removed.")
        self.history_callback("all_dtcs_cleared", "Cleared all simulated DTCs", {"dtcs_by_module": before, "total_cleared": count}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()



class NetworkOverviewTab(QWidget):
    """Thinkcar-style module status overview; colors reflect scan evidence only."""
    def __init__(self, network, vin_provider=None, parent=None):
        super().__init__(parent)
        self.network = network
        self.vin_provider = vin_provider or (lambda: None)
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["System / module", "Health", "DTCs", "Last scan"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh module status")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        row.addStretch()
        layout.addLayout(row)
        self.refresh()

    def set_network(self, network):
        self.network = network
        self.refresh()

    def refresh(self):
        vin = self.vin_provider() or "No VIN detected"
        self.heading.setText(
            f"<b>Vehicle network overview</b><br>VIN: {vin}<br>"
            "Green = scanned, no DTCs. Red = one or more DTCs. Gray = not scanned or no response. "
            "Current module inventory is simulated until live L319 addressing is verified."
        )
        self.tree.clear()
        groups = {}
        for module in self.network.modules:
            group = groups.get(module.category)
            if group is None:
                group = QTreeWidgetItem([module.category, "", "", ""])
                self.tree.addTopLevelItem(group)
                groups[module.category] = group
            if not module.available:
                status, color = "No response", QColor("#888888")
            elif module.last_scan is None:
                status, color = "Not scanned", QColor("#888888")
            elif module.dtcs:
                status, color = "Attention", QColor("#ef5350")
            else:
                status, color = "No faults", QColor("#43a047")
            item = QTreeWidgetItem([
                f"{module.code} — {module.name}", status,
                str(len(module.dtcs)), module.last_scan or "—"
            ])
            item.setData(0, Qt.UserRole, module.code)
            for col in (0, 1):
                item.setForeground(col, QBrush(color))
            group.addChild(item)
        for group in groups.values():
            children = [self.network.get_module(group.child(i).data(0, Qt.UserRole))
                        for i in range(group.childCount())]
            if any(m.available and m.last_scan is not None and m.dtcs for m in children):
                group.setForeground(0, QBrush(QColor("#ef5350")))
            elif children and all(m.available and m.last_scan is not None and not m.dtcs for m in children):
                group.setForeground(0, QBrush(QColor("#43a047")))
            else:
                group.setForeground(0, QBrush(QColor("#888888")))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(2)
        self.tree.resizeColumnToContents(3)


class VehicleHistoryTab(QWidget):
    def __init__(self, store: VehicleHistoryStore, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Vehicle VIN:"))
        self.vin_filter = QComboBox()
        self.vin_filter.currentIndexChanged.connect(self.refresh_events)
        controls.addWidget(self.vin_filter, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(refresh_btn)
        layout.addLayout(controls)

        split = QHBoxLayout()
        self.events_tree = QTreeWidget()
        self.events_tree.setHeaderLabels(["Date / time", "Event", "Summary"])
        self.events_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.events_tree.itemSelectionChanged.connect(self.show_details)
        split.addWidget(self.events_tree, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a history entry to inspect its recorded details.")
        split.addWidget(self.details, 2)
        layout.addLayout(split)
        self.refresh()

    def refresh(self):
        current = self.vin_filter.currentData()
        self.vin_filter.blockSignals(True)
        self.vin_filter.clear()
        self.vin_filter.addItem("All vehicles", None)
        for vin in self.store.vehicles():
            self.vin_filter.addItem(vin, vin)
        index = self.vin_filter.findData(current)
        self.vin_filter.setCurrentIndex(index if index >= 0 else 0)
        self.vin_filter.blockSignals(False)
        self.refresh_events()

    def refresh_events(self):
        self.events_tree.clear()
        selected_vin = self.vin_filter.currentData()
        events = self.store.events if selected_vin is None else self.store.for_vin(selected_vin)
        for event in reversed(events):
            timestamp = event.get("timestamp", "")
            item = QTreeWidgetItem([
                timestamp.replace("T", " "),
                event.get("type", ""),
                event.get("summary", ""),
            ])
            item.setData(0, Qt.UserRole, event)
            self.events_tree.addTopLevelItem(item)
        self.events_tree.resizeColumnToContents(0)
        self.events_tree.resizeColumnToContents(1)
        self.details.clear()

    def show_details(self):
        item = self.events_tree.currentItem()
        event = item.data(0, Qt.UserRole) if item else None
        self.details.setPlainText(json.dumps(event, indent=2, ensure_ascii=False) if event else "")



class SolutionsTab(QWidget):
    """VIN- and module-scoped ChatGPT prompt and saved-response workspace."""
    def __init__(self, network, vin_provider, history_provider, sensor_provider, storage_path, parent=None):
        super().__init__(parent)
        self.network, self.vin_provider = network, vin_provider
        self.history_provider, self.sensor_provider = history_provider, sensor_provider
        self.storage_path = Path(storage_path)
        self.solutions = self._load()
        self.current_module_code = None
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        split = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Problem module", "DTCs"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self.select_module)
        split.addWidget(self.tree, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Scan evidence"))
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        right.addWidget(self.evidence, 2)
        row = QHBoxLayout()
        copy = QPushButton("Copy ChatGPT prompt")
        copy.clicked.connect(self.copy_prompt)
        row.addWidget(copy)
        export = QPushButton("Export prompt")
        export.clicked.connect(self.export_prompt)
        row.addWidget(export)
        right.addLayout(row)
        right.addWidget(QLabel("ChatGPT suggested troubleshooting / solution"))
        self.response = QPlainTextEdit()
        self.response.setPlaceholderText("Paste ChatGPT's response here.")
        right.addWidget(self.response, 3)
        row2 = QHBoxLayout()
        paste = QPushButton("Paste from clipboard")
        paste.clicked.connect(lambda: self.response.setPlainText(QApplication.clipboard().text()))
        row2.addWidget(paste)
        save = QPushButton("Save solution for this VIN / module")
        save.clicked.connect(self.save_solution)
        row2.addWidget(save)
        right.addLayout(row2)
        split.addLayout(right, 3)
        layout.addLayout(split)
        self.refresh()

    def _load(self):
        try:
            value = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.solutions, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.storage_path)

    def set_network(self, network):
        self.network = network
        self.refresh()

    def refresh(self):
        vin = self.vin_provider() or "No VIN selected"
        self.heading.setText(
            f"<b>ChatGPT troubleshooting workspace</b><br>Vehicle: {vin}<br>"
            "Select a module to build a focused prompt from DTCs, vehicle history and recent sensor data. "
            "Prompts and saved replies stay local. No API call is made."
        )
        previous = self.current_module_code
        self.tree.clear()
        groups = {}
        for module in self.network.modules:
            group = groups.get(module.category)
            if group is None:
                group = QTreeWidgetItem([module.category, ""])
                self.tree.addTopLevelItem(group)
                groups[module.category] = group
            item = QTreeWidgetItem([f"{module.code} — {module.name}", str(len(module.dtcs))])
            item.setData(0, Qt.UserRole, module.code)
            group.addChild(item)
            if module.code == previous:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            group = self.tree.topLevelItem(0)
            if group.childCount():
                self.tree.setCurrentItem(group.child(0))
        self.select_module()

    def select_module(self):
        item = self.tree.currentItem()
        code = item.data(0, Qt.UserRole) if item else None
        if not code:
            self.current_module_code = None
            self.evidence.clear()
            self.response.clear()
            return
        self.current_module_code = code
        module = self.network.get_module(code)
        vin = self.vin_provider() or "UNASSIGNED"
        dtcs = [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs]
        evidence = {
            "vin": vin,
            "module": {"code": code, "name": module.name, "category": module.category},
            "scan_state": "not_scanned" if module.last_scan is None else "scanned",
            "last_scan": module.last_scan, "available": module.available, "dtcs": dtcs,
            "data_quality": "Synthetic simulator fixture, not verified live L319 scan data."
        }
        self.evidence.setPlainText(json.dumps(evidence, indent=2, ensure_ascii=False))
        self.response.setPlainText(self.solutions.get(vin, {}).get(code, {}).get("response", ""))

    def build_prompt(self):
        code = self.current_module_code
        if not code:
            return ""
        module = self.network.get_module(code)
        vin = self.vin_provider() or "UNASSIGNED"
        events = self.history_provider(vin)[-30:]
        samples = self.sensor_provider(vin)[-50:]
        data = {
            "vin": vin, "vehicle": "2010-2016 Land Rover Discovery 4 / LR4 (L319)",
            "module": {"code": code, "name": module.name, "category": module.category},
            "scan_state": "not_scanned" if module.last_scan is None else "scanned",
            "last_scan": module.last_scan,
            "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs],
            "recent_history": [{"timestamp": e.get("timestamp"), "type": e.get("type"), "summary": e.get("summary"), "details": e.get("details", {})} for e in events],
            "sensor_samples": [{"timestamp": x.timestamp, "name": x.name, "value": x.value, "unit": x.unit, "source": x.source} for x in samples],
            "data_quality": "Module inventory and DTCs are synthetic fixtures, not actual verified L319 faults or definitions."
        }
        instructions = (
            "Troubleshoot this Land Rover Discovery 4 / LR4. Analyze only the evidence. "
            "Separate facts, hypotheses and tests. Do not assume generic DTC descriptions are verified. "
            "For each likely cause explain why it fits, provide safe checks and expected results, required tools, "
            "and what would rule it out. Prioritize non-invasive checks. Do not recommend parts replacement "
            "without confirming tests. Flag safety-critical systems. State clearly if evidence is synthetic or insufficient."
        )
        return instructions + "\n\nEVIDENCE JSON:\n" + json.dumps(data, indent=2, ensure_ascii=False)

    def copy_prompt(self):
        prompt = self.build_prompt()
        if prompt:
            QApplication.clipboard().setText(prompt)
            QMessageBox.information(self, "Copied", "Module-specific ChatGPT prompt copied to clipboard.")

    def export_prompt(self):
        prompt = self.build_prompt()
        if not prompt:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export troubleshooting prompt", "freerov3r_prompt.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(prompt, encoding="utf-8")

    def save_solution(self):
        code = self.current_module_code
        if not code:
            return
        vin = self.vin_provider() or "UNASSIGNED"
        self.solutions.setdefault(vin, {})[code] = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "response": self.response.toPlainText(),
            "dtcs_at_save": [d.code for d in self.network.get_module(code).dtcs]
        }
        self._save()
        QMessageBox.information(self, "Saved", f"Solution saved locally for {vin} / {code}.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        installed_fonts = {family.casefold(): family for family in QFontDatabase.families()}
        self.body_font_family = next(
            (installed_fonts[name.casefold()] for name in ("Inter", "Segoe UI Variable", "Segoe UI")
             if name.casefold() in installed_fonts),
            "Segoe UI",
        )
        self.heading_font_family = next(
            (installed_fonts[name.casefold()] for name in ("Inter Tight", "Inter", "Segoe UI Variable", "Segoe UI")
             if name.casefold() in installed_fonts),
            self.body_font_family,
        )
        self.session = CaptureSession()
        self.can_monitor = CanMonitor(capacity=20000)
        self.sensor_capture = SensorCapture()
        self.history_store = VehicleHistoryStore(SETTINGS_DIR / "vehicle_history.json")
        self.receiver = None
        self.capture_started_at = None
        self.capture_start_frames = 0
        self.capture_start_sample_index = 0
        self.capture_start_frame_index = 0
        self.capture_vin = None
        self.vin_decoder = VinFrameDecoder()
        self.active_interface = None
        self.frame_counter = 0
        self.last_rate_time = time.monotonic()
        self.last_rate_count = 0

        self.setWindowTitle("FreeRov3r")
        self.resize(1320, 860)

        self._build_ui()
        self._apply_settings()
        self._update_vehicle_context()

        self.rate_timer = QTimer(self)
        self.rate_timer.timeout.connect(self._update_rate)
        self.rate_timer.start(self.settings.get("graph_refresh_ms", 1000))

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.mode_label = QLabel()
        self.mode_label.setWordWrap(True)
        self.mode_label.setObjectName("modeBanner")
        self.mode_label.setFont(QFont(self.body_font_family, 11, QFont.DemiBold))

        # Welcome
        welcome = QWidget()
        wlayout = QVBoxLayout(welcome)
        wlayout.setAlignment(Qt.AlignCenter)
        wlayout.setSpacing(18)
        wlayout.setContentsMargins(48, 40, 48, 40)

        title = QLabel("What would you like to do?")
        title.setFont(QFont(self.heading_font_family, 25, QFont.ExtraBold))
        title.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(title)

        subtitle = QLabel("Choose a task to get started. You can switch later.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("welcomeSubtitle")
        wlayout.addWidget(subtitle)

        task_grid = QGridLayout()
        task_grid.setSpacing(12)
        tasks = [
            ("Pull diagnostic codes (DTCs)", self.show_dtc_mode),
            ("Read OBD-II data", self.show_obd_mode),
            ("Collect sensor data", self.show_sensor_mode),
            ("Graph sensor data", self.show_graph_mode),
            ("Read vehicle information", self.show_vehicle_info_mode),
            ("Vehicle modules (CAN)", self.show_modules_mode),
        ]
        for index, (text, slot) in enumerate(tasks):
            btn = QPushButton(text)
            btn.setMinimumHeight(66)
            btn.setObjectName("taskButton")
            btn.clicked.connect(slot)
            task_grid.addWidget(btn, index // 2, index % 2)
        wlayout.addLayout(task_grid)

        self.stack.addWidget(welcome)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        self._build_capture_tab()
        self._build_sensors_tab()
        self.graph_tab = SensorGraphTab(self.sensor_capture)
        self.tabs.addTab(self.graph_tab, "Graph")
        self.obd_tab = OBDTab()
        self.tabs.addTab(self.obd_tab, "OBD-II")
        self.module_networks = {}
        self.module_network = SimulatedModuleNetwork()
        self.modules_tab = ModulesTab(
            self.module_network,
            vin_provider=lambda: self.settings.get("current_vin"),
            history_callback=self.record_vehicle_event,
        )
        self.tabs.addTab(self.modules_tab, "Modules")
        self.network_tab = NetworkOverviewTab(
            self.module_network, vin_provider=lambda: self.settings.get("current_vin")
        )
        self.tabs.addTab(self.network_tab, "Network")
        self.modules_tab.network_overview_refresh = self.network_tab.refresh
        self.solutions_tab = SolutionsTab(
            self.module_network,
            vin_provider=lambda: self.settings.get("current_vin"),
            history_provider=lambda vin: self.history_store.for_vin(vin),
            sensor_provider=lambda vin: [
                sample for sample in self.sensor_capture.samples
                if (sample.metadata or {}).get("vin", "UNASSIGNED") == vin
            ],
            storage_path=SETTINGS_DIR / "solutions.json",
        )
        self.tabs.addTab(self.solutions_tab, "Solutions")
        self.history_tab = VehicleHistoryTab(self.history_store)
        self.tabs.addTab(self.history_tab, "Vehicle History")
        self._build_settings_tab()
        self._build_navigation_workspace()
        self.quick_drawer = QuickDrawer(self, self._navigate_to_tab)
        self.addDockWidget(Qt.RightDockWidgetArea, self.quick_drawer)
        self.quick_drawer.setMinimumWidth(260)
        self.quick_drawer.setMaximumWidth(340)
        self.quick_drawer.show()
        self.quick_drawer.set_current_workspace(self.tabs.tabText(self.tabs.currentIndex()))
        self.toast_manager = ToastManager(self)

    def _build_navigation_workspace(self):
        """Build a readable icon-tile rail instead of rotated QTabWidget labels."""
        self.tabs.tabBar().hide()
        workspace = QWidget()
        outer_layout = QVBoxLayout(workspace)
        outer_layout.setContentsMargins(12, 10, 12, 12)
        outer_layout.setSpacing(10)

        # Persistent instrument header: the key context stays visible on every page.
        header = QWidget()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(18)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.workspace_title = QLabel("Capture")
        self.workspace_title.setObjectName("workspaceTitle")
        self.workspace_title.setFont(QFont(self.heading_font_family, 20, QFont.ExtraBold))
        self.workspace_subtitle = QLabel("Passive vehicle diagnostics and CAN monitoring")
        self.workspace_subtitle.setObjectName("workspaceSubtitle")
        self.workspace_subtitle.setFont(QFont(self.body_font_family, 9, QFont.Medium))
        title_column.addWidget(self.workspace_title)
        title_column.addWidget(self.workspace_subtitle)
        header_layout.addLayout(title_column, 1)

        self.header_vehicle = QLabel("NO VEHICLE SELECTED")
        self.header_vehicle.setObjectName("headerVehicle")
        self.header_vehicle.setFont(QFont(self.body_font_family, 9, QFont.DemiBold))
        self.header_vehicle.setToolTip("Select or identify a vehicle in the Sensors workspace.")
        header_layout.addWidget(self.header_vehicle)

        self.header_connection = QLabel("● OFFLINE")
        self.header_connection.setObjectName("headerOffline")
        self.header_connection.setFont(QFont(self.body_font_family, 9, QFont.Bold))
        header_layout.addWidget(self.header_connection)

        self.header_traffic = QLabel("0 frames  |  0.0 fps")
        self.header_traffic.setObjectName("headerTraffic")
        self.header_traffic.setFont(QFont(self.body_font_family, 10, QFont.DemiBold))
        header_layout.addWidget(self.header_traffic)

        self.drawer_button = QToolButton()
        self.drawer_button.setObjectName("drawerToggle")
        self.drawer_button.setText("☷  Quick panel")
        self.drawer_button.setToolTip("Open vehicle context and workspace shortcuts")
        self.drawer_button.clicked.connect(self.toggle_quick_drawer)
        header_layout.addWidget(self.drawer_button)

        outer_layout.addWidget(header)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        content_row.addWidget(self.tabs, 1)
        outer_layout.addLayout(content_row, 1)
        self.stack.addWidget(workspace)
        self.stack.setCurrentIndex(1)
        self.tabs.currentChanged.connect(self._sync_navigation_selection)
        self._sync_navigation_selection(self.tabs.currentIndex())

    def _sync_navigation_selection(self, index):
        if hasattr(self, "workspace_title") and 0 <= index < self.tabs.count():
            title = self.tabs.tabText(index)
            self.workspace_title.setText(title.upper())
            descriptions = {
                "Capture": "Live CAN traffic, interface status and recording controls",
                "Sensors": "Vehicle identity and recorded sensor measurements",
                "Graph": "Compare sensor trends and operating ranges",
                "OBD-II": "Standard diagnostic parameters and trouble codes",
                "Modules": "Module-level diagnostic workspace",
                "Network": "Vehicle network overview and module status",
                "Solutions": "Review diagnostic evidence and analysis notes",
                "Vehicle History": "Previous captures and vehicle-specific events",
                "Settings": "Connection, display and logging configuration",
            }
            self.workspace_subtitle.setText(descriptions.get(title, "Vehicle diagnostics workspace"))
            if hasattr(self, "quick_drawer"):
                self.quick_drawer.set_current_workspace(title)
        self._refresh_workspace_header()

    def toggle_quick_drawer(self):
        if hasattr(self, "quick_drawer"):
            self.quick_drawer.setVisible(not self.quick_drawer.isVisible())

    def _navigate_to_tab(self, name):
        if name == "Home":
            self.stack.setCurrentIndex(0)
            if hasattr(self, "quick_drawer"):
                self.quick_drawer.set_current_workspace("Home")
            return
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                self.stack.setCurrentIndex(1)
                return

    def show_toast(self, message, kind="info"):
        if hasattr(self, "toast_manager"):
            self.toast_manager.show(message, kind)

    def _refresh_workspace_header(self):
        if not hasattr(self, "header_vehicle"):
            return
        vin = self.settings.get("current_vin")
        vehicles = self.settings.get("vehicles", {})
        nickname = vehicles.get(vin, {}).get("nickname", "") if vin else ""
        vehicle_text = f"{nickname}  |  {vin}" if nickname and vin else (vin or "NO VEHICLE SELECTED")
        self.header_vehicle.setText(vehicle_text)
        running = bool(self.receiver and self.receiver.isRunning())
        if running:
            if self.active_interface == "simulator":
                self.header_connection.setText("● SIMULATION")
                self.header_connection.setObjectName("headerSimulation")
            else:
                self.header_connection.setText("● LISTENING")
                self.header_connection.setObjectName("headerOnline")
        else:
            self.header_connection.setText("● OFFLINE")
            self.header_connection.setObjectName("headerOffline")
        self.header_connection.style().unpolish(self.header_connection)
        self.header_connection.style().polish(self.header_connection)
        rate = self.can_monitor.rate()
        self.header_traffic.setText(f"{self.frame_counter:,} frames  |  {rate:.1f} fps")
        if hasattr(self, "quick_drawer"):
            self.quick_drawer.update_context(
                vehicle_text, self.header_connection.text().replace("● ", ""),
                f"{self.frame_counter:,} frames · {rate:.1f} fps",
            )

    def record_vehicle_event(self, event_type, summary, details=None, vin=None):
        vehicle_vin = vin if vin is not None else self.settings.get("current_vin")
        self.history_store.record(vehicle_vin, event_type, summary, details)
        if hasattr(self, "history_tab"):
            self.history_tab.refresh()
        if hasattr(self, "solutions_tab"):
            self.solutions_tab.refresh()

    def show_startup_splash_if_enabled(self):
        if not self.settings.get("show_startup_splash", True):
            return
        dialog = QDialog(self)
        dialog.setObjectName("startupSplash")
        dialog.setWindowTitle("Welcome to FreeRov3r")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setMinimumSize(760, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)
        eyebrow = QLabel("FREEROV3R  /  VEHICLE DIAGNOSTICS")
        eyebrow.setObjectName("splashEyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("What would you like to do?")
        title.setObjectName("splashTitle")
        title.setFont(QFont(self.heading_font_family, 25, QFont.ExtraBold))
        layout.addWidget(title)
        subtitle = QLabel(
            "Start with a simple task. You can switch workspaces at any time "
            "using Quick Nav on the right."
        )
        subtitle.setObjectName("splashSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        grid = QGridLayout()
        grid.setSpacing(12)
        choices = [
            ("Connect to a vehicle", "Choose your adapter and passively monitor vehicle traffic.",
             "Open capture", lambda: self._navigate_to_tab("Capture")),
            ("Try the simulator", "Start a clearly labeled demo using synthetic vehicle data. No hardware required.",
             "Start demo", self._start_simulator_demo),
            ("Explore sample modules", "Browse example module categories and sample faults. These are test fixtures, not a real scan.",
             "View sample modules", lambda: self._navigate_to_tab("Modules")),
            ("Open the full workspace", "Go straight to the complete set of diagnostic, graphing and history tools.",
             "Open workspace", lambda: self._navigate_to_tab("Capture")),
        ]
        for index, (heading, description, action_text, action) in enumerate(choices):
            card = QFrame()
            card.setObjectName("splashCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(8)
            heading_label = QLabel(heading)
            heading_label.setObjectName("splashCardTitle")
            card_layout.addWidget(heading_label)
            detail = QLabel(description)
            detail.setObjectName("splashCardText")
            detail.setWordWrap(True)
            card_layout.addWidget(detail, 1)
            action_button = QPushButton(action_text)
            action_button.setObjectName("splashAction")
            action_button.setMinimumHeight(38)
            action_button.clicked.connect(
                lambda checked=False, callback=action: (dialog.accept(), callback())
            )
            card_layout.addWidget(action_button)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid, 1)
        footer = QHBoxLayout()
        self.splash_skip_checkbox = QCheckBox("Don't show this welcome screen at startup")
        self.splash_skip_checkbox.toggled.connect(self._set_startup_splash_preference)
        footer.addWidget(self.splash_skip_checkbox)
        footer.addStretch(1)
        close_button = QPushButton("Continue to workspace")
        close_button.setObjectName("splashContinue")
        close_button.clicked.connect(dialog.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        dialog.exec()

    def _set_startup_splash_preference(self, skip_splash):
        self.settings["show_startup_splash"] = not skip_splash
        save_settings(self.settings)

    def _start_simulator_demo(self):
        for index in range(self.backend.count()):
            data = self.backend.itemData(index)
            if data and data[0] == "simulator":
                self.backend.setCurrentIndex(index)
                self.channel_edit.setCurrentText(data[1])
                self._navigate_to_tab("Capture")
                self.toggle_capture()
                return

    def _build_capture_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.mode_label)

        self.status = QLabel("Not connected")
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        self.backend = QComboBox()
        self.backend.addItem("Virtual CAN (no hardware)", ("virtual", "freerov3r"))
        self.backend.addItem("Simulated vehicle (synthetic OBD-II)", ("simulator", "L319-DEMO"))
        self.backend.addItem("ESP32 serial adapter", ("esp32", "COM3"))
        self.backend.addItem("SocketCAN", ("socketcan", "can0"))
        self.backend.addItem("SLCAN", ("slcan", "COM3"))
        controls.addWidget(QLabel("Connection:"))
        controls.addWidget(self.backend)

        self.channel_edit = QComboBox()
        self.channel_edit.setEditable(True)
        self.channel_edit.setInsertPolicy(QComboBox.NoInsert)
        self.channel_edit.setPlaceholderText("COM port or CAN channel")
        self.channel_edit.setToolTip(
            "Choose a detected serial port for ESP32/SLCAN, or type a CAN channel such as can0."
        )
        controls.addWidget(self.channel_edit)

        refresh_ports_btn = QPushButton("Refresh ports")
        refresh_ports_btn.setToolTip("Detect serial devices currently connected to Windows.")
        refresh_ports_btn.clicked.connect(self.refresh_serial_ports)
        controls.addWidget(refresh_ports_btn)

        self.bitrate = QComboBox()
        self.bitrate.addItems(["125000", "250000", "500000", "1000000"])
        controls.addWidget(QLabel("Bitrate:"))
        controls.addWidget(self.bitrate)
        layout.addLayout(controls)

        self.connect_btn = QPushButton("Start listening")
        self.connect_btn.clicked.connect(self.toggle_capture)
        layout.addWidget(self.connect_btn)

        stats = QHBoxLayout()
        self.frame_count_label = QLabel("Frames: 0")
        self.rate_label = QLabel("Rate: 0 fps")
        stats.addWidget(self.frame_count_label)
        stats.addWidget(self.rate_label)
        stats.addStretch()
        layout.addLayout(stats)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("CAN ID filter (hex / range):"))
        self.can_id_filter = QLineEdit()
        self.can_id_filter.setPlaceholderText("e.g. 7E8 or 700-7FF; blank = all")
        self.can_id_filter.setToolTip("Hexadecimal arbitration ID or inclusive range. Filtering affects display only, not capture/export.")
        self.can_id_filter.textChanged.connect(self.refresh_can_display)
        filter_row.addWidget(self.can_id_filter)
        self.can_format_filter = QComboBox()
        self.can_format_filter.addItems(["All", "Standard", "Extended"])
        self.can_format_filter.currentTextChanged.connect(self.refresh_can_display)
        filter_row.addWidget(self.can_format_filter)
        layout.addLayout(filter_row)

        self.monitor_summary = QLabel("Recent traffic: no frames")
        layout.addWidget(self.monitor_summary)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(self.settings.get("max_log_lines", 5000))
        layout.addWidget(self.log)

        export_row = QHBoxLayout()
        export_btn = QPushButton("Export capture")
        export_btn.clicked.connect(self.export_capture)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_capture_display)
        back_btn = QPushButton("← Back to tasks")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        export_row.addWidget(export_btn)
        export_row.addWidget(clear_btn)
        export_row.addStretch()
        export_row.addWidget(back_btn)
        layout.addLayout(export_row)

        self.tabs.addTab(tab, "Capture")
        self.refresh_serial_ports()

    def refresh_serial_ports(self):
        """Refresh the editable channel selector with detected serial devices."""
        current = self.channel_edit.currentText().strip()
        ports = list_serial_ports()
        self.channel_edit.blockSignals(True)
        self.channel_edit.clear()
        for port in ports:
            self.channel_edit.addItem(port["device"], port["device"])
            index = self.channel_edit.count() - 1
            self.channel_edit.setItemData(
                index,
                f'{port["description"]} | VID:PID '
                f'{port["vid"] or "----"}:{port["pid"] or "----"}',
                Qt.ToolTipRole,
            )
        if current:
            self.channel_edit.setCurrentText(current)
        elif ports:
            self.channel_edit.setCurrentIndex(0)
        else:
            self.channel_edit.setEditText("")
            self.channel_edit.setPlaceholderText("No serial ports found; enter channel manually")
        self.channel_edit.blockSignals(False)
        if ports:
            self.status.setText(
                "Detected serial ports: " + ", ".join(port["device"] for port in ports)
            )
        else:
            self.status.setText("No serial ports detected. Manual CAN channel entry remains available.")

    def _build_sensors_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        vehicle_group = QGroupBox("Vehicle")
        vlayout = QVBoxLayout(vehicle_group)
        form = QFormLayout()
        self.vin_edit = QLineEdit()
        self.nickname_edit = QLineEdit()
        form.addRow("VIN:", self.vin_edit)
        form.addRow("Nickname:", self.nickname_edit)
        vlayout.addLayout(form)

        vbtn = QHBoxLayout()
        add_btn = QPushButton("Save vehicle")
        add_btn.clicked.connect(self.add_or_update_vehicle)
        set_btn = QPushButton("Use selected")
        set_btn.clicked.connect(self.set_current_vehicle)
        vbtn.addWidget(add_btn)
        vbtn.addWidget(set_btn)
        vlayout.addLayout(vbtn)

        self.vehicle_list = QListWidget()
        self.vehicle_list.itemClicked.connect(self.on_vehicle_selected)
        vlayout.addWidget(self.vehicle_list)
        self.current_vehicle_label = QLabel("No vehicle selected")
        vlayout.addWidget(self.current_vehicle_label)
        layout.addWidget(vehicle_group)

        actions = QHBoxLayout()
        llm_btn = QPushButton("Export LLM report")
        llm_btn.clicked.connect(self.export_llm_report)
        csv_btn = QPushButton("Export CSV")
        csv_btn.clicked.connect(self.export_sensor_csv)
        actions.addWidget(llm_btn)
        actions.addWidget(csv_btn)
        layout.addLayout(actions)

        self.sensor_log = QPlainTextEdit()
        self.sensor_log.setReadOnly(True)
        self.sensor_log.setMaximumBlockCount(2000)
        layout.addWidget(self.sensor_log)

        self.tabs.addTab(tab, "Sensors")

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        connection_group = QGroupBox("Default connection")
        connection_form = QFormLayout(connection_group)
        self.settings_backend = QComboBox()
        self.settings_backend.addItem("Virtual CAN (no hardware)", ("virtual", "freerov3r"))
        self.settings_backend.addItem("Simulated vehicle (synthetic OBD-II)", ("simulator", "L319-DEMO"))
        self.settings_backend.addItem("ESP32 serial adapter", ("esp32", "COM3"))
        self.settings_backend.addItem("SocketCAN", ("socketcan", "can0"))
        self.settings_backend.addItem("SLCAN", ("slcan", "COM3"))
        self.settings_channel = QLineEdit()
        self.settings_channel.setPlaceholderText("COM port or CAN channel")
        self.settings_bitrate = QComboBox()
        self.settings_bitrate.addItems(["125000", "250000", "500000", "1000000"])
        connection_form.addRow("Interface:", self.settings_backend)
        connection_form.addRow("Channel / port:", self.settings_channel)
        connection_form.addRow("CAN bitrate:", self.settings_bitrate)
        layout.addWidget(connection_group)

        display_group = QGroupBox("Display and logging")
        display_layout = QVBoxLayout(display_group)
        self.dark_mode_cb = QCheckBox("Dark mode")
        self.dark_mode_cb.toggled.connect(self.toggle_dark_mode)
        display_layout.addWidget(self.dark_mode_cb)
        row = QHBoxLayout()
        row.addWidget(QLabel("Maximum log lines:"))
        self.max_log_spin = QSpinBox()
        self.max_log_spin.setRange(500, 50000)
        row.addWidget(self.max_log_spin)
        display_layout.addLayout(row)
        layout.addWidget(display_group)

        graph_group = QGroupBox("Graphing")
        graph_layout = QFormLayout(graph_group)
        self.auto_refresh_graph_cb = QCheckBox("Refresh graph while listening")
        self.graph_refresh_spin = QSpinBox()
        self.graph_refresh_spin.setRange(250, 5000)
        self.graph_refresh_spin.setSingleStep(250)
        self.graph_refresh_spin.setSuffix(" ms")
        graph_layout.addRow(self.auto_refresh_graph_cb)
        graph_layout.addRow("Graph refresh interval:", self.graph_refresh_spin)
        layout.addWidget(graph_group)

        layout.addStretch()
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self.save_current_settings)
        layout.addWidget(save_btn)

        self.tabs.addTab(tab, "Settings")

    def show_dtc_mode(self):
        self.mode_label.setText("<b>Pull diagnostic codes</b><br>Listen for diagnostic traffic. Full DTC reading requires transmit (currently disabled).")
        self.tabs.setCurrentIndex(0)
        self.stack.setCurrentIndex(1)

    def show_obd_mode(self):
        self.tabs.setCurrentWidget(self.obd_tab)
        self.stack.setCurrentIndex(1)

    def show_sensor_mode(self):
        self.mode_label.setText("<b>Collect sensor data</b><br>Record sensor values and associate them with a vehicle VIN.")
        self.tabs.setCurrentIndex(1)
        self.stack.setCurrentIndex(1)

    def show_graph_mode(self):
        self.tabs.setCurrentWidget(self.graph_tab)
        self.stack.setCurrentIndex(1)

    def show_vehicle_info_mode(self):
        self.mode_label.setText("<b>Read vehicle information</b><br>Add or select a vehicle by VIN.")
        self.tabs.setCurrentIndex(1)
        self.stack.setCurrentIndex(1)

    def show_modules_mode(self):
        self.tabs.setCurrentWidget(self.modules_tab)
        self.stack.setCurrentIndex(1)

    def _apply_settings(self):
        iface = self.settings.get("interface", "virtual")
        for i in range(self.backend.count()):
            if self.backend.itemData(i)[0] == iface:
                self.backend.setCurrentIndex(i)
                break
        self.channel_edit.setCurrentText(self.settings.get("channel", "freerov3r"))
        self.bitrate.setCurrentText(str(self.settings.get("bitrate", 500000)))
        for i in range(self.settings_backend.count()):
            if self.settings_backend.itemData(i)[0] == iface:
                self.settings_backend.setCurrentIndex(i)
                break
        self.settings_channel.setText(self.settings.get("channel", "freerov3r"))
        self.settings_bitrate.setCurrentText(str(self.settings.get("bitrate", 500000)))
        self.max_log_spin.setValue(self.settings.get("max_log_lines", 5000))
        self.auto_refresh_graph_cb.setChecked(self.settings.get("auto_refresh_graph", True))
        self.graph_refresh_spin.setValue(self.settings.get("graph_refresh_ms", 1000))
        self.dark_mode_cb.setChecked(self.settings.get("dark_mode", True))
        self.apply_dark_mode(self.settings.get("dark_mode", True))
        self._refresh_vehicle_list()

    def _refresh_vehicle_list(self):
        self.vehicle_list.clear()
        vehicles = self.settings.get("vehicles", {})
        for vin, info in sorted(vehicles.items()):
            nick = info.get("nickname", "")
            self.vehicle_list.addItem(f"{vin}  —  {nick}" if nick else vin)
        current = self.settings.get("current_vin")
        if current and current in vehicles:
            nick = vehicles[current].get("nickname", "")
            self.current_vehicle_label.setText(f"Current: {current} ({nick})" if nick else f"Current: {current}")
        else:
            self.current_vehicle_label.setText("No vehicle selected")

    def add_or_update_vehicle(self):
        vin = self.vin_edit.text().strip().upper()
        nickname = self.nickname_edit.text().strip()
        if len(vin) != 17:
            QMessageBox.warning(self, "Invalid VIN", "VIN must be 17 characters.")
            return
        self.settings.setdefault("vehicles", {})[vin] = {"nickname": nickname}
        self.settings["current_vin"] = vin
        self._refresh_vehicle_list()
        self._update_vehicle_context()
        self.save_current_settings()
        self.vin_edit.clear()
        self.nickname_edit.clear()

    def set_current_vehicle(self):
        item = self.vehicle_list.currentItem()
        if not item:
            return
        vin = item.text().split("  —  ")[0]
        self.settings["current_vin"] = vin
        self._refresh_vehicle_list()
        self._update_vehicle_context()
        self.save_current_settings()

    def on_vehicle_selected(self, item):
        vin = item.text().split("  —  ")[0]
        info = self.settings.get("vehicles", {}).get(vin, {})
        self.vin_edit.setText(vin)
        self.nickname_edit.setText(info.get("nickname", ""))

    def _update_vehicle_context(self):
        vin = self.settings.get("current_vin")
        vehicles = self.settings.get("vehicles", {})
        ctx = {}
        if vin and vin in vehicles:
            ctx = {"vin": vin, "nickname": vehicles[vin].get("nickname", "")}
        self.sensor_capture.vehicle_context = ctx

        if vin and hasattr(self, "modules_tab"):
            network = self.module_networks.setdefault(vin, SimulatedModuleNetwork())
            self.modules_tab.set_network(network)
            if hasattr(self, "network_tab"):
                self.network_tab.set_network(network)
            if hasattr(self, "solutions_tab"):
                self.solutions_tab.set_network(network)

        if hasattr(self, "graph_tab"):
            self.graph_tab.set_vehicle_vin(vin)
        self._refresh_workspace_header()


    def _apply_detected_vin(self, vin):
        """Use a validated VIN decoded from observed diagnostic response traffic."""
        previous = self.settings.get("current_vin")
        if previous == vin:
            return
        if previous and previous != vin:
            self.log.appendPlainText(
                f"VIN mismatch: selected {previous}, scan data reports {vin}. Using scan-reported VIN."
            )
        self.settings.setdefault("vehicles", {}).setdefault(vin, {"nickname": ""})
        self.settings["current_vin"] = vin
        if self.receiver and self.receiver.isRunning():
            self.capture_vin = vin
        self._refresh_vehicle_list()
        self._update_vehicle_context()
        self.save_current_settings()
        self.record_vehicle_event(
            "vin_detected", "VIN decoded from diagnostic traffic",
            {"vin": vin, "source": "OBD Mode 09 PID 02 or UDS DID F190"}, vin=vin
        )
        self.log.appendPlainText(f"VIN detected from scan data: {vin}")
        self.show_toast(f"VIN identified: {vin}", "success")

    def toggle_capture(self):
        if self.receiver and self.receiver.isRunning():
            self.receiver.stop()
            elapsed = max(0.0, time.time() - (self.capture_started_at or time.time()))
            capture_samples = self.sensor_capture.samples[self.capture_start_sample_index:]
            capture_frames = self.session.frames[self.capture_start_frame_index:]
            archive_path = self.history_store.archive_capture(
                self.capture_vin,
                {
                    "interface": self.active_interface,
                    "started_at": self.capture_started_at,
                    "duration_seconds": round(elapsed, 2),
                    "frames": [
                        {"timestamp": frame.timestamp, "arbitration_id": frame.arbitration_id,
                         "extended": frame.is_extended_id, "data": frame.data.hex(),
                         "channel": frame.channel}
                        for frame in capture_frames
                    ],
                    "sensor_samples": [
                        {"timestamp": sample.timestamp, "sensor_id": sample.sensor_id,
                         "name": sample.name, "value": sample.value, "unit": sample.unit,
                         "source": sample.source, "ecu": sample.ecu, "signal": sample.signal,
                         "quality": sample.quality, "metadata": sample.metadata}
                        for sample in capture_samples
                    ],
                },
            )
            self.record_vehicle_event(
                "capture_completed", "CAN capture stopped",
                {"interface": self.active_interface, "frames": len(capture_frames),
                 "sensor_samples": len(capture_samples), "duration_seconds": round(elapsed, 2),
                 "archive_file": str(archive_path)},
                vin=self.capture_vin or "UNASSIGNED",
            )
            self.capture_started_at = None
            self.capture_vin = None
            self.receiver = None
            self.connect_btn.setText("Start listening")
            self.status.setText("Disconnected")
            self._refresh_workspace_header()
            self.show_toast("CAN capture stopped", "info")
            return

        data = self.backend.currentData()
        interface = data[0]
        channel = self.channel_edit.currentText().strip() or data[1]
        bitrate = int(self.bitrate.currentText())

        if interface == "simulator":
            adapter = SimulatedVehicleAdapter(channel=channel or "L319-DEMO")
        elif interface == "esp32":
            adapter = Esp32SerialAdapter(port=channel)
        else:
            adapter = PythonCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

        self.active_interface = interface
        self.capture_vin = self.settings.get("current_vin")
        self.capture_started_at = time.time()
        self.capture_start_frames = 0
        self.capture_start_sample_index = len(self.sensor_capture.samples)
        self.capture_start_frame_index = len(self.session.frames)
        self.record_vehicle_event(
            "capture_started", "CAN capture started",
            {"interface": interface, "channel": channel, "bitrate": bitrate},
            vin=self.capture_vin or "UNASSIGNED",
        )
        self.vin_decoder.reset()
        self.can_monitor.reset()
        self.log.clear()
        self.refresh_can_display()
        self.modules_tab.set_simulation_enabled(interface == "simulator")
        self.receiver = Receiver(adapter)
        self.receiver.frame_received.connect(self.on_frame)
        self.receiver.status.connect(self.status.setText)
        self.receiver.start()
        self.connect_btn.setText("Stop listening")
        self.frame_counter = 0
        self.last_rate_count = 0
        self.last_rate_time = time.monotonic()
        self.settings.update({"interface": interface, "channel": channel, "bitrate": bitrate})
        for i in range(self.settings_backend.count()):
            if self.settings_backend.itemData(i)[0] == interface:
                self.settings_backend.setCurrentIndex(i)
                break
        self.settings_channel.setText(channel)
        self.settings_bitrate.setCurrentText(str(bitrate))
        self._refresh_workspace_header()
        self.show_toast("CAN listener started", "success")

    def on_frame(self, frame):
        detected_vin = self.vin_decoder.feed(frame.arbitration_id, bytes(frame.data))
        if detected_vin:
            self._apply_detected_vin(detected_vin)
        self.session.add(frame)
        self.can_monitor.add(frame)
        self.frame_counter += 1
        self.frame_count_label.setText(f"Frames: {self.frame_counter}")
        ts = frame.timestamp or 0
        if self.can_monitor.matches(frame, self.can_id_filter.text(), self.can_format_filter.currentText()):
            frame_type = "EXT" if frame.is_extended_id else "STD"
            self.log.appendPlainText(
                f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
                f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}"
            )
        decoded = decode_mode01(frame)
        if decoded is not None:
            pid, name, value, unit = decoded
            self.obd_tab.update_value(pid, value)
            sensor_id = f"obd_{pid:02X}"
            simulated = self.active_interface == "simulator"
            self.sensor_capture.add(SensorSample(
                timestamp=ts or time.time(), sensor_id=sensor_id, name=name,
                value=value, unit=unit, source="simulated" if simulated else "ecu",
                ecu="SIMULATED ECU" if simulated else None,
                signal=f"Mode 01 PID {pid:02X}",
                metadata={"can_id": frame.arbitration_id, "raw": frame.data.hex(),
                         "vin": self.capture_vin or "UNASSIGNED"},
            ))
            known = any(
                self.graph_tab.sensor_list.item(i).text().endswith(f"({sensor_id})")
                for i in range(self.graph_tab.sensor_list.count())
            )
            if not known:
                self.graph_tab.refresh_sensor_list()
            self.sensor_log.appendPlainText(f"{name}: {value:.2f} {unit} [{sensor_id}]")

    def _update_rate(self):
        now = time.monotonic()
        elapsed = now - self.last_rate_time
        if elapsed >= 0.5:
            rate = (self.frame_counter - self.last_rate_count) / elapsed
            rolling_rate = self.can_monitor.rate()
            self.rate_label.setText(f"Rate: {rate:.1f} fps | Rolling: {rolling_rate:.1f} fps")
            self._refresh_workspace_header()
            top_ids = self.can_monitor.id_stats()[:5]
            summary = " | ".join(
                f"{item.arbitration_id:08X}{'X' if item.extended else 'S'}: {item.frames_per_second:.1f}/s"
                for item in top_ids
            ) or "no recent traffic"
            self.monitor_summary.setText(
                f"Buffered: {len(self.can_monitor.frames):,}/{self.can_monitor.capacity:,} "
                f"| Dropped from rolling buffer: {self.can_monitor.dropped_from_buffer:,} "
                f"| Top IDs: {summary}"
            )
            self.last_rate_count = self.frame_counter
            self.last_rate_time = now
            if (self.settings.get("auto_refresh_graph", True)
                    and self.tabs.currentWidget() is self.graph_tab
                    and self.sensor_capture.samples):
                self.graph_tab.update_chart()

    def refresh_can_display(self):
        """Rebuild the visible log using the current display-only filters."""
        if not hasattr(self, "log"):
            return
        rows = []
        for frame in self.can_monitor.frames:
            if not self.can_monitor.matches(
                frame, self.can_id_filter.text(), self.can_format_filter.currentText()
            ):
                continue
            ts = frame.timestamp or 0
            frame_type = "EXT" if frame.is_extended_id else "STD"
            rows.append(
                f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
                f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}"
            )
        self.log.setPlainText("\n".join(rows[-self.settings.get("max_log_lines", 5000):]))

    def clear_capture_display(self):
        """Clear the recent monitor window and visible log; exported session remains intact."""
        self.can_monitor.reset()
        self.log.clear()
        self.monitor_summary.setText("Recent traffic: no frames")
        self.rate_label.setText("Rate: 0 fps")

    def export_capture(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "capture.csv", "CSV (*.csv);;candump (*.log)")
        if path:
            if path.lower().endswith(".log"):
                self.session.export_candump(path)
            else:
                self.session.export_csv(path)
            self.status.setText(f"Exported {len(self.session.frames)} frames")
            self.show_toast(f"Exported {len(self.session.frames):,} CAN frames", "success")

    def export_llm_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "LLM report", "analysis.md", "Markdown (*.md)")
        if path:
            self.sensor_capture.export_llm_report(path, vin=self.settings.get("current_vin"))
            self.status.setText("LLM report saved")
            self.show_toast("Analysis report exported", "success")

    def export_sensor_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Sensor CSV", "sensors.csv", "CSV (*.csv)")
        if path:
            self.sensor_capture.export_csv(path)
            self.show_toast("Sensor data exported", "success")

    def toggle_dark_mode(self, enabled: bool):
        self.settings["dark_mode"] = enabled
        self.apply_dark_mode(enabled)

    def apply_dark_mode(self, enabled: bool):
        app = QApplication.instance()
        if enabled:
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#171b22"))
            palette.setColor(QPalette.WindowText, QColor("#e7ebf0"))
            palette.setColor(QPalette.Base, QColor("#10141a"))
            palette.setColor(QPalette.AlternateBase, QColor("#202630"))
            palette.setColor(QPalette.Text, QColor("#e7ebf0"))
            palette.setColor(QPalette.Button, QColor("#252d38"))
            palette.setColor(QPalette.ButtonText, QColor("#e7ebf0"))
            palette.setColor(QPalette.Highlight, QColor("#2675c9"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            app.setPalette(palette)
            self.setStyleSheet("""
                QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
                QMainWindow, QWidget { background: #171b22; color: #e7ebf0; }
                QWidget#workspaceHeader { background: #222833; border: 1px solid #343e4c; border-radius: 12px; }
                QDockWidget#quickDrawer { background: #20242c; color: #e7ebf0; border-left: 1px solid #3a4655; }
                QDockWidget#quickDrawer::title { background: #20242c; padding: 10px 14px; font-weight: 700; }
                QWidget#drawerBody { background: #1c222b; }
                QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
                QFrame#drawerCard { background: #252e39; border: 1px solid #3a4655; border-radius: 12px; }
                QLabel#drawerTitle { color: #f4f7fb; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#drawerSubtitle, QLabel#drawerCaption { color: #aeb9c6; font-size: 9pt; }
                QLabel#drawerValue { color: #f4f7fb; font-size: 10pt; font-weight: 700; }
                QLabel#drawerStatus { color: #82c5ff; font-weight: 700; }
                QLabel#drawerSection { color: #91a5bb; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
                QLabel#drawerNote { color: #9caaba; background: #202a36; border: 1px solid #34475b; border-radius: 9px; padding: 10px; font-size: 9pt; }
                QPushButton#drawerNavButton { text-align: left; background: #252e39; border: 1px solid #354253; border-radius: 8px; padding: 9px 12px; min-height: 22px; }
                QPushButton#drawerNavButton:hover { background: #2c4055; border-color: #5486b8; }
                QToolButton#drawerToggle { background: #263c55; color: #eaf3fc; border: 1px solid #42678e; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
                QToolButton#drawerToggle:hover { background: #315579; }
                QFrame#toastNotification { background: #252e39; border: 1px solid #48617b; border-radius: 12px; }
                QFrame#toastNotification[kind="success"] { border-left: 4px solid #35b779; }
                QFrame#toastNotification[kind="warning"] { border-left: 4px solid #e5a93d; }
                QFrame#toastNotification[kind="error"] { border-left: 4px solid #e05d67; }
                QLabel#toastMarker { color: #8cc8ff; font-size: 15pt; font-weight: 800; }
                QLabel#toastText { color: #f2f6fa; font-size: 9pt; font-weight: 600; }
                QLabel#workspaceTitle { color: #ffffff; font-family: "{HEADING_FONT}"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
                QLabel#workspaceSubtitle { color: #aebdcb; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 500; }
                QLabel#headerVehicle { background: #303d4c; color: #f3f7fb; border: 1px solid #46586b; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 700; }
                QLabel#headerOffline { background: #343b45; color: #c4ccd5; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerOnline { background: #173e30; color: #83e0b2; border: 1px solid #286849; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerSimulation { background: #4a391b; color: #ffd27c; border: 1px solid #80602b; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerTraffic { color: #dce9f7; font-family: "Inter"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
                QWidget#navigationRail { background: #111720; border: 1px solid #2c3744; border-radius: 10px; }
                QWidget#navigationSeparator { background: #344252; max-height: 1px; }
                QToolButton { background: transparent; color: #aebdcb; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
                QToolButton:hover { background: #263342; color: #ffffff; border-color: #3b5269; }
                QToolButton:checked { background: #24496b; color: #ffffff; border: 1px solid #3989d8; }
                QGroupBox { border: 1px solid #303a47; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 600; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
                QLabel#modeBanner { background: #202a36; border: 1px solid #34475b; border-radius: 8px; padding: 14px 16px; color: #dce9f7; font-family: "Inter"; font-size: 11pt; font-weight: 600; }
                QLabel#welcomeSubtitle { color: #9eabb9; font-size: 11pt; }
                QPushButton { background: #283443; color: #eaf1f8; border: 1px solid #3a4b5e; border-radius: 7px; padding: 8px 14px; min-height: 24px; }
                QPushButton:hover { background: #34485e; border-color: #5486b8; }
                QPushButton:pressed { background: #1d5d9c; }
                QPushButton#taskButton { text-align: left; font-size: 11pt; font-weight: 600; padding: 16px 18px; background: #202a36; }
                QPushButton#taskButton:hover { background: #293b4e; }
                QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget, QSpinBox { background: #10141a; color: #e7ebf0; border: 1px solid #35404d; border-radius: 5px; padding: 5px; selection-background-color: #2675c9; }
                QComboBox QAbstractItemView { background: #202630; color: #e7ebf0; selection-background-color: #2675c9; }
                QTabWidget::pane { border: 1px solid #303a47; border-radius: 8px; background: #171b22; top: 0; }
                QTabBar::tab { background: #202630; color: #aeb9c6; border: 0; border-bottom: 1px solid #303a47; padding: 14px 12px; min-width: 118px; text-align: left; }
                QTabBar::tab:selected { background: #293b4e; color: #ffffff; border-left: 3px solid #3989d8; font-weight: 600; }
                QHeaderView::section { background: #252e39; color: #dce4ed; border: 0; border-bottom: 1px solid #3a4654; padding: 7px; }
                QCheckBox { spacing: 8px; }
                QDialog#startupSplash { background: #171b22; }
                QLabel#splashEyebrow { color: #78b9f2; font-size: 9pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#splashTitle { color: #f4f7fb; font-family: "Inter Tight"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
                QLabel#splashSubtitle { color: #aebdcb; font-size: 10pt; }
                QFrame#splashCard { background: #202a36; border: 1px solid #34475b; border-radius: 12px; }
                QLabel#splashCardTitle { color: #f4f7fb; font-size: 12pt; font-weight: 700; }
                QLabel#splashCardText { color: #aebdcb; font-size: 9pt; }
                QPushButton#splashAction, QPushButton#splashContinue { background: #24496b; border: 1px solid #3989d8; font-weight: 700; }
                QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #315579; }
                QToolTip { background: #202630; color: #ffffff; border: 1px solid #526174; }
            """.replace("{BODY_FONT}", self.body_font_family).replace("{HEADING_FONT}", self.heading_font_family))
        else:
            app.setPalette(app.style().standardPalette())
            self.setStyleSheet("""
                QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
                QWidget#workspaceHeader { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
                QDockWidget#quickDrawer { background: #f8fafc; color: #1e293b; border-left: 1px solid #d9e0e8; }
                QDockWidget#quickDrawer::title { background: #f1f5f9; padding: 10px 14px; font-weight: 700; }
                QWidget#drawerBody { background: #f8fafc; }
                QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
                QFrame#drawerCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
                QLabel#drawerTitle { color: #172033; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#drawerSubtitle, QLabel#drawerCaption { color: #64748b; font-size: 9pt; }
                QLabel#drawerValue { color: #172033; font-size: 10pt; font-weight: 700; }
                QLabel#drawerStatus { color: #1769aa; font-weight: 700; }
                QLabel#drawerSection { color: #64748b; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
                QLabel#drawerNote { color: #475569; background: #eff6ff; border: 1px solid #d5e5f6; border-radius: 9px; padding: 10px; font-size: 9pt; }
                QPushButton#drawerNavButton { text-align: left; background: #ffffff; border: 1px solid #d9e0e8; border-radius: 8px; padding: 9px 12px; min-height: 22px; color: #243449; }
                QPushButton#drawerNavButton:hover { background: #eff6ff; border-color: #9bbfe2; }
                QToolButton#drawerToggle { background: #e8f2fc; color: #174b78; border: 1px solid #b9d2eb; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
                QToolButton#drawerToggle:hover { background: #d9eafa; }
                QFrame#toastNotification { background: #ffffff; border: 1px solid #d3deea; border-radius: 12px; }
                QFrame#toastNotification[kind="success"] { border-left: 4px solid #219b64; }
                QFrame#toastNotification[kind="warning"] { border-left: 4px solid #d28a16; }
                QFrame#toastNotification[kind="error"] { border-left: 4px solid #d94853; }
                QLabel#toastMarker { color: #2675c9; font-size: 15pt; font-weight: 800; }
                QLabel#toastText { color: #243449; font-size: 9pt; font-weight: 600; }
                QLabel#workspaceTitle { color: #172033; font-family: "Inter Tight"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
                QLabel#workspaceSubtitle { color: #596b7d; font-family: "Inter"; font-size: 9.5pt; font-weight: 500; }
                QLabel#headerVehicle { background: #edf2f7; color: #24384c; border: 1px solid #cbd6e0; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 700; }
                QLabel#headerOffline { background: #eef0f2; color: #596675; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerOnline { background: #e1f4e9; color: #17633b; border: 1px solid #a6d7b8; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerSimulation { background: #fff1d6; color: #80520b; border: 1px solid #e6c98d; border-radius: 7px; padding: 9px 12px; font-family: "Inter"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerTraffic { color: #26394b; font-family: "Inter"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
                QWidget#navigationRail { background: #f1f4f7; border: 1px solid #d5dde5; border-radius: 10px; }
                QWidget#navigationSeparator { background: #d5dde5; max-height: 1px; }
                QToolButton { background: transparent; color: #526273; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
                QToolButton:hover { background: #e2eaf2; color: #1f3448; border-color: #c4d1de; }
                QToolButton:checked { background: #dceaf7; color: #174b78; border: 1px solid #6a9dcc; }
                QLabel#modeBanner { background: #edf3f8; border: 1px solid #cbd7e2; border-radius: 8px; padding: 14px 16px; color: #26394b; font-family: "Inter"; font-size: 11pt; font-weight: 600; }
                QLabel#welcomeSubtitle { color: #647386; font-size: 11pt; }
                QPushButton { border: 1px solid #c5ced8; border-radius: 7px; padding: 8px 14px; min-height: 24px; }
                QPushButton#taskButton { text-align: left; font-size: 11pt; font-weight: 600; padding: 16px 18px; }
                QTabWidget::pane { border: 1px solid #cbd3dc; border-radius: 8px; }
                QTabBar::tab { padding: 14px 12px; min-width: 118px; text-align: left; }
                QTabBar::tab:selected { font-weight: 600; border-left: 3px solid #2675c9; }
                QGroupBox { border: 1px solid #cbd3dc; border-radius: 8px; margin-top: 12px; padding: 12px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
                QDialog#startupSplash { background: #f8fafc; }
                QLabel#splashEyebrow { color: #2675c9; font-size: 9pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#splashTitle { color: #172033; font-family: "Inter Tight"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
                QLabel#splashSubtitle { color: #596b7d; font-size: 10pt; }
                QFrame#splashCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
                QLabel#splashCardTitle { color: #172033; font-size: 12pt; font-weight: 700; }
                QLabel#splashCardText { color: #596b7d; font-size: 9pt; }
                QPushButton#splashAction, QPushButton#splashContinue { background: #e8f2fc; color: #174b78; border: 1px solid #9bbfe2; font-weight: 700; }
                QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #d9eafa; }
            """.replace("{BODY_FONT}", self.body_font_family).replace("{HEADING_FONT}", self.heading_font_family))

    def save_current_settings(self):
        backend_data = self.settings_backend.currentData()
        if backend_data:
            self.settings["interface"] = backend_data[0]
            self.settings["channel"] = self.settings_channel.text().strip() or backend_data[1]
            self.settings["bitrate"] = int(self.settings_bitrate.currentText())
            for i in range(self.backend.count()):
                if self.backend.itemData(i)[0] == backend_data[0]:
                    self.backend.setCurrentIndex(i)
                    break
            self.channel_edit.setCurrentText(self.settings["channel"])
            self.bitrate.setCurrentText(str(self.settings["bitrate"]))
        self.settings["max_log_lines"] = self.max_log_spin.value()
        self.settings["dark_mode"] = self.dark_mode_cb.isChecked()
        self.settings["auto_refresh_graph"] = self.auto_refresh_graph_cb.isChecked()
        self.settings["graph_refresh_ms"] = self.graph_refresh_spin.value()
        self.log.setMaximumBlockCount(self.settings["max_log_lines"])
        if hasattr(self, "rate_timer"):
            self.rate_timer.setInterval(self.settings["graph_refresh_ms"])
        save_settings(self.settings)
        self.status.setText("Settings saved")
        self.show_toast("Settings saved", "success")

    def closeEvent(self, event):
        if self.receiver and self.receiver.isRunning():
            self.toggle_capture()
        self.save_current_settings()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.show_startup_splash_if_enabled)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
