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
    QTableWidget, QTableWidgetItem, QHeaderView,
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
        self.sensor_list.setSelectionMode(QListWidget.MultiSelection)
        self.sensor_list.setMaximumHeight(140)
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
        self.sensor_list.clear()
        seen = set()
        for sample in self.sensor_capture.samples:
            if sample.sensor_id not in seen:
                seen.add(sample.sensor_id)
                self.sensor_list.addItem(f"{sample.name} ({sample.sensor_id})")
        if not HAS_CHARTS and hasattr(self, "placeholder"):
            self.placeholder.setPlainText(f"{len(self.sensor_capture.samples)} samples loaded.\n{len(seen)} unique sensors.")

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

        selected_ids = [item.text().split("(")[-1].rstrip(")") for item in self.sensor_list.selectedItems()]
        if not selected_ids:
            selected_ids = [self.sensor_list.item(i).text().split("(")[-1].rstrip(")") for i in range(self.sensor_list.count())]

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
            "This tab shows common PIDs and will display live values once request capability is enabled."
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
    def __init__(self, session: CaptureSession, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)

        note = QLabel(
            "<b>Vehicle Modules (CAN)</b><br>"
            "L319 module list is a placeholder. Addresses must come from verified documentation. "
            "Select a module to filter the current capture."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.module_list = QListWidget()
        for code, name, addr in L319_MODULES:
            self.module_list.addItem(f"{code} — {name}  [{addr}]")
        self.module_list.itemClicked.connect(self.on_module_selected)
        layout.addWidget(self.module_list)

        self.filter_log = QPlainTextEdit()
        self.filter_log.setReadOnly(True)
        self.filter_log.setPlaceholderText("Select a module to see related frames from the current capture...")
        layout.addWidget(self.filter_log)

        refresh_btn = QPushButton("Refresh from Capture")
        refresh_btn.clicked.connect(lambda: self.on_module_selected(self.module_list.currentItem()))
        layout.addWidget(refresh_btn)

    def on_module_selected(self, item):
        if not item:
            return
        self.filter_log.clear()
        # Placeholder filter — real filtering needs verified IDs
        self.filter_log.appendPlainText(f"Selected: {item.text()}\n")
        self.filter_log.appendPlainText(f"Frames in session: {len(self.session.frames)}")
        self.filter_log.appendPlainText("(Module-specific ID filtering will be added once verified addresses are available.)")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.session = CaptureSession()
        self.sensor_capture = SensorCapture()
        self.receiver = None
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
        self.rate_timer.start(1000)

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
        self.modules_tab = ModulesTab(self.session)
        self.tabs.addTab(self.modules_tab, "Modules")
        self._build_settings_tab()

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

        self.dark_mode_cb = QCheckBox("Dark mode")
        self.dark_mode_cb.toggled.connect(self.toggle_dark_mode)
        layout.addWidget(self.dark_mode_cb)

        row = QHBoxLayout()
        row.addWidget(QLabel("Max log lines:"))
        self.max_log_spin = QSpinBox()
        self.max_log_spin.setRange(500, 20000)
        self.max_log_spin.valueChanged.connect(lambda v: self.log.setMaximumBlockCount(v))
        row.addWidget(self.max_log_spin)
        layout.addLayout(row)

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
        self.max_log_spin.setValue(self.settings.get("max_log_lines", 5000))
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
            self.receiver = None
            self.connect_btn.setText("Start listening")
            self.status.setText("Disconnected")
            return

        data = self.backend.currentData()
        interface = data[0]
        channel = self.channel_edit.text().strip() or data[1]
        bitrate = int(self.bitrate.currentText())

        if interface == "simulator":
            adapter = SimulatedVehicleAdapter(channel=channel)
        elif interface == "esp32":
            adapter = Esp32SerialAdapter(port=channel)
        else:
            adapter = PythonCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

        self.receiver = Receiver(adapter)
        self.receiver.frame_received.connect(self.on_frame)
        self.receiver.status.connect(self.status.setText)
        self.receiver.start()
        self.connect_btn.setText("Stop listening")
        self.frame_counter = 0
        self.last_rate_count = 0
        self.last_rate_time = time.monotonic()
        self.settings.update({"interface": interface, "channel": channel, "bitrate": bitrate})

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
            simulated = bool(frame.channel and "DEMO" in frame.channel)
            self.sensor_capture.add(SensorSample(
                timestamp=ts or time.time(), sensor_id=sensor_id, name=name,
                value=value, unit=unit, source="simulated" if simulated else "ecu",
                ecu="SIMULATED ECU" if simulated else None,
                signal=f"Mode 01 PID {pid:02X}",
                metadata={"can_id": frame.arbitration_id, "raw": frame.data.hex()},
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
        save_settings(self.settings)
        self.status.setText("Settings saved")

    def closeEvent(self, event):
        if self.receiver and self.receiver.isRunning():
            self.receiver.stop()
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