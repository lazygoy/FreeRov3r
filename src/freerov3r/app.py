"""FreeRov3r – user-friendly diagnostic interface with graphing, OBD-II, and modules."""
import csv
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtGui import QPalette, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow,
    QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QGroupBox,
    QFormLayout, QCheckBox, QSpinBox, QStackedWidget, QColorDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .hardware.python_can_adapter import PythonCanAdapter
from .hardware.esp32_serial_adapter import Esp32SerialAdapter
from .hardware.simulated_vehicle import SimulatedVehicleAdapter, decode_mode01
from .session import CaptureSession
from .sensors.capture import SensorCapture
from .sensors.models import SensorSample
from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .vehicle_history import VehicleHistoryStore

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
        self.recording = False
        self.record_start = None

        layout = QVBoxLayout(self)

        if not HAS_CHARTS:
            msg = QLabel(
                "<b>Graphing unavailable</b><br><br>"
                "PySide6.QtCharts is not installed.<br>"
                "Run: <code>pip install --upgrade PySide6</code> then restart.<br><br>"
                "CSV load/export still works."
            )
            msg.setWordWrap(True)
            msg.setAlignment(Qt.AlignCenter)
            layout.addWidget(msg)
        else:
            info = QLabel("Select sensors, set colors/scale, zoom with mouse. Right-click chart to reset zoom.")
            info.setWordWrap(True)
            layout.addWidget(info)

        controls = QHBoxLayout()
        self.sensor_list = QListWidget()
        self.sensor_list.setMaximumHeight(140)
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

            self.auto_scale = QCheckBox("Auto Y-scale")
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
            self.chart = QChart()
            self.chart.setTitle("Sensor / PID Graph")
            self.chart.legend().setVisible(True)
            self.chart.setAnimationOptions(QChart.SeriesAnimations)

            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.chart_view.setRubberBand(QChartView.RectangleRubberBand)
            layout.addWidget(self.chart_view)

            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("Time (s from start)")
            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("Value")
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
            if sample.sensor_id not in seen:
                seen.add(sample.sensor_id)
                item = QListWidgetItem(f"{sample.name} ({sample.sensor_id})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked if sample.sensor_id in self.hidden_sensor_ids else Qt.Checked)
                self.sensor_list.addItem(item)
        self.sensor_list.blockSignals(False)
        if HAS_CHARTS:
            self.update_chart()
        if not HAS_CHARTS and hasattr(self, "placeholder"):
            self.placeholder.setPlainText(f"{len(self.sensor_capture.samples)} samples loaded.\\n{len(seen)} unique sensors.")

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
            path, _ = QFileDialog.getSaveFileName(self, "Save sensor recording", "sensor_recording.csv", "CSV (*.csv)")
            if path:
                self.sensor_capture.export_csv(path)

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

        selected_ids = [
            self.sensor_list.item(i).text().split("(")[-1].rstrip(")")
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        ]

        min_t = min_v = float("inf")
        max_t = max_v = float("-inf")
        base_time = self.record_start or (self.sensor_capture.samples[0].timestamp if self.sensor_capture.samples else 0)

        for sample in self.sensor_capture.samples:
            if sample.sensor_id not in selected_ids:
                continue
            t = sample.timestamp - base_time
            if sample.sensor_id not in self.series_map:
                series = QLineSeries()
                series.setName(f"{sample.name} ({sample.sensor_id})")
                color = self.color_map.get(sample.sensor_id, QColor.fromHsv(abs(hash(sample.sensor_id)) % 360, 180, 220))
                series.setColor(color)
                self.chart.addSeries(series)
                series.attachAxis(self.axis_x)
                series.attachAxis(self.axis_y)
                self.series_map[sample.sensor_id] = series
            self.series_map[sample.sensor_id].append(t, sample.value)
            min_t, max_t = min(min_t, t), max(max_t, t)
            min_v, max_v = min(min_v, sample.value), max(max_v, sample.value)

        if min_t != float("inf"):
            self.axis_x.setRange(min_t, max_t + 0.5)
            if self.auto_scale.isChecked():
                pad = max((max_v - min_v) * 0.15, 1.0)
                self.axis_y.setRange(min_v - pad, max_v + pad)
            else:
                try:
                    self.axis_y.setRange(float(self.ymin.text()), float(self.ymax.text()))
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
                    )
                    self.sensor_capture.add(sample)
                    count += 1
                except (KeyError, ValueError):
                    continue
        self.refresh_sensor_list()
        if HAS_CHARTS:
            self.update_chart()
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.session = CaptureSession()
        self.sensor_capture = SensorCapture()
        self.history_store = VehicleHistoryStore(SETTINGS_DIR / "vehicle_history.json")
        self.receiver = None
        self.capture_started_at = None
        self.capture_start_frames = 0
        self.capture_start_sample_index = 0
        self.capture_start_frame_index = 0
        self.capture_vin = None
        self.active_interface = None
        self.frame_counter = 0
        self.last_rate_time = time.monotonic()
        self.last_rate_count = 0

        self.setWindowTitle("FreeRov3r")
        self.resize(1100, 750)

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
        self.mode_label.setStyleSheet("background: #2a2a2a; padding: 10px; border-radius: 6px;")

        # Welcome
        welcome = QWidget()
        wlayout = QVBoxLayout(welcome)
        wlayout.setAlignment(Qt.AlignCenter)
        wlayout.setSpacing(16)

        title = QLabel("What would you like to do?")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(title)

        subtitle = QLabel("Choose a task to get started. You can switch later.")
        subtitle.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(subtitle)

        btn_style = "QPushButton { font-size: 14px; padding: 12px; min-width: 280px; }"
        tasks = [
            ("Pull diagnostic codes (DTCs)", self.show_dtc_mode),
            ("Read OBD-II data", self.show_obd_mode),
            ("Collect sensor data", self.show_sensor_mode),
            ("Graph sensor data", self.show_graph_mode),
            ("Read vehicle information", self.show_vehicle_info_mode),
            ("Vehicle modules (CAN)", self.show_modules_mode),
        ]
        for text, slot in tasks:
            btn = QPushButton(text)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(slot)
            wlayout.addWidget(btn, alignment=Qt.AlignCenter)

        self.stack.addWidget(welcome)

        # Tabs
        self.tabs = QTabWidget()
        self.stack.addWidget(self.tabs)

        self._build_capture_tab()
        self._build_sensors_tab()
        self.graph_tab = SensorGraphTab(self.sensor_capture)
        self.tabs.addTab(self.graph_tab, "Graph")
        self.obd_tab = OBDTab()
        self.tabs.addTab(self.obd_tab, "OBD-II")
        self.module_network = SimulatedModuleNetwork()
        self.modules_tab = ModulesTab(
            self.module_network,
            vin_provider=lambda: self.settings.get("current_vin"),
            history_callback=self.record_vehicle_event,
        )
        self.tabs.addTab(self.modules_tab, "Modules")
        self.history_tab = VehicleHistoryTab(self.history_store)
        self.tabs.addTab(self.history_tab, "Vehicle History")
        self._build_settings_tab()

    def record_vehicle_event(self, event_type, summary, details=None, vin=None):
        vehicle_vin = vin if vin is not None else self.settings.get("current_vin")
        self.history_store.record(vehicle_vin, event_type, summary, details)
        if hasattr(self, "history_tab"):
            self.history_tab.refresh()

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

        self.channel_edit = QLineEdit()
        self.channel_edit.setPlaceholderText("COM port or channel")
        controls.addWidget(self.channel_edit)

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

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(self.settings.get("max_log_lines", 5000))
        layout.addWidget(self.log)

        export_row = QHBoxLayout()
        export_btn = QPushButton("Export capture")
        export_btn.clicked.connect(self.export_capture)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log.clear)
        back_btn = QPushButton("← Back to tasks")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        export_row.addWidget(export_btn)
        export_row.addWidget(clear_btn)
        export_row.addStretch()
        export_row.addWidget(back_btn)
        layout.addLayout(export_row)

        self.tabs.addTab(tab, "Capture")

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
        self.channel_edit.setText(self.settings.get("channel", "freerov3r"))
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
                vin=self.capture_vin,
            )
            self.capture_started_at = None
            self.capture_vin = None
            self.receiver = None
            self.connect_btn.setText("Start listening")
            self.status.setText("Disconnected")
            return

        data = self.backend.currentData()
        interface = data[0]
        channel = self.channel_edit.text().strip() or data[1]
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
            vin=self.capture_vin,
        )
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

    def on_frame(self, frame):
        self.session.add(frame)
        self.frame_counter += 1
        self.frame_count_label.setText(f"Frames: {self.frame_counter}")
        ts = frame.timestamp or 0
        self.log.appendPlainText(f"{ts:.6f}  {frame.arbitration_id:08X}  {frame.data.hex(' ').upper()}")
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
            self.rate_label.setText(f"Rate: {rate:.1f} fps")
            self.last_rate_count = self.frame_counter
            self.last_rate_time = now
            if (self.settings.get("auto_refresh_graph", True)
                    and self.tabs.currentWidget() is self.graph_tab
                    and self.sensor_capture.samples):
                self.graph_tab.update_chart()

    def export_capture(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "capture.csv", "CSV (*.csv);;candump (*.log)")
        if path:
            if path.lower().endswith(".log"):
                self.session.export_candump(path)
            else:
                self.session.export_csv(path)
            self.status.setText(f"Exported {len(self.session.frames)} frames")

    def export_llm_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "LLM report", "analysis.md", "Markdown (*.md)")
        if path:
            self.sensor_capture.export_llm_report(path)
            self.status.setText("LLM report saved")

    def export_sensor_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Sensor CSV", "sensors.csv", "CSV (*.csv)")
        if path:
            self.sensor_capture.export_csv(path)

    def toggle_dark_mode(self, enabled: bool):
        self.settings["dark_mode"] = enabled
        self.apply_dark_mode(enabled)

    def apply_dark_mode(self, enabled: bool):
        app = QApplication.instance()
        if enabled:
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(32, 32, 32))
            palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
            palette.setColor(QPalette.Text, QColor(220, 220, 220))
            palette.setColor(QPalette.Button, QColor(50, 50, 50))
            palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
            app.setPalette(palette)
            self.setStyleSheet("""
                QPlainTextEdit, QLineEdit, QComboBox, QListWidget, QSpinBox, QTableWidget {
                    background-color: #1e1e1e; color: #dcdcdc; border: 1px solid #555;
                }
                QGroupBox { color: #dcdcdc; font-weight: bold; }
                QPushButton { padding: 6px 12px; }
                QHeaderView::section { background-color: #333; color: #dcdcdc; }
            """)
        else:
            app.setPalette(app.style().standardPalette())
            self.setStyleSheet("")

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
            self.channel_edit.setText(self.settings["channel"])
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()