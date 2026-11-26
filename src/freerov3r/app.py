"""FreeRov3r – user-friendly diagnostic interface with graphing, OBD-II, and modules."""
import csv
import json
import math
import queue
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer, Qt, QUrl
from PySide6.QtGui import QPalette, QColor, QFont, QFontDatabase, QPainter, QBrush, QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow,
    QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QGroupBox,
    QFormLayout, QCheckBox, QSpinBox, QStackedWidget, QColorDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QGridLayout, QToolButton, QButtonGroup,
    QDialog, QFrame, QScrollArea, QSizePolicy, QInputDialog,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .hardware.serial_ports import list_serial_ports
from .hardware.interface_discovery import discover_interfaces
from .hardware.elm327_serial_adapter import Elm327SerialAdapter, query_vin
from .hardware.elm327_obd_adapter import Elm327ObdAdapter
from .diagnostics.vehicle_identification import identify_vehicle, validate_vin, decode_vin_online
from .vehicle_profiles.registry import VehicleProfileRegistry
from .hardware.python_can_adapter import PythonCanAdapter
from .hardware.esp32_serial_adapter import Esp32SerialAdapter
from .hardware.esp32_dual_serial_adapter import Esp32DualSerialAdapter
from .hardware.simulated_vehicle import SimulatedVehicleAdapter
from .diagnostics.obd2 import (OBD_PIDS, PID_CATEGORIES_ALL, PID_MULTI_VALUE_KEYS, search_mode01_pids, decode_mode01_measurements, Mode01ScalingContext)
from .session import CaptureSession
from .can_monitor import CanMonitor
from .sensors.capture import SensorCapture
from .sensors.models import SensorSample
from .sensors.scaling import normalize_values
from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .diagnostics.service_routines import ServiceRoutine, ServiceRoutineManager
from .diagnostics.l319_wiring import NETWORKS as L319_WIRING_NETWORKS, SOURCE_URL as L319_WIRING_SOURCE_URL, DEFAULT_ENGINE as L319_DEFAULT_ENGINE

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    HAS_PDF_VIEWER = True
except ImportError:
    QPdfDocument = QPdfView = None
    HAS_PDF_VIEWER = False
from .vehicle_history import VehicleHistoryStore, filter_dtc_scan_events, format_dtc_scan_event
from .diagnostics.vin_decoder import VinFrameDecoder
from .ui_feedback import QuickDrawer, ToastManager
from .asset_loader import ASSET_DIR, load_asset_pixmap
from .research_tab import ResearchTab
from .tuning_tab import TuningTab

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


class ResponsiveBanner(QLabel):
    """Wide photographic banner with layout-safe custom painting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._rendered_pixmap = QPixmap()
        self._refreshing = False
        self._last_render_size = None

        self.setObjectName("brandBanner")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(132)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_source_pixmap(self, pixmap):
        self._source_pixmap = pixmap
        self._last_render_size = None
        self._refresh_banner()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_banner()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self._rendered_pixmap.isNull():
            painter.drawPixmap(0, 0, self._rendered_pixmap)
        else:
            painter.fillRect(self.rect(), self.palette().window())
        painter.end()

    def _refresh_banner(self):
        if (
            self._refreshing
            or self._source_pixmap.isNull()
            or self.width() < 2
            or self.height() < 2
        ):
            return

        target_size = self.size()
        if target_size == self._last_render_size:
            return

        self._refreshing = True
        try:
            scaled = self._source_pixmap.scaled(
                target_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )

            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            rendered = scaled.copy(x, y, self.width(), self.height())

            painter = QPainter(rendered)
            painter.setRenderHint(QPainter.Antialiasing)

            title_font = QFont(
                "Gill Sans MT", max(20, int(self.height() * 0.34))
            )
            title_font.setBold(True)
            title_font.setItalic(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#f4f7f3"))
            painter.drawText(34, int(self.height() * 0.55), "FreeRov3r")

            tagline_font = QFont(
                "Gill Sans MT", max(8, int(self.height() * 0.095))
            )
            tagline_font.setBold(True)
            painter.setFont(tagline_font)
            painter.setPen(QColor("#d5e2d8"))
            painter.drawText(
                38,
                int(self.height() * 0.76),
                "DIAGNOSTICS  •  MONITORING  •  SOLUTIONS"
            )

            painter.end()

            self._rendered_pixmap = rendered
            self._last_render_size = target_size
            self.update()

        finally:
            self._refreshing = False



class Receiver(QThread):
    frame_received = Signal(object)
    status = Signal(str)
    dtcs_completed = Signal(object)
    dtcs_failed = Signal(str)

    def __init__(self, adapter):
        super().__init__()
        self.adapter = adapter
        self.running = True
        self._commands = queue.Queue()
        self._dtc_request_pending = False

    def request_dtcs(self):
        """Queue a DTC read for execution by the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_dtcs", None)):
            return False
        if self._dtc_request_pending:
            return False
        self._dtc_request_pending = True
        self._commands.put("read_dtcs")
        return True

    def run(self):
        try:
            self.adapter.open()
            self.status.emit(f"Connected: {self.adapter.description}")
            while self.running:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == "read_dtcs":
                    try:
                        self.dtcs_completed.emit(self.adapter.read_dtcs())
                    except Exception as exc:
                        self.dtcs_failed.emit(str(exc))
                    finally:
                        self._dtc_request_pending = False
                    continue
                frame = self.adapter.receive(0.15)
                if frame is not None:
                    self.frame_received.emit(frame)
        except Exception as exc:
            if hasattr(self.adapter, "last_error"):
                self.adapter.last_error = str(exc)
            self.status.emit(f"Adapter error: {exc}")
            if self._dtc_request_pending:
                self.dtcs_failed.emit(str(exc))
        finally:
            try:
                self.adapter.close()
            except Exception:
                pass
            self._dtc_request_pending = False

    def stop(self):
        self.running = False
        self.wait(2500)


class VinQueryWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.port = port

    def run(self):
        try:
            self.completed.emit(query_vin(self.port))
        except Exception as exc:
            self.failed.emit(str(exc))


class VinDecodeWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, vin, parent=None):
        super().__init__(parent)
        self.vin = vin

    def run(self):
        try:
            self.completed.emit(decode_vin_online(self.vin))
        except Exception as exc:
            self.failed.emit(str(exc))


class VehicleSetupWizard(QDialog):
    """Optional connection and vehicle setup wizard."""

    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("FreeRov3r | Vehicle Setup")
        self.setMinimumSize(760, 540)
        self.setModal(True)
        self.result_data = None
        self._vin_worker = None
        self._decode_worker = None
        self._decoded = None
        self.setObjectName("startupSplash")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        eyebrow = QLabel("FREEROV3R CONFIGURATION")
        eyebrow.setObjectName("splashEyebrow")
        root.addWidget(eyebrow)
        self.page_title = QLabel("Connect an interface")
        self.page_title.setObjectName("splashTitle")
        root.addWidget(self.page_title)
        self.page_description = QLabel(
            "Detect USB serial and paired Bluetooth COM interfaces, or choose one manually. "
            "Wi-Fi discovery is not implemented yet. Detection does not transmit to the vehicle."
        )
        self.page_description.setWordWrap(True)
        self.page_description.setObjectName("splashSubtitle")
        root.addWidget(self.page_description)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)

        # Page 1: connection selection
        connection_page = QWidget()
        connection_layout = QVBoxLayout(connection_page)
        connection_form = QFormLayout()
        self.interface_combo = QComboBox()
        self._interfaces = [
            ("virtual", "Virtual CAN (no hardware)", "freerov3r"),
            ("simulator", "Simulated vehicle (demo)", "L319-DEMO"),
            ("esp32", "ESP32 single CAN channel", "COM3"),
            ("esp32_dual", "ESP32 dual CAN channels (two boards)", "COM3,COM4"),
            ("elm327", "ELM327 raw CAN monitor", ""),
            ("elm327_obd", "ELM327 active OBD-II polling", ""),
            ("socketcan", "SocketCAN", "can0"),
            ("slcan", "SLCAN", "COM3"),
        ]
        for kind, label, channel in self._interfaces:
            self.interface_combo.addItem(label, (kind, channel))
        self.channel_edit = QComboBox()
        self.channel_edit.setEditable(True)
        self.channel_edit.setInsertPolicy(QComboBox.NoInsert)
        self.channel_edit.setPlaceholderText("Select detected port or enter channel")
        connection_form.addRow("Interface:", self.interface_combo)
        connection_form.addRow("Port / channel:", self.channel_edit)
        connection_layout.addLayout(connection_form)
        detect_row = QHBoxLayout()
        detect_button = QPushButton("Detect interfaces")
        detect_button.clicked.connect(self.detect_interfaces)
        detect_row.addWidget(detect_button)
        detect_row.addStretch()
        connection_layout.addLayout(detect_row)
        self.interface_status = QLabel(
            "ESP32 interfaces are receive-only. Dual mode requires two different COM ports, entered as COMx,COMy (HS-CAN first, MS-CAN second). "
            "Bluetooth/serial ELM327 supports either passive CAN monitoring or read-only Mode 01 polling. "
            "Wi-Fi adapter support is not implemented yet."
        )
        self.interface_status.setWordWrap(True)
        self.interface_status.setObjectName("mutedText")
        connection_layout.addWidget(self.interface_status)
        connection_layout.addStretch()
        self.pages.addWidget(connection_page)

        # Page 2: VIN and manual vehicle details
        vehicle_page = QWidget()
        vehicle_layout = QVBoxLayout(vehicle_page)
        vehicle_form = QFormLayout()
        self.vin_edit = QLineEdit()
        self.vin_edit.setMaxLength(17)
        self.vin_edit.setPlaceholderText("17-character VIN")
        self.make_edit = QLineEdit()
        self.make_edit.setPlaceholderText("Manufacturer")
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Model / series")
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Model year")
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Land Rover L319 (LR3 / LR4)", "land_rover_l319")
        self.profile_combo.addItem("Land Rover LR3 / Discovery 3 (L319)", "land_rover_l319_lr3")
        self.profile_combo.addItem("Land Rover LR4 / Discovery 4 (L319)", "land_rover_l319_lr4")
        self.profile_combo.addItem("Generic OBD-II / CAN (other vehicle)", "generic")
        vehicle_form.addRow("VIN:", self.vin_edit)
        vehicle_form.addRow("Make:", self.make_edit)
        vehicle_form.addRow("Model:", self.model_edit)
        vehicle_form.addRow("Model year:", self.year_edit)
        vehicle_form.addRow("Capability package:", self.profile_combo)
        vehicle_layout.addLayout(vehicle_form)
        vin_actions = QHBoxLayout()
        self.read_vin_button = QPushButton("Read VIN from ELM327")
        self.read_vin_button.clicked.connect(self.read_vin)
        vin_actions.addWidget(self.read_vin_button)
        self.decode_vin_button = QPushButton("Identify from VIN")
        self.decode_vin_button.clicked.connect(self.decode_vin)
        vin_actions.addWidget(self.decode_vin_button)
        vehicle_layout.addLayout(vin_actions)
        self.vin_status = QLabel(
            "The VIN is read using the standard OBD-II Mode 09 PID 02 request when "
            "an ELM327 adapter is selected. Other adapters may require transmit-capable "
            "firmware or a manual VIN."
        )
        self.vin_status.setWordWrap(True)
        self.vin_status.setObjectName("mutedText")
        vehicle_layout.addWidget(self.vin_status)
        vehicle_layout.addStretch()
        self.pages.addWidget(vehicle_page)

        # Page 3: review
        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        self.review_text = QPlainTextEdit()
        self.review_text.setReadOnly(True)
        review_layout.addWidget(self.review_text)
        self.pages.addWidget(review_page)

        footer = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("splashContinue")
        self.next_button.clicked.connect(self.go_next)
        self.skip_button = QPushButton("Skip to full workspace")
        self.skip_button.clicked.connect(self.reject)
        self.finish_button = QPushButton("Finish setup")
        self.finish_button.setObjectName("splashContinue")
        self.finish_button.clicked.connect(self.finish_setup)
        footer.addWidget(self.back_button)
        footer.addStretch()
        footer.addWidget(self.skip_button)
        footer.addWidget(self.next_button)
        footer.addWidget(self.finish_button)
        root.addLayout(footer)

        settings = current_settings or {}
        saved_interface = settings.get("interface")
        saved_channel = settings.get("channel", "")
        for index in range(self.interface_combo.count()):
            data = self.interface_combo.itemData(index)
            if data and data[0] == saved_interface:
                self.interface_combo.setCurrentIndex(index)
                break
        self.channel_edit.setEditText(str(saved_channel or ""))
        self.detect_interfaces()
        self._show_page(0)
        self.interface_combo.currentIndexChanged.connect(self._update_vin_query_availability)
        self.channel_edit.editTextChanged.connect(self._update_vin_query_availability)

    def detect_interfaces(self):
        current = self.channel_edit.currentText().strip()
        ports = discover_interfaces()
        self.channel_edit.clear()
        for port in ports:
            self.channel_edit.addItem(port["device"], port["device"])
            index = self.channel_edit.count() - 1
            self.channel_edit.setItemData(
                index,
                f'{port["label"]} | {port["description"]} | '
                f'VID:PID {port["vid"] or "----"}:{port["pid"] or "----"}',
                Qt.ToolTipRole,
            )
        if current:
            self.channel_edit.setEditText(current)
        elif len(ports) == 1:
            self.channel_edit.setCurrentIndex(0)
        elif not ports:
            self.channel_edit.setEditText("")
        recognized = [p for p in ports if p["kind"] in ("esp32", "elm327", "slcan")]
        if len(recognized) == 1:
            candidate = recognized[0]
            for index in range(self.interface_combo.count()):
                data = self.interface_combo.itemData(index)
                if data and data[0] == candidate["kind"]:
                    self.interface_combo.setCurrentIndex(index)
                    self.channel_edit.setEditText(candidate["device"])
                    break
        self.interface_status.setText(
            ("Detected: " + "; ".join(f'{p["device"]} — {p["label"]}' for p in ports))
            if ports else
            "No serial adapters detected. You can still enter a channel manually or continue without hardware."
        )
        self._update_vin_query_availability()

    def _update_vin_query_availability(self):
        data = self.interface_combo.currentData()
        is_elm = bool(data and data[0] in ("elm327", "elm327_obd"))
        self.read_vin_button.setEnabled(is_elm and bool(self.channel_edit.currentText().strip()))
        if is_elm:
            self.read_vin_button.setToolTip("Send the read-only OBD-II Mode 09 PID 02 VIN request.")
        else:
            self.read_vin_button.setToolTip(
                "Active VIN querying is currently implemented for ELM327 serial adapters. "
                "ESP32 firmware is presently receive-only."
            )

    def read_vin(self):
        data = self.interface_combo.currentData()
        port = self.channel_edit.currentText().strip()
        if not data or data[0] != "elm327" or not port:
            return
        self.read_vin_button.setEnabled(False)
        self.decode_vin_button.setEnabled(False)
        self.vin_edit.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.channel_edit.setEnabled(False)
        self.next_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.vin_status.setText("Querying VIN with OBD-II Mode 09 PID 02…")
        self._vin_worker = VinQueryWorker(port, self)
        self._vin_worker.completed.connect(self._vin_query_completed)
        self._vin_worker.failed.connect(self._vin_query_failed)
        self._vin_worker.finished.connect(self._vin_query_finished)
        self._vin_worker.start()

    def _vin_query_completed(self, vin):
        self.vin_edit.setText(vin)
        self.decode_vin()
        self.vin_status.setText("VIN read successfully from the vehicle. " + self.vin_status.text())

    def _vin_query_failed(self, message):
        self.vin_status.setText(f"VIN query failed: {message}")

    def _vin_query_finished(self):
        if self._decode_worker and self._decode_worker.isRunning():
            return
        self.decode_vin_button.setEnabled(True)
        self.vin_edit.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.channel_edit.setEnabled(True)
        self.next_button.setEnabled(True)
        self.back_button.setEnabled(self.pages.currentIndex() > 0)
        self.skip_button.setEnabled(True)
        self._update_vin_query_availability()

    def _apply_vehicle_identification(self, result):
        self._decoded = result
        if result.get("make"):
            self.make_edit.setText(result["make"])
        if result.get("model"):
            self.model_edit.setText(result["model"])
        if result.get("model_year"):
            self.year_edit.setText(str(result["model_year"]))
        profile_id = result.get("profile_id", "generic")
        if profile_id == "generic":
            make = str(result.get("make") or "").strip().lower()
            model = str(result.get("model") or "").strip().lower()
            year = result.get("model_year")
            # Unknown identity defaults to the shared L319 workspace. A VIN
            # decode naming another make/model explicitly selects generic.
            if not make and not model:
                profile_id = "land_rover_l319"
            elif "land rover" in make and not model:
                profile_id = "land_rover_l319"
            elif "land rover" in make and (
                "discovery" in model or "lr3" in model or "lr4" in model
            ):
                if "discovery 3" in model or "lr3" in model or (year and 2005 <= year <= 2009):
                    profile_id = "land_rover_l319_lr3"
                elif "discovery 4" in model or "lr4" in model or (year and 2010 <= year <= 2016):
                    profile_id = "land_rover_l319_lr4"
                else:
                    profile_id = "land_rover_l319"
        profile_index = self.profile_combo.findData(profile_id)
        if profile_index >= 0:
            self.profile_combo.setCurrentIndex(profile_index)

    def decode_vin(self):
        vin = validate_vin(self.vin_edit.text())
        if not vin:
            self.vin_status.setText("Enter a valid 17-character VIN before identifying the vehicle.")
            return
        result = identify_vehicle(vin)
        self._apply_vehicle_identification(result)
        if result.get("profile_id") in ("land_rover_l319_lr3", "land_rover_l319_lr4"):
            self.vin_status.setText(
                f'{result["confidence"].upper()} LOCAL MATCH: {result["reason"]} '
                "Review the suggested vehicle details before continuing."
            )
            return
        self.vin_status.setText(
            "No installed manufacturer-specific package matches this VIN. "
            "Checking NHTSA vPIC for manufacturer-reported make, model and year…"
        )
        self.read_vin_button.setEnabled(False)
        self.decode_vin_button.setEnabled(False)
        self.vin_edit.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.channel_edit.setEnabled(False)
        self.next_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self._decode_worker = VinDecodeWorker(vin, self)
        self._decode_worker.completed.connect(self._vin_decode_completed)
        self._decode_worker.failed.connect(self._vin_decode_failed)
        self._decode_worker.finished.connect(self._vin_decode_finished)
        self._decode_worker.start()

    def _vin_decode_completed(self, result):
        self._apply_vehicle_identification(result)
        details = [
            f'{result.get("make") or "Unknown make"} {result.get("model") or "Unknown model"}',
            str(result.get("model_year") or "Year unavailable"),
        ]
        if result.get("engine_model"):
            details.append(result["engine_model"])
        self.vin_status.setText(
            "NHTSA vPIC result: " + " | ".join(details)
            + ". Generic OBD-II/CAN package selected; manufacturer-specific support is not inferred."
        )

    def _vin_decode_failed(self, message):
        self.vin_status.setText(
            "Online VIN decoding unavailable. The VIN remains saved as an unidentified "
            "vehicle; enter make, model and year manually if needed. " + message
        )

    def _vin_decode_finished(self):
        self.decode_vin_button.setEnabled(True)
        self.vin_edit.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.channel_edit.setEnabled(True)
        self.next_button.setEnabled(True)
        self.back_button.setEnabled(self.pages.currentIndex() > 0)
        self.skip_button.setEnabled(True)
        self._update_vin_query_availability()

    def _show_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Connect an interface", "Identify your vehicle", "Review configuration"]
        descriptions = [
            "Detect a supported adapter or choose one manually. Detection inventories local interfaces; it does not transmit to the vehicle.",
            "Read the VIN with a supported adapter, enter it manually, or provide vehicle details yourself.",
            "Check the selected connection and vehicle profile before applying setup.",
        ]
        self.page_title.setText(titles[index])
        self.page_description.setText(descriptions[index])
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < 2)
        self.finish_button.setVisible(index == 2)

    def go_next(self):
        page = self.pages.currentIndex()
        if page == 0:
            self._show_page(1)
        elif page == 1:
            self._build_review()
            self._show_page(2)

    def go_back(self):
        self._show_page(max(0, self.pages.currentIndex() - 1))

    def _build_review(self):
        interface = self.interface_combo.currentData()
        channel = self.channel_edit.currentText().strip()
        profile_id = self.profile_combo.currentData() or "generic"
        vin = validate_vin(self.vin_edit.text())
        year_text = self.year_edit.text().strip()
        try:
            year = int(year_text) if year_text else None
        except ValueError:
            year = None
        self.result_data = {
            "interface": interface[0] if interface else "virtual",
            "channel": channel or (interface[1] if interface else "freerov3r"),
            "bitrate": 500000,
            "vin": vin,
            "make": self.make_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "model_year": year,
            "profile_id": profile_id,
            "identification": self._decoded or {},
        }
        rows = [
            "CONNECTION",
            f'Interface: {interface[1] if interface else "Virtual CAN"}',
            f'Port / channel: {self.result_data["channel"] or "Not selected"}',
            "",
            "VEHICLE",
            f'VIN: {vin or "Not provided"}',
            f'Make: {self.result_data["make"] or "Not specified"}',
            f'Model: {self.result_data["model"] or "Not specified"}',
            f'Model year: {year or "Not specified"}',
            f'Capability package: {self.profile_combo.currentText()}',
            "",
            "The shared L319 workspace is the default while vehicle identity is unknown. "
            "A VIN decode identifying another make/model selects the generic package.",
        ]
        self.review_text.setPlainText("\n".join(rows))

    def finish_setup(self):
        self._build_review()
        profile_id = self.result_data["profile_id"]
        year = self.result_data["model_year"]
        valid_years = {
            "land_rover_l319": range(2005, 2017),
            "land_rover_l319_lr3": range(2005, 2010),
            "land_rover_l319_lr4": range(2010, 2017),
        }
        if year is not None and profile_id in valid_years and year not in valid_years[profile_id]:
            QMessageBox.warning(
                self,
                "Vehicle profile does not match model year",
                "The selected LR3/LR4 package does not match the entered model year. "
                "Correct the year or select the generic OBD-II/CAN package.",
            )
            return
        self.accept()

    def reject(self):
        for worker in (self._vin_worker, self._decode_worker):
            if worker and worker.isRunning():
                worker.wait(8000)
        super().reject()


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
        self.last_sample_time = {}
        self.activity_phase = True
        self.synced_obd_sensor_ids = set()
        self.selection_changed_callback = None
        self.favorites_changed_callback = None
        self.navigate_to_obd_callback = None
        self.parent_settings = {}

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

        load_btn = QPushButton("Load CSV")
        load_btn.clicked.connect(self.load_csv)
        right.addWidget(load_btn)
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_sensor_list)
        right.addWidget(refresh_btn)
        controls.addLayout(right, 1)
        layout.addLayout(controls)
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
        self.activity_timer.setInterval(350)
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

    def mark_sample(self, sensor_id):
        self.last_sample_time[str(sensor_id)] = time.monotonic()
        self._update_activity_indicators()

    def _update_activity_indicators(self):
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
        base_time = min(sample.timestamp for sample in all_samples)
        min_t = min(sample.timestamp - base_time for sample in all_samples)
        max_t = max(sample.timestamp - base_time for sample in all_samples)

        independent = self.independent_scale.isChecked()
        self.axis_y.setTitleText("Relative scale per sensor (%)" if independent else "Value (shared scale)")
        raw_min = min(sample.value for sample in all_samples)
        raw_max = max(sample.value for sample in all_samples)

        for sensor_id, samples in grouped.items():
            samples.sort(key=lambda sample: sample.timestamp)
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
    """Searchable, categorized OBD-II PID selector with persistent user groups."""

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self.pid_rows = {}
        self._loading_group = False
        self._syncing_selection = False
        self.selection_changed_callback = None
        self.favorites_changed_callback = None
        self.navigate_to_graph_callback = None
        self.last_sample_time = {}
        self.activity_phase = True
        layout = QVBoxLayout(self)

        note = QLabel(
            "<b>OBD-II</b><br>"
            "Read-only Mode 01 polling is available when using the dedicated ELM327 OBD-II "
            "connection. Other interfaces remain passive unless their transmit support is "
            "implemented and explicitly enabled. No ECU write commands are sent. "
            "The simulator streams clearly labeled synthetic Mode 01 values; real vehicles "
            "also populate this table when matching response frames are observed. "
            "A listed PID is not proof that the vehicle supports it."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Find sensor:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search coolant, RPM, throttle, voltage, PID…")
        self.search_edit.textChanged.connect(self.filter_pids)
        search_row.addWidget(self.search_edit, 2)
        search_row.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(PID_CATEGORIES_ALL)
        self.category_combo.currentTextChanged.connect(self.filter_pids)
        search_row.addWidget(self.category_combo, 1)
        layout.addLayout(search_row)

        favorite_row = QHBoxLayout()
        favorite_row.addWidget(QLabel("Favorite group:"))
        self.favorite_combo = QComboBox()
        self.favorite_combo.setMinimumWidth(170)
        self.favorite_combo.currentIndexChanged.connect(self._favorite_selection_changed)
        favorite_row.addWidget(self.favorite_combo, 1)
        self.load_group_btn = QPushButton("Load")
        self.load_group_btn.clicked.connect(self.load_favorite_group)
        favorite_row.addWidget(self.load_group_btn)
        self.save_group_btn = QPushButton("Save selected as…")
        self.save_group_btn.clicked.connect(self.save_favorite_group)
        favorite_row.addWidget(self.save_group_btn)
        self.delete_group_btn = QPushButton("Delete")
        self.delete_group_btn.clicked.connect(self.delete_favorite_group)
        favorite_row.addWidget(self.delete_group_btn)
        layout.addLayout(favorite_row)

        self.table = QTableWidget(len(OBD_PIDS), 7)
        self.table.setHorizontalHeaderLabels(
            ["Poll", "PID", "Category", "Sensor", "Unit", "Value", "Live"]
        )
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for row, (pid, desc, unit) in enumerate(OBD_PIDS):
            pid_int = int(pid, 16)
            category = next(
                (entry[3] for entry in search_mode01_pids() if entry[0] == pid),
                "Other",
            )
            poll_item = QTableWidgetItem()
            poll_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            poll_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, poll_item)
            self.table.setItem(row, 1, QTableWidgetItem(pid))
            self.table.setItem(row, 2, QTableWidgetItem(category))
            self.table.setItem(row, 3, QTableWidgetItem(desc))
            self.table.setItem(row, 4, QTableWidgetItem(unit))
            self.table.setItem(row, 5, QTableWidgetItem("—"))
            live_item = QTableWidgetItem("○")
            live_item.setTextAlignment(Qt.AlignCenter)
            live_item.setToolTip("No recent samples")
            self.table.setItem(row, 6, live_item)
            self.pid_rows[pid_int] = row
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 58)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(4, 65)
        self.table.setColumnWidth(5, 85)
        self.table.setColumnWidth(6, 48)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(350)
        self.activity_timer.timeout.connect(self._update_activity_indicators)
        self.activity_timer.start()
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table, 1)

        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Request interval:"))
        self.poll_interval_ms = QSpinBox()
        self.poll_interval_ms.setRange(50, 2000)
        self.poll_interval_ms.setValue(200)
        self.poll_interval_ms.setSuffix(" ms / PID")
        self.poll_interval_ms.setToolTip(
            "Delay between sequential Mode 01 PID requests on an active ELM327 connection."
        )
        poll_row.addWidget(self.poll_interval_ms)
        select_visible_btn = QPushButton("Select visible")
        select_visible_btn.clicked.connect(lambda: self._set_visible_checks(Qt.Checked))
        poll_row.addWidget(select_visible_btn)
        clear_visible_btn = QPushButton("Clear visible")
        clear_visible_btn.clicked.connect(lambda: self._set_visible_checks(Qt.Unchecked))
        poll_row.addWidget(clear_visible_btn)
        self.open_graph_btn = QPushButton("View in Graph")
        self.open_graph_btn.clicked.connect(lambda: self.navigate_to_graph_callback() if self.navigate_to_graph_callback else None)
        poll_row.addWidget(self.open_graph_btn)
        poll_row.addStretch()
        layout.addLayout(poll_row)

        btn_row = QHBoxLayout()
        self.request_btn = QPushButton(
            "Active polling is selected by the ELM327 OBD-II connection"
        )
        self.request_btn.setEnabled(False)
        self.request_btn.setToolTip(
            "Polling starts only when the dedicated ELM327 OBD-II adapter is selected."
        )
        btn_row.addWidget(self.request_btn)
        clear_btn = QPushButton("Clear Values")
        clear_btn.clicked.connect(self.clear_values)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        dtc_group = QGroupBox("DIAGNOSTIC TROUBLE CODES")
        dtc_layout = QVBoxLayout(dtc_group)
        dtc_actions = QHBoxLayout()
        self.read_dtcs_btn = QPushButton("Read Stored / Pending / Permanent Codes")
        self.read_dtcs_btn.setEnabled(False)
        self.read_dtcs_btn.setToolTip(
            "Uses standard read-only OBD-II services 03, 07 and 0A on an active ELM327 OBD-II connection."
        )
        self.read_dtcs_btn.clicked.connect(self.request_dtc_scan)
        dtc_actions.addWidget(self.read_dtcs_btn)
        self.dtc_status_label = QLabel("Connect an ELM327 OBD-II adapter to read trouble codes.")
        self.dtc_status_label.setWordWrap(True)
        dtc_actions.addWidget(self.dtc_status_label, 1)
        dtc_layout.addLayout(dtc_actions)
        self.dtc_table = QTableWidget(0, 5)
        self.dtc_table.setHorizontalHeaderLabels(
            ["Code", "Status", "Response ECU", "Channel", "Raw"]
        )
        self.dtc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.dtc_table.setMaximumHeight(190)
        self.dtc_table.setAlternatingRowColors(True)
        self.dtc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        dtc_layout.addWidget(self.dtc_table)
        layout.addWidget(dtc_group)
        self.read_dtcs_callback = None
        self._refresh_favorite_combo()

    def request_dtc_scan(self):
        if self.read_dtcs_callback is None:
            self.dtc_status_label.setText("Start an ELM327 OBD-II connection before requesting DTCs.")
            return
        if self.read_dtcs_callback():
            self.read_dtcs_btn.setEnabled(False)
            self.dtc_status_label.setText("Reading stored, pending and permanent DTCs…")
        else:
            self.dtc_status_label.setText("DTC read is unavailable or another read is already in progress.")

    def set_dtc_scan_enabled(self, enabled):
        self.read_dtcs_btn.setEnabled(bool(enabled))
        if not enabled:
            self.dtc_status_label.setText("Connect an ELM327 OBD-II adapter to read trouble codes.")

    def show_dtc_results(self, codes):
        self.dtc_table.setRowCount(0)
        for code in codes:
            row = self.dtc_table.rowCount()
            self.dtc_table.insertRow(row)
            values = (
                code.get("code", ""),
                code.get("status", ""),
                f"{code.get('arbitration_id', 0):08X}"
                + (" (29-bit)" if code.get("is_extended_id") else " (11-bit)"),
                code.get("channel", ""),
                code.get("raw", ""),
            )
            for column, value in enumerate(values):
                self.dtc_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.dtc_status_label.setText(
            f"Read complete: {len(codes)} code record(s). "
            "Descriptions are not inferred; verify OEM-specific meaning separately."
            if codes else
            "Read complete: no stored, pending or permanent codes were returned."
        )
        self.read_dtcs_btn.setEnabled(True)

    def set_dtc_scan_error(self, message):
        self.dtc_status_label.setText(f"DTC read failed: {message}")
        self.read_dtcs_btn.setEnabled(True)

    def filter_pids(self, *_):
        query = self.search_edit.text()
        category = self.category_combo.currentText()
        visible = {int(row[0], 16) for row in search_mode01_pids(query, category)}
        for pid, row in self.pid_rows.items():
            self.table.setRowHidden(row, pid not in visible)

    def _set_visible_checks(self, state):
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, 0).setCheckState(state)

    def selected_pids(self):
        return [
            int(self.table.item(row, 1).text(), 16)
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]

    def selected_sensor_ids(self):
        selected = set()
        for pid in self.selected_pids():
            keys = PID_MULTI_VALUE_KEYS.get(pid)
            if keys:
                selected.update(f"obd_{pid:02X}_{key}" for key in keys)
            else:
                selected.add(f"obd_{pid:02X}")
        return selected

    def set_selected_sensor_ids(self, sensor_ids):
        selected = {str(value).lower() for value in sensor_ids}
        self._syncing_selection = True
        self.table.blockSignals(True)
        for pid, row in self.pid_rows.items():
            keys = PID_MULTI_VALUE_KEYS.get(pid, ())
            checked = f"obd_{pid:02X}" in selected or any(
                f"obd_{pid:02X}_{key}" in selected for key in keys
            )
            self.table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.table.blockSignals(False)
        self._syncing_selection = False

    def _on_table_item_changed(self, item):
        if item.column() == 0 and not self._syncing_selection and self.selection_changed_callback:
            self.selection_changed_callback(self.selected_sensor_ids())

    def _update_activity_indicators(self):
        now = time.monotonic()
        self.activity_phase = not self.activity_phase
        for pid, row in self.pid_rows.items():
            item = self.table.item(row, 6)
            active = now - self.last_sample_time.get(pid, 0) <= 5.0
            item.setText("●" if active else "○")
            item.setForeground(QColor("#39d98a") if active and self.activity_phase else
                               QColor("#27885b") if active else QColor("#77818c"))
            item.setToolTip("Live data arriving" if active else "No recent samples")

    def update_value(self, pid, value):
        row = self.pid_rows.get(pid)
        if row is not None:
            if isinstance(value, str):
                display_value = value
            else:
                display_value = f"{value:.2f}".rstrip("0").rstrip(".")
            self.table.item(row, 5).setText(display_value)
            self.last_sample_time[pid] = time.monotonic()
            self._update_activity_indicators()

    def clear_values(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 5).setText("—")

    def _favorite_groups(self):
        groups = self.settings.get("obd_pid_favorites", {})
        return groups if isinstance(groups, dict) else {}

    def _refresh_favorite_combo(self, selected_name=None):
        self._loading_group = True
        self.favorite_combo.clear()
        self.favorite_combo.addItem("Choose saved group…", None)
        for name in sorted(self._favorite_groups(), key=str.casefold):
            self.favorite_combo.addItem(name, name)
        if selected_name:
            index = self.favorite_combo.findData(selected_name)
            if index >= 0:
                self.favorite_combo.setCurrentIndex(index)
        self._loading_group = False
        has_group = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(has_group)
        self.delete_group_btn.setEnabled(has_group)

    def _favorite_selection_changed(self, *_):
        if self._loading_group:
            return
        has_group = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(has_group)
        self.delete_group_btn.setEnabled(has_group)

    def load_favorite_group(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        sensor_ids = set()
        for value in self._favorite_groups().get(name, []):
            text = str(value).strip().lower()
            if text.startswith("obd_"):
                sensor_ids.add(text)
            else:
                try:
                    sensor_ids.add(f"obd_{int(text, 16):02X}")
                except ValueError:
                    continue
        self.set_selected_sensor_ids(sensor_ids)
        if self.selection_changed_callback:
            self.selection_changed_callback(sensor_ids)

    def save_favorite_group(self):
        pids = self.selected_pids()
        if not pids:
            QMessageBox.information(
                self, "No PIDs selected",
                "Select at least one sensor before saving a favorite group.",
            )
            return
        name, accepted = QInputDialog.getText(
            self, "Save PID group", "Group name:"
        )
        name = name.strip()
        if not accepted or not name:
            return
        groups = dict(self._favorite_groups())
        groups[name] = [f"obd_{pid:02X}" for pid in pids]
        self.settings["obd_pid_favorites"] = groups
        save_settings(self.settings)
        self._refresh_favorite_combo(name)
        if self.favorites_changed_callback:
            self.favorites_changed_callback(name)

    def delete_favorite_group(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        groups = dict(self._favorite_groups())
        groups.pop(name, None)
        self.settings["obd_pid_favorites"] = groups
        save_settings(self.settings)
        self._refresh_favorite_combo()
        if self.favorites_changed_callback:
            self.favorites_changed_callback()


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
        self.health_report_btn = QPushButton("Generate Health Report")
        self.health_report_btn.setObjectName("primaryButton")
        self.health_report_btn.setToolTip(
            "Scan the complete module inventory and create a concise vehicle health summary."
        )
        self.health_report_btn.clicked.connect(self.generate_health_report)
        actions.addWidget(self.health_report_btn)
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
        self.module_tree.setMinimumWidth(230)
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
        right.addWidget(QLabel("VEHICLE HEALTH REPORT"))
        self.health_report = QPlainTextEdit()
        self.health_report.setReadOnly(True)
        self.health_report.setMinimumHeight(105)
        self.health_report.setPlaceholderText(
            "Run Generate Health Report for a module-by-module summary."
        )
        right.addWidget(self.health_report, 1)
        report_export_row = QHBoxLayout()
        self.export_health_report_btn = QPushButton("Export Health Report")
        self.export_health_report_btn.clicked.connect(self.export_health_report)
        report_export_row.addWidget(self.export_health_report_btn)
        report_export_row.addStretch()
        right.addLayout(report_export_row)
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

    def generate_health_report(self):
        """Run the available complete inventory check and render an evidence-labelled report."""
        vin = self.vin_provider()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.simulation_enabled:
            report = [
                "FREEROV3R VEHICLE HEALTH REPORT",
                f"Generated: {timestamp}",
                f"Vehicle VIN: {vin or 'Not selected'}",
                "",
                "RESULT: LIVE MODULE SCAN NOT AVAILABLE",
                "",
                "No physical vehicle modules were interrogated. The current live hardware "
                "connection supports passive CAN capture only; live ECU addressing and "
                "module diagnostic requests are not implemented in this build.",
                "",
                "The module inventory shown in this workspace is a development fixture. "
                "It must not be interpreted as the installed modules or actual condition "
                "of the vehicle.",
                "",
                "NEXT STEP",
                "Select 'Simulated vehicle (synthetic OBD-II)' in Capture and start listening "
                "to generate a clearly labelled demonstration report. For a real vehicle "
                "report, verified model-specific ECU addressing and read-only diagnostic "
                "services must be implemented first.",
                "",
                "DATA INTEGRITY: No real ECU results were created or inferred.",
            ]
            self.health_report.setPlainText("\n".join(report))
            self.result_log.appendPlainText(
                "HEALTH REPORT: blocked. Live module interrogation is not implemented; no ECU was queried."
            )
            return

        if not vin:
            self.health_report.setPlainText(
                "FREEROV3R VEHICLE HEALTH REPORT\n"
                f"Generated: {timestamp}\n"
                "RESULT: NOT RUN\n\n"
                "Select a vehicle and save its 17-character VIN in the Sensors tab, "
                "then run the report again. No module scan was performed."
            )
            return

        modules = self.network.scan_all()
        dtc_entries = [
            (module, dtc) for module in modules for dtc in module.dtcs
        ]
        affected = [module for module in modules if module.dtcs]
        severity_counts = {}
        for module, dtc in dtc_entries:
            severity = (dtc.severity or "Unclassified").strip()
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        lines = [
            "FREEROV3R VEHICLE HEALTH REPORT",
            f"Generated: {timestamp}",
            f"Vehicle VIN: {vin}",
            "DATA SOURCE: SYNTHETIC MODULE SIMULATOR",
            "IMPORTANT: This is a demonstration report, not a scan of a physical vehicle.",
            "",
            "EXECUTIVE SUMMARY",
            f"Module inventory scanned: {len(modules)}",
            f"Modules responding in simulator: {sum(1 for module in modules if module.available)}",
            f"Modules with DTC entries: {len(affected)}",
            f"Total DTC entries: {len(dtc_entries)}",
        ]
        if severity_counts:
            lines.append("DTC severity breakdown:")
            lines.extend(
                f"  • {severity}: {count}"
                for severity, count in sorted(severity_counts.items())
            )
        else:
            lines.append("DTC severity breakdown: No DTC entries.")
        lines.extend(["", "MODULE FINDINGS"])
        for module in modules:
            status = "FAULTS RECORDED" if module.dtcs else "NO DTC ENTRIES"
            if not module.available:
                status = "NO SIMULATOR RESPONSE"
            lines.append(f"{module.code} — {module.name} [{module.category}]")
            lines.append(f"  Status: {status}")
            if module.dtcs:
                for dtc in module.dtcs:
                    lines.append(
                        f"  • {dtc.code} | {dtc.status} | {dtc.severity}: {dtc.description}"
                    )
            else:
                lines.append("  • No DTC entries in simulator fixture.")
        lines.extend([
            "",
            "ASSESSMENT",
            (
                f"{len(affected)} module(s) contain example DTC entries. "
                "Review each listed code against verified service information."
                if affected else
                "No DTC entries are present in this simulator fixture."
            ),
            "",
            "LIMITATIONS",
            "All module names, response states and DTC entries above are synthetic test data. "
            "They do not establish actual vehicle fitment, ECU communication, fault status, "
            "roadworthiness or repair requirements. No commands were sent to a physical ECU.",
        ])
        report_text = "\n".join(lines)
        self.health_report.setPlainText(report_text)
        self.result_log.appendPlainText(
            f"HEALTH REPORT: {len(modules)} simulated modules checked; "
            f"{len(affected)} with DTC entries; {len(dtc_entries)} total DTC(s)."
        )
        self.history_callback(
            "module_health_report",
            "Module health report generated (simulator)",
            {
                "source": "synthetic_module_simulator",
                "modules_scanned": len(modules),
                "modules_with_dtcs": len(affected),
                "dtc_count": len(dtc_entries),
                "severity_counts": severity_counts,
                "report": report_text,
            },
            vin=vin,
        )
        self.refresh_tree()

    def export_health_report(self):
        report = self.health_report.toPlainText().strip()
        if not report:
            QMessageBox.information(
                self, "No health report", "Generate a health report before exporting."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export vehicle health report", "vehicle_health_report.txt",
            "Text report (*.txt);;Markdown (*.md)"
        )
        if path:
            Path(path).write_text(report + "\n", encoding="utf-8")
            self.result_log.appendPlainText(f"Health report exported: {path}")

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
    """Interactive, evidence-labelled topology view over the current module inventory."""

    STATUS_STYLES = {
        "faults": ("#ef5350", "#351d22", "ATTENTION"),
        "clean": ("#35b779", "#17352b", "NO FAULTS"),
        "unscanned": ("#9aa7b5", "#202a35", "NOT SCANNED"),
        "offline": ("#87909a", "#24282d", "NO RESPONSE"),
    }

    def __init__(self, network, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.network = network
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.selected_code = None
        self.map_buttons = {}
        self._building = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel("VEHICLE NETWORK TOPOLOGY")
        title.setObjectName("sectionTitle")
        title_column.addWidget(title)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        self.heading.setObjectName("mutedText")
        title_column.addWidget(self.heading)
        header.addLayout(title_column, 1)

        self.scan_all_button = QPushButton("⟳  Scan All Modules")
        self.scan_all_button.setObjectName("primaryButton")
        self.scan_all_button.clicked.connect(self.scan_all)
        header.addWidget(self.scan_all_button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.summary_row = QHBoxLayout()
        self.summary_cards = {}
        for key, label in (
            ("total", "MODULES"),
            ("scanned", "SCANNED"),
            ("faults", "WITH DTCS"),
            ("unscanned", "NOT SCANNED"),
        ):
            card = QFrame()
            card.setObjectName("topologyMetric")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            value = QLabel("0")
            value.setObjectName("topologyMetricValue")
            caption = QLabel(label)
            caption.setObjectName("topologyMetricLabel")
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            self.summary_cards[key] = value
            self.summary_row.addWidget(card)
        root.addLayout(self.summary_row)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("STATUS:"))
        for color, label in (
            ("#35b779", "No faults"),
            ("#ef5350", "DTCs present"),
            ("#9aa7b5", "Not scanned"),
            ("#87909a", "No response"),
        ):
            swatch = QLabel("●")
            swatch.setStyleSheet(f"color:{color};font-size:15px;")
            legend.addWidget(swatch)
            text = QLabel(label)
            text.setObjectName("mutedText")
            legend.addWidget(text)
        legend.addStretch(1)
        self.view_toggle = QPushButton("System List")
        self.view_toggle.setCheckable(True)
        self.view_toggle.toggled.connect(self._toggle_view)
        legend.addWidget(self.view_toggle)
        root.addLayout(legend)

        content = QHBoxLayout()
        content.setSpacing(10)

        self.map_scroll = QScrollArea()
        self.map_scroll.setWidgetResizable(True)
        self.map_scroll.setFrameShape(QFrame.NoFrame)
        self.map_scroll.setMinimumWidth(0)
        self.map_scroll.setObjectName("topologyMapScroll")
        self.map_body = QWidget()
        self.map_grid = QGridLayout(self.map_body)
        self.map_grid.setContentsMargins(8, 8, 8, 8)
        self.map_grid.setSpacing(10)
        self.map_tree = QTreeWidget()
        self.map_tree.setObjectName("thinkcarTopologyTree")
        self.map_tree.setHeaderLabels(["VEHICLE NETWORK / MODULE", "SCAN STATUS", "DTCs"])
        self.map_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.map_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.map_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.map_tree.setAlternatingRowColors(False)
        self.map_tree.setUniformRowHeights(True)
        self.map_tree.itemSelectionChanged.connect(self._map_selection_changed)
        self.map_grid.addWidget(self.map_tree, 0, 0)
        self.map_scroll.setWidget(self.map_body)
        content.addWidget(self.map_scroll, 3)

        self.system_list = QTreeWidget()
        self.system_list.setHeaderLabels(["System / module", "Status", "DTCs", "Last scan"])
        self.system_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.system_list.setMinimumWidth(360)
        self.system_list.itemSelectionChanged.connect(self._list_selection_changed)
        self.system_list.itemDoubleClicked.connect(self._open_module_details)
        self.system_list.hide()
        content.addWidget(self.system_list, 3)

        detail_frame = QFrame()
        detail_frame.setObjectName("topologyDetailPanel")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(8)
        detail_title = QLabel("MODULE DETAILS")
        detail_title.setObjectName("sectionTitle")
        detail_layout.addWidget(detail_title)
        self.detail_name = QLabel("Select a module")
        self.detail_name.setObjectName("topologyDetailName")
        self.detail_name.setWordWrap(True)
        detail_layout.addWidget(self.detail_name)
        self.detail_status = QLabel("No module selected")
        self.detail_status.setObjectName("mutedText")
        detail_layout.addWidget(self.detail_status)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Select a module node to inspect scan status and diagnostic trouble codes.")
        detail_layout.addWidget(self.detail_text, 1)
        self.scan_selected_button = QPushButton("Scan Selected Module")
        self.scan_selected_button.clicked.connect(self.scan_selected)
        self.scan_selected_button.setEnabled(False)
        detail_layout.addWidget(self.scan_selected_button)
        content.addWidget(detail_frame, 2)
        root.addLayout(content, 1)

        self._toggle_view(False)
        self.refresh()

    def set_network(self, network):
        self.network = network
        self.selected_code = None
        self.refresh()

    def _module_status(self, module):
        if not module.available:
            return "offline"
        if module.last_scan is None:
            return "unscanned"
        if module.dtcs:
            return "faults"
        return "clean"

    def _status_text(self, module):
        return self.STATUS_STYLES[self._module_status(module)][2]

    def _toggle_view(self, list_mode):
        self.map_scroll.setVisible(not list_mode)
        self.system_list.setVisible(list_mode)
        self.view_toggle.setText("Topology Map" if list_mode else "System List")

    def _clear_map(self):
        self.map_tree.clear()
        self.map_buttons.clear()

    def _make_module_node(self, module):
        status = self._module_status(module)
        accent, background, label = self.STATUS_STYLES[status]
        node = QPushButton()
        node.setObjectName("topologyModuleNode")
        node.setCheckable(True)
        node.setMinimumSize(145, 82)
        node.setMaximumHeight(100)
        node.setStyleSheet(
            "QPushButton#topologyModuleNode {"
            f"background:{background};border:1px solid {accent};"
            "border-radius:9px;padding:8px;text-align:left;color:#edf2f7;}"
            "QPushButton#topologyModuleNode:checked {border:2px solid #58a6ff;}"
            "QPushButton#topologyModuleNode:hover {border:2px solid #a9c9e8;}"
        )
        dtc_count = len(module.dtcs)
        node.setText(f"{module.code}\n{module.name}\n{label}  ·  {dtc_count} DTC")
        node.setToolTip(
            f"{module.name}\nStatus: {label}\nDTC count: {dtc_count}\n"
            "Inventory is simulated; physical network path and ECU address are not verified."
        )
        node.clicked.connect(lambda checked=False, code=module.code: self.select_module(code))
        self.map_buttons[module.code] = node
        return node

    def _build_map(self):
        """Build a Thinkcar-style expandable vehicle/network/module tree.

        Network membership comes from the transcribed 2010 L319 factory
        reference. Scan state is overlaid only where a simulator fixture can
        be matched; unmatched factory entries remain reference-only.
        """
        self._clear_map()
        root = QTreeWidgetItem([
            f"2010 DISCOVERY 4  •  {L319_DEFAULT_ENGINE}",
            "FACTORY REFERENCE",
            "—",
        ])
        root.setExpanded(True)
        root.setForeground(0, QBrush(QColor("#58a6ff")))
        self.map_tree.addTopLevelItem(root)

        # Explicit aliases only where the simulator fixture represents the
        # same functional module. No guessed mapping for optional equipment.
        fixture_aliases = {
            "ABS/DSC": "ABS",
            "AIR-SUS": "RLM",
            "SAS": "SASM",
            "IC-HS": "IC",
            "IC-MS": "IC",
        }
        for network_key in ("HS-CAN", "MS-CAN", "MOST"):
            info = L319_WIRING_NETWORKS.get(network_key, {})
            branch = QTreeWidgetItem([
                f"▰  {info.get('title', network_key)}",
                "WIRING REFERENCE",
                "—",
            ])
            branch.setExpanded(True)
            branch.setForeground(0, QBrush(QColor("#58a6ff")))
            branch.setToolTip(0, f"{info.get('description', '')}\n{info.get('pages', '')}")
            root.addChild(branch)

            for code, component, name, connector, notes in info.get("modules", []):
                fixture_code = fixture_aliases.get(code, code)
                try:
                    module = self.network.get_module(fixture_code)
                except (KeyError, AttributeError):
                    module = None

                if module is None:
                    status = "REFERENCE ONLY"
                    dtc_count = "—"
                    accent = "#8995a3"
                else:
                    status = self._status_text(module)
                    dtc_count = str(len(module.dtcs))
                    accent = self.STATUS_STYLES[self._module_status(module)][0]

                item = QTreeWidgetItem([
                    f"{code}  ·  {name}  [{component}]",
                    status,
                    dtc_count,
                ])
                item.setData(0, Qt.UserRole, {
                    "fixture_code": fixture_code if module is not None else None,
                    "code": code,
                    "component": component,
                    "name": name,
                    "connector": connector,
                    "notes": notes,
                    "network": network_key,
                })
                item.setForeground(0, QBrush(QColor(accent)))
                item.setForeground(1, QBrush(QColor(accent)))
                item.setToolTip(
                    0,
                    f"{info.get('title', network_key)}\nFactory component: {component}\n"
                    f"Connector: {connector}\n{notes}"
                )
                branch.addChild(item)

        self.map_tree.expandAll()
        self.map_tree.resizeColumnToContents(1)
        self.map_tree.resizeColumnToContents(2)

    def _map_selection_changed(self):
        item = self.map_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        fixture_code = data.get("fixture_code")
        if fixture_code:
            self.select_module(fixture_code)
            return

        network_key = data.get("network")
        info = L319_WIRING_NETWORKS.get(network_key, {})
        self.selected_code = None
        self.detail_name.setText(f"{data.get('code')}  |  {data.get('name')}")
        self.detail_status.setText("FACTORY REFERENCE ONLY  •  NOT IN SIMULATOR INVENTORY")
        self.detail_status.setStyleSheet("color:#8995a3;font-weight:700;")
        self.detail_text.setPlainText(
            f"FACTORY COMPONENT: {data.get('component')}\n"
            f"NETWORK: {info.get('title', network_key)}\n"
            f"REFERENCE: {info.get('pages', '')}\n\n"
            f"CONNECTOR / PIN REFERENCES\n{data.get('connector', '')}\n\n"
            f"NOTES\n{data.get('notes', '')}\n\n"
            f"NETWORK CONDUCTORS\n{info.get('pair', '')}\n\n"
            f"DIAGNOSTIC SOCKET\n{info.get('dlc', '')}\n\n"
            "DATA SOURCE: TRANSCRIBED 2010 L319 FACTORY WIRING REFERENCE.\n"
            "LIVE ECU PRESENCE AND SCAN STATUS HAVE NOT BEEN VERIFIED."
        )
        self.scan_selected_button.setEnabled(False)

    def _build_system_list(self):
        self.system_list.clear()
        groups = {}
        for module in self.network.modules:
            group = groups.get(module.category)
            if group is None:
                group = QTreeWidgetItem([module.category, "", "", ""])
                self.system_list.addTopLevelItem(group)
                groups[module.category] = group
            item = QTreeWidgetItem([
                f"{module.code} — {module.name}",
                self._status_text(module),
                str(len(module.dtcs)),
                module.last_scan or "—",
            ])
            item.setData(0, Qt.UserRole, module.code)
            group.addChild(item)
            accent = self.STATUS_STYLES[self._module_status(module)][0]
            for col in (0, 1):
                item.setForeground(col, QBrush(QColor(accent)))
        self.system_list.expandAll()
        self.system_list.resizeColumnToContents(1)
        self.system_list.resizeColumnToContents(2)
        self.system_list.resizeColumnToContents(3)

    def refresh(self):
        self._building = True
        try:
            modules = list(self.network.modules)
            scanned = [m for m in modules if m.last_scan is not None]
            faults = [m for m in modules if m.last_scan is not None and m.dtcs]
            self.summary_cards["total"].setText(str(len(modules)))
            self.summary_cards["scanned"].setText(str(len(scanned)))
            self.summary_cards["faults"].setText(str(len(faults)))
            self.summary_cards["unscanned"].setText(str(sum(m.last_scan is None for m in modules)))
            vin = self.vin_provider() or "NO VIN SELECTED"
            self.heading.setText(
                f"VIN: {vin}  •  {len(modules)} inventory entries  •  "
                "SIMULATED DATA / PHYSICAL ECU NETWORK NOT VERIFIED"
            )
            self._build_map()
            self._build_system_list()
        finally:
            self._building = False

        if self.selected_code and any(m.code == self.selected_code for m in modules):
            self.select_module(self.selected_code)
        elif modules:
            self.select_module(modules[0].code)
        else:
            self._show_empty_selection()

    def _show_empty_selection(self):
        self.selected_code = None
        self.detail_name.setText("No modules in inventory")
        self.detail_status.setText("No scan data")
        self.detail_text.clear()
        self.scan_selected_button.setEnabled(False)

    def select_module(self, code):
        try:
            module = self.network.get_module(code)
        except (KeyError, AttributeError):
            self._show_empty_selection()
            return
        self.selected_code = code
        for key, button in self.map_buttons.items():
            button.setChecked(key == code)
        for index in range(self.system_list.topLevelItemCount()):
            group = self.system_list.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.data(0, Qt.UserRole) == code:
                    self.system_list.setCurrentItem(child)
                    break

        status = self._status_text(module)
        accent = self.STATUS_STYLES[self._module_status(module)][0]
        self.detail_name.setText(f"{module.code}  |  {module.name}")
        self.detail_status.setText(f"{status}  •  {len(module.dtcs)} DTC(S)")
        self.detail_status.setStyleSheet(f"color:{accent};font-weight:700;")
        lines = [
            f"MODULE: {module.code}",
            f"SYSTEM GROUP: {module.category}",
            f"STATUS: {status}",
            f"LAST SCAN: {module.last_scan or 'Never'}",
            f"AVAILABILITY: {'Responding in simulator' if module.available else 'No response in simulator'}",
            "",
            "DIAGNOSTIC TROUBLE CODES",
        ]
        if module.dtcs:
            for dtc in module.dtcs:
                lines.extend([
                    f"{dtc.code}  |  {dtc.status}  |  {dtc.severity}",
                    dtc.description,
                    "",
                ])
        else:
            lines.append("No DTC entries in the current module fixture.")
        lines.extend([
            "",
            "DATA SOURCE: SIMULATED MODULE FIXTURE",
            "ECU ADDRESS: NOT VERIFIED",
            "PHYSICAL BUS / ROUTE: NOT VERIFIED",
        ])
        self.detail_text.setPlainText("\n".join(lines))
        self.scan_selected_button.setEnabled(bool(module.available))

    def _list_selection_changed(self):
        if self._building:
            return
        item = self.system_list.currentItem()
        code = item.data(0, Qt.UserRole) if item else None
        if code:
            self.select_module(code)

    def _open_module_details(self, item, column):
        code = item.data(0, Qt.UserRole)
        if code:
            self.select_module(code)

    def scan_selected(self):
        if not self.selected_code:
            return
        module = self.network.scan_module(self.selected_code)
        self.history_callback(
            "topology_module_scan",
            f"Topology module scan: {module.code}",
            {"module": module.code, "source": "simulated_module_network",
             "dtcs": [dtc.code for dtc in module.dtcs]},
            vin=self.vin_provider(),
        )
        self.refresh()
        self.select_module(module.code)

    def scan_all(self):
        modules = self.network.scan_all()
        self.history_callback(
            "topology_full_scan",
            "Topology full inventory scan",
            {"source": "simulated_module_network",
             "modules_scanned": [module.code for module in modules],
             "dtcs": {module.code: [dtc.code for dtc in module.dtcs] for module in modules}},
            vin=self.vin_provider(),
        )
        self.refresh()



class WiringDiagramsTab(QWidget):
    """Factory-reference L319 network explorer and optional local PDF viewer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_document = None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        heading = QLabel("LAND ROVER DISCOVERY 4 / LR4  •  FACTORY WIRING REFERENCE")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            f"Default configuration: {L319_DEFAULT_ENGINE}  •  2010 model-year LHD reference. "
            "Factory network data is separate from simulated scan results and is not proof "
            "that a particular vehicle is equipped with every listed module."
        )
        intro.setWordWrap(True)
        intro.setObjectName("mutedText")
        root.addWidget(intro)

        self.pages = QTabWidget()
        root.addWidget(self.pages, 1)

        network_page = QWidget()
        network_layout = QVBoxLayout(network_page)
        network_layout.setContentsMargins(4, 6, 4, 4)
        top = QHBoxLayout()
        top.addWidget(QLabel("NETWORK:"))
        self.network_select = QComboBox()
        for key, info in L319_WIRING_NETWORKS.items():
            self.network_select.addItem(info["title"], key)
        self.network_select.currentIndexChanged.connect(self.refresh_network)
        top.addWidget(self.network_select, 1)
        network_layout.addLayout(top)

        self.network_summary = QLabel()
        self.network_summary.setWordWrap(True)
        self.network_summary.setObjectName("mutedText")
        network_layout.addWidget(self.network_summary)

        split = QHBoxLayout()
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Module", "Factory ID"])
        self.module_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.module_tree.setMinimumWidth(300)
        self.module_tree.itemSelectionChanged.connect(self.show_module)
        split.addWidget(self.module_tree, 2)

        detail_column = QVBoxLayout()
        detail_title = QLabel("WIRING / CONNECTOR DETAILS")
        detail_title.setObjectName("sectionTitle")
        detail_column.addWidget(detail_title)
        self.module_detail = QPlainTextEdit()
        self.module_detail.setReadOnly(True)
        self.module_detail.setPlaceholderText("Select a factory-listed module.")
        detail_column.addWidget(self.module_detail, 1)
        split.addLayout(detail_column, 3)
        network_layout.addLayout(split, 1)
        self.pages.addTab(network_page, "Network Reference")

        pdf_page = QWidget()
        pdf_layout = QVBoxLayout(pdf_page)
        pdf_controls = QHBoxLayout()
        load_pdf = QPushButton("Load Local Wiring PDF")
        load_pdf.clicked.connect(self.load_local_pdf)
        pdf_controls.addWidget(load_pdf)
        open_source = QPushButton("Open Online Reference")
        open_source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(L319_WIRING_SOURCE_URL)))
        pdf_controls.addWidget(open_source)
        pdf_controls.addStretch(1)
        pdf_layout.addLayout(pdf_controls)
        if HAS_PDF_VIEWER:
            self.pdf_view = QPdfView()
            self.pdf_document = QPdfDocument(self)
            self.pdf_view.setDocument(self.pdf_document)
            try:
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            except AttributeError:
                pass
            pdf_layout.addWidget(self.pdf_view, 1)
            pdf_note = QLabel("Load a PDF copy you are entitled to use. Scroll through pages; the network reference identifies the relevant factory page numbers.")
        else:
            self.pdf_view = None
            pdf_note = QLabel(
                "This build does not have the optional Qt PDF viewer installed. "
                "Load Local Wiring PDF will open your selected file in the system PDF reader. "
                "The factory network references remain available in the Network Reference tab."
            )
        pdf_note.setWordWrap(True)
        pdf_note.setObjectName("mutedText")
        pdf_layout.addWidget(pdf_note)
        self.pages.addTab(pdf_page, "Factory Diagram Viewer")

        self.refresh_network()

    def refresh_network(self, *_):
        key = self.network_select.currentData()
        info = L319_WIRING_NETWORKS.get(key)
        self.module_tree.clear()
        self.module_detail.clear()
        if not info:
            return
        self.network_summary.setText(
            f"{info['description']}\n{info['pages']}\n{info['pair']}\n"
            f"Diagnostic socket: {info['dlc']}"
        )
        for code, component, name, connector, notes in info["modules"]:
            item = QTreeWidgetItem([f"{code}  •  {name}", component])
            item.setData(0, Qt.UserRole, (code, component, name, connector, notes, key))
            self.module_tree.addTopLevelItem(item)
        if self.module_tree.topLevelItemCount():
            self.module_tree.setCurrentItem(self.module_tree.topLevelItem(0))

    def show_module(self):
        item = self.module_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            self.module_detail.clear()
            return
        code, component, name, connector, notes, key = data
        info = L319_WIRING_NETWORKS[key]
        self.module_detail.setPlainText(
            f"MODULE: {name}\nSHORT NAME: {code}\nFACTORY COMPONENT ID: {component}\n"
            f"NETWORK: {info['title']}\nREFERENCE: {info['pages']}\n\n"
            f"CONNECTOR / PIN REFERENCES\n{connector}\n\n"
            f"NOTES\n{notes}\n\n"
            f"NETWORK CONDUCTORS\n{info['pair']}\n\n"
            f"DIAGNOSTIC SOCKET\n{info['dlc']}\n\n"
            "DATA STATUS: TRANSCRIBED FACTORY REFERENCE. NOT LIVE VEHICLE DETECTION. "
            "Confirm model year, VIN, market, equipment and connector view before probing."
        )

    def load_local_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Land Rover wiring diagram PDF", "", "PDF files (*.pdf)"
        )
        if not path:
            return
        if HAS_PDF_VIEWER:
            status = self.pdf_document.load(path)
            if status != QPdfDocument.Status.Ready:
                QMessageBox.warning(self, "PDF load failed", f"Qt could not load this PDF. Status: {status}")
                return
            self.pages.setCurrentIndex(1)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


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
        self.dtc_only_filter = QCheckBox("DTC scans only")
        self.dtc_only_filter.toggled.connect(self.refresh_events)
        controls.addWidget(self.dtc_only_filter)
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
        if self.dtc_only_filter.isChecked():
            events = filter_dtc_scan_events(events)
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
        if not event:
            self.details.clear()
        elif event.get("type") in {"dtc_scan_completed", "dtc_scan_failed"}:
            self.details.setPlainText(format_dtc_scan_event(event))
        else:
            self.details.setPlainText(json.dumps(event, indent=2, ensure_ascii=False))



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


class SpecialFunctionsTab(QWidget):
    """Service-routine catalog with guarded preflight and VIN-linked audit history."""
    ROUTINES = [
        ("Service & Maintenance", "Instrument cluster / service system", "Service interval reset",
         "Reset the oil-service or scheduled-maintenance reminder after the required maintenance has been completed.",
         "Correct service procedure completed; vehicle configuration and reset method verified."),
        ("Service & Maintenance", "Battery / body electrical system", "Battery registration or adaptation",
         "Register a replacement battery where the vehicle requires battery monitoring adaptation.",
         "Battery specification and monitoring-system support verified for the exact vehicle."),
        ("Service & Maintenance", "Brake system", "Brake pad replacement service mode",
         "Retract or release the electronic parking-brake mechanism for rear brake service, where supported.",
         "Vehicle safely secured; correct axle and actuator procedure confirmed."),
        ("Air Suspension", "Air suspension control module", "Ride-height calibration",
         "Calibrate commanded suspension heights against measured reference points.",
         "Level measuring surface, correct tire pressures, ride-height measurements and vehicle-specific values."),
        ("Air Suspension", "Air suspension control module", "Compressor activation test",
         "Run a controlled compressor and valve-block functional test.",
         "Leak check, pressure limits and compressor thermal limits verified."),
        ("Air Suspension", "Air suspension control module", "Suspension mode / transport-mode control",
         "Inspect or change supported suspension operating modes for service or transport.",
         "Exact mode support and safe vehicle state verified."),
        ("Brakes & ABS", "ABS / stability control module", "ABS hydraulic unit bleeding",
         "Guide a supported automated bleed procedure for the ABS hydraulic unit after brake-system work.",
         "Correct pressure bleeder setup, fluid specification and manufacturer bleed sequence."),
        ("Brakes & ABS", "ABS / stability control module", "Brake pressure sensor calibration",
         "Calibrate supported brake-pressure sensing after relevant component replacement.",
         "No active hydraulic faults; sensor and calibration conditions verified."),
        ("Parking Brake", "Electronic parking-brake module", "Parking brake service mode",
         "Move supported parking-brake actuators into a service position for brake work.",
         "Vehicle secured against movement; actuator and service procedure verified."),
        ("Parking Brake", "Electronic parking-brake module", "Parking brake actuator calibration",
         "Run the supported actuator initialization or calibration after service.",
         "Mechanical installation checked and vehicle-specific calibration method verified."),
        ("Engine & Emissions", "Engine control module", "DPF regeneration",
         "Request a supported diesel particulate-filter regeneration when diagnostic conditions permit.",
         "Oil level, coolant temperature, fuel level, DPF loading and fire-safety conditions checked."),
        ("Engine & Emissions", "Engine control module", "Throttle adaptation",
         "Run a supported throttle-body or throttle-position adaptation after relevant repairs.",
         "No unresolved engine faults; exact engine and throttle procedure verified."),
        ("Engine & Emissions", "Engine control module", "EGR adaptation / relearn",
         "Run a supported EGR initialization or learned-value procedure after component service.",
         "Correct engine variant and required temperature / ignition conditions verified."),
        ("Transmission & Driveline", "Transmission control module", "Transmission adaptive values reset",
         "Reset supported learned transmission values when the repair procedure specifically calls for it.",
         "Repair completed; correct transmission variant and post-reset drive cycle known."),
        ("Transmission & Driveline", "Transfer case control module", "Transfer case calibration",
         "Run supported transfer-case calibration or initialization after relevant repairs.",
         "Driveline configuration and exact calibration prerequisites verified."),
        ("Steering & Chassis", "Steering / ABS modules", "Steering-angle sensor calibration",
         "Calibrate the steering-angle reference after alignment or steering-system work.",
         "Wheels straight, alignment verified and vehicle on a suitable level surface."),
        ("Body & Electrical", "Body control module", "Window regulator initialization",
         "Relearn supported one-touch window limits after battery disconnection or regulator replacement.",
         "Correct window and anti-trap initialization procedure verified."),
        ("Body & Electrical", "Lighting control module", "Headlamp leveling calibration",
         "Calibrate supported automatic headlamp leveling after sensor or suspension work.",
         "Vehicle load and ride height set to the specified calibration condition."),
    ]

    def __init__(self, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.routine_manager = ServiceRoutineManager()
        self.current_routine = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            "<b>Service routines and module-specific procedures</b><br>"
            "Candidate procedures for the Discovery 4 / LR4 (L319) project. "
            "Compatibility and live command support are not yet verified. "
            "Preflight checks are read-only and do not transmit ECU commands."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("SYSTEM:"))
        self.category_filter = QComboBox()
        self.category_filter.addItem("All systems")
        for category in sorted({item[0] for item in self.ROUTINES}):
            self.category_filter.addItem(category)
        self.category_filter.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.category_filter, 1)
        self.vehicle_label = QLabel("NO VEHICLE SELECTED")
        filter_row.addWidget(self.vehicle_label)
        layout.addLayout(filter_row)

        split = QHBoxLayout()
        self.routine_tree = QTreeWidget()
        self.routine_tree.setHeaderLabels(["Routine", "Module / system", "Status"])
        self.routine_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.routine_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.routine_tree.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.routine_tree, 3)

        details_panel = QVBoxLayout()
        details_panel.addWidget(QLabel("ROUTINE DETAILS"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a routine to inspect its purpose and prerequisites.")
        details_panel.addWidget(self.details, 1)

        self.preflight_button = QPushButton("Run Readiness Check")
        self.preflight_button.setEnabled(False)
        self.preflight_button.setToolTip("Checks available vehicle context and reports missing implementation requirements. Sends no ECU commands.")
        self.preflight_button.clicked.connect(self.run_preflight)
        details_panel.addWidget(self.preflight_button)

        self.execution_note = QLabel(
            "LIVE EXECUTION LOCKED  •  NO ECU COMMANDS SENT"
        )
        self.execution_note.setWordWrap(True)
        details_panel.addWidget(self.execution_note)
        split.addLayout(details_panel, 2)
        layout.addLayout(split, 1)
        self.refresh()

    @staticmethod
    def _routine_id(category, name):
        return f"{category.strip().lower()}::{name.strip().lower()}"

    def _selected_routine(self):
        item = self.routine_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return None
        category, module, name, description, prerequisites = data
        return ServiceRoutine(
            routine_id=self._routine_id(category, name),
            category=category,
            target_module=module,
            name=name,
            description=description,
            prerequisites=prerequisites,
        )

    def refresh(self, *_):
        vin = self.vin_provider()
        self.vehicle_label.setText(vin or "NO VEHICLE SELECTED")
        selected_category = self.category_filter.currentText()
        self.routine_tree.clear()
        groups = {}
        for category, module, name, description, prerequisites in self.ROUTINES:
            if selected_category != "All systems" and category != selected_category:
                continue
            group = groups.get(category)
            if group is None:
                group = QTreeWidgetItem([category, "", ""])
                self.routine_tree.addTopLevelItem(group)
                groups[category] = group
            item = QTreeWidgetItem([name, module, "CATALOG ONLY"])
            item.setData(0, Qt.UserRole, (category, module, name, description, prerequisites))
            group.addChild(item)
        self.routine_tree.expandAll()
        if self.routine_tree.topLevelItemCount():
            first = self.routine_tree.topLevelItem(0)
            if first.childCount():
                self.routine_tree.setCurrentItem(first.child(0))
        else:
            self.current_routine = None
            self.details.clear()
            self.preflight_button.setEnabled(False)

    def show_selected(self):
        routine = self._selected_routine()
        self.current_routine = routine
        if routine is None:
            self.details.clear()
            self.preflight_button.setEnabled(False)
            return
        vin = self.vin_provider() or "Not selected"
        self.preflight_button.setEnabled(True)
        self.details.setPlainText(
            f"ROUTINE: {routine.name}\n"
            f"SYSTEM: {routine.category}\n"
            f"TARGET MODULE: {routine.target_module}\n"
            f"CURRENT VIN: {vin}\n"
            "SUPPORT STATUS: CATALOG ONLY\n\n"
            f"PURPOSE\n{routine.description}\n\n"
            f"PREREQUISITES TO VERIFY\n{routine.prerequisites}\n\n"
            "READINESS REQUIREMENTS\n"
            "• Exact vehicle and module compatibility verified\n"
            "• Module addressing and diagnostic protocol verified\n"
            "• Security-access requirements documented, if applicable\n"
            "• Manufacturer procedure and safety conditions verified\n"
            "• A reviewed routine executor implemented\n\n"
            "The readiness check below reports missing requirements. It does not send commands."
        )
        self.execution_note.setText("LIVE EXECUTION LOCKED  •  NO ECU COMMANDS SENT")

    def run_preflight(self):
        routine = self.current_routine or self._selected_routine()
        if routine is None:
            return
        vin = self.vin_provider()
        result = self.routine_manager.preflight(routine, vin=vin)
        status = "READY" if result.ready else "BLOCKED"
        self.execution_note.setText(
            f"{status}  •  READ-ONLY CHECK  •  NO ECU COMMANDS SENT"
        )
        blockers = "\n".join(f"• {item}" for item in result.blockers) or "No blockers reported."
        self.details.appendPlainText(
            f"\n\nREADINESS RESULT: {status}\n{blockers}"
        )
        self.history_callback(
            "service_routine_preflight",
            f"Preflight {status.lower()}: {routine.name}",
            result.to_dict(),
            vin=vin,
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.vehicle_profiles = VehicleProfileRegistry()
        installed_fonts = {family.casefold(): family for family in QFontDatabase.families()}
        self.body_font_family = next(
            (installed_fonts[name.casefold()] for name in ("Inter", "Segoe UI Variable", "Segoe UI")
             if name.casefold() in installed_fonts),
            "Segoe UI",
        )
        self.heading_font_family = next(
            (installed_fonts[name.casefold()] for name in (
                "Gill Sans MT", "Gill Sans", "Trebuchet MS",
                "Inter Tight", "Inter", "Segoe UI Variable", "Segoe UI"
            ) if name.casefold() in installed_fonts),
            self.body_font_family,
        )
        self.session = CaptureSession()
        self.can_monitor = CanMonitor(capacity=20000)
        self.sensor_capture = SensorCapture()
        self.obd_scaling_context = Mode01ScalingContext()
        self.history_store = VehicleHistoryStore(SETTINGS_DIR / "vehicle_history.json")
        self.receiver = None
        self.active_adapter = None
        self._last_receiver_diagnostics = {}
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

        self.setWindowTitle("FreeRov3r | Vehicle Diagnostics")
        self.setWindowIcon(QIcon(str(ASSET_DIR / "brand_badge.svg")))
        self.setMinimumSize(800, 600)
        self.resize(1180, 760)

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

        # Reuse the exact photographic banner shown by the startup splash.
        self.welcome_banner = ResponsiveBanner()
        self.welcome_banner.set_source_pixmap(
            load_asset_pixmap("brand_banner.svg")
        )
        wlayout.addWidget(self.welcome_banner)

        title = QLabel("What would you like to do?")
        title_font = QFont(self.heading_font_family, 25, QFont.Bold)
        title_font.setItalic(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(title)

        subtitle = QLabel("Land Rover L319 workspaces are available by default. A VIN decode identifying another vehicle switches to generic OBD-II/CAN support.")
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
            ("Run Module Health Report", self.open_health_report),
            ("Vehicle setup wizard", self.run_setup_wizard),
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
        self.graph_tab.parent_settings = self.settings
        self.graph_tab.refresh_favorite_groups()
        self.tabs.addTab(self.graph_tab, "Graph")
        self.obd_tab = OBDTab(self.settings)
        self.obd_tab.read_dtcs_callback = self.request_dtc_scan
        self.graph_tab.selection_changed_callback = self.obd_tab.set_selected_sensor_ids
        self.obd_tab.selection_changed_callback = self.graph_tab.set_selected_sensor_ids
        self.graph_tab.navigate_to_obd_callback = lambda: self.tabs.setCurrentWidget(self.obd_tab)
        self.obd_tab.navigate_to_graph_callback = lambda: self.tabs.setCurrentWidget(self.graph_tab)
        self.graph_tab.favorites_changed_callback = self.obd_tab._refresh_favorite_combo
        self.obd_tab.favorites_changed_callback = self.graph_tab.refresh_favorite_groups
        self.graph_tab.set_selected_sensor_ids(self.obd_tab.selected_sensor_ids())
        self.tabs.addTab(self.obd_tab, "OBD-II")
        self.module_networks = {}
        self.module_network = SimulatedModuleNetwork()
        self.modules_tab = ModulesTab(
            self.module_network,
            vin_provider=lambda: self.settings.get("current_vin"),
            history_callback=self.record_vehicle_event,
        )
        self.tabs.addTab(self.modules_tab, "Modules")
        self.special_functions_tab = SpecialFunctionsTab(
            vin_provider=lambda: self.settings.get("current_vin"),
            history_callback=self.record_vehicle_event,
        )
        self.tabs.addTab(self.special_functions_tab, "Special Functions")
        self.network_tab = NetworkOverviewTab(
            self.module_network,
            vin_provider=lambda: self.settings.get("current_vin"),
            history_callback=self.record_vehicle_event,
        )
        self.tabs.addTab(self.network_tab, "Topology")
        self.wiring_tab = WiringDiagramsTab()
        self.tabs.addTab(self.wiring_tab, "Wiring Diagrams")
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
        self.research_tab = ResearchTab()
        self.tabs.addTab(self.research_tab, "Research")
        self.tuning_tab = TuningTab(
            vin_provider=lambda: self.settings.get("current_vin")
        )
        self.tabs.addTab(self.tuning_tab, "Tuning")
        self._build_settings_tab()
        self._build_navigation_workspace()
        for group_box in self.findChildren(QGroupBox):
            group_box.setTitle(group_box.title().upper())
        self.quick_drawer = QuickDrawer(self, self._navigate_to_tab)
        self.addDockWidget(Qt.RightDockWidgetArea, self.quick_drawer)
        self.resizeDocks([self.quick_drawer], [290], Qt.Horizontal)
        self.quick_drawer.setMinimumWidth(240)
        self.quick_drawer.setMaximumWidth(320)
        self.quick_drawer.show()
        self.quick_drawer.set_current_workspace(self.tabs.tabText(self.tabs.currentIndex()))
        self.toast_manager = ToastManager(self)

    def _build_navigation_workspace(self):
        """Build a readable icon-tile rail instead of rotated QTabWidget labels."""
        self.tabs.tabBar().hide()
        workspace = QWidget()
        outer_layout = QVBoxLayout(workspace)
        outer_layout.setContentsMargins(7, 6, 7, 7)
        outer_layout.setSpacing(6)

        # Persistent instrument header: the key context stays visible on every page.
        header = QWidget()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(10)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.workspace_title = QLabel("Capture")
        self.workspace_title.setObjectName("workspaceTitle")
        workspace_title_font = QFont(self.heading_font_family, 20, QFont.Bold)
        workspace_title_font.setItalic(True)
        self.workspace_title.setFont(workspace_title_font)
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
        self.drawer_button.setText("☷  QUICK PANEL")
        self.drawer_button.setToolTip("Open vehicle context and workspace shortcuts")
        self.drawer_button.clicked.connect(self.toggle_quick_drawer)
        header_layout.addWidget(self.drawer_button)

        outer_layout.addWidget(header)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        content_row.addWidget(self.tabs, 1)
        outer_layout.addLayout(content_row, 1)
        # Keep all workspace controls reachable on short or narrow displays.
        workspace.setMinimumSize(0, 0)
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.NoFrame)
        self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.workspace_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.workspace_scroll.setWidget(workspace)
        self.stack.addWidget(self.workspace_scroll)
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
                "Special Functions": "Service resets, calibrations and module-specific routines",
                "Topology": "Interactive ECU module map, scan status and DTC overview",
                "Wiring Diagrams": "Factory-documented L319 HS-CAN, MS-CAN and MOST wiring reference",
                "Solutions": "Review diagnostic evidence and analysis notes",
                "Vehicle History": "Previous captures and vehicle-specific events",
                "Research": "Private protocol capture, comparison, annotation and REA handoff",
                "Settings": "Connection, display and logging configuration",
            }
            self.workspace_subtitle.setText(descriptions.get(title, "Vehicle diagnostics workspace"))
            if hasattr(self, "quick_drawer"):
                self.quick_drawer.set_current_workspace(title)
        self._refresh_workspace_header()

    def toggle_quick_drawer(self):
        if hasattr(self, "quick_drawer"):
            self.quick_drawer.setVisible(not self.quick_drawer.isVisible())

    def open_health_report(self):
        """Open module diagnostics and immediately run the health-report workflow."""
        self._navigate_to_tab("Modules")
        self.modules_tab.generate_health_report()

    def run_setup_wizard(self):
        """Guide interface selection and vehicle-profile setup."""
        wizard = VehicleSetupWizard(self, self.settings)
        if wizard.exec() != QDialog.Accepted or not wizard.result_data:
            return
        data = wizard.result_data
        self.settings.update({
            "interface": data["interface"], "channel": data["channel"],
            "bitrate": data["bitrate"],
        })
        for combo in (self.backend, self.settings_backend):
            for index in range(combo.count()):
                item_data = combo.itemData(index)
                if item_data and item_data[0] == data["interface"]:
                    combo.setCurrentIndex(index)
                    break
        self.channel_edit.setCurrentText(data["channel"])
        self.settings_channel.setText(data["channel"])
        self.bitrate.setCurrentText(str(data["bitrate"]))
        self.settings_bitrate.setCurrentText(str(data["bitrate"]))
        vehicle = {
            "make": data["make"], "model": data["model"],
            "model_year": data["model_year"], "profile_id": data["profile_id"],
            "identification_confidence": data["identification"].get("confidence", "manual"),
            "variant_id": data["identification"].get("variant_id"),
            "profile_selection_explicit": True, "nickname": "",
        }
        vin = data["vin"]
        if vin:
            existing = self.settings.setdefault("vehicles", {}).get(vin, {})
            existing.update(vehicle)
            self.settings["vehicles"][vin] = existing
            self.settings["current_vin"] = vin
            self.settings["active_vehicle"] = existing.copy()
        else:
            self.settings["current_vin"] = None
            self.settings["active_vehicle"] = vehicle
        self._refresh_vehicle_list()
        self._update_vehicle_context()
        self.save_current_settings()
        self._navigate_to_tab("Capture")
        self.show_toast("Vehicle setup applied", "success")

    def _navigate_to_tab(self, name):
        if name == "Home":
            self.stack.setCurrentIndex(0)
            if hasattr(self, "quick_drawer"):
                self.quick_drawer.set_current_workspace("Home")
            return
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                if not self.tabs.isTabEnabled(index):
                    self.show_toast(
                        "This workspace is available for Land Rover L319 vehicles. A VIN decode identifying another vehicle selects generic support.",
                        "info",
                    )
                    return
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
        active = vehicles.get(vin, {}) if vin else self.settings.get("active_vehicle", {})
        nickname = active.get("nickname", "")
        model = active.get("model") or active.get("make", "")
        vehicle_text = (
            f"{nickname or model}  |  {vin}" if vin and (nickname or model)
            else (vin or model or "NO VEHICLE SELECTED")
        )
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
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        dialog_width = min(1100, max(640, available.width() - 40))
        dialog_height = min(660, max(480, available.height() - 40))
        dialog.setMinimumSize(min(640, dialog_width), min(480, dialog_height))
        dialog.resize(dialog_width, dialog_height)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        content_scroll = QScrollArea(dialog)
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        splash_banner = QLabel()
        splash_banner.setAlignment(Qt.AlignCenter)
        banner_height = min(210, max(110, int(dialog_height * 0.30)))
        splash_banner.setFixedHeight(banner_height)
        splash_banner.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )

        splash_source = load_asset_pixmap("brand_banner.svg")
        if not splash_source.isNull():
            banner_width = max(1, dialog_width - 64)
            scaled_banner = splash_source.scaled(
                banner_width, banner_height,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            crop_x = max(0, (scaled_banner.width() - banner_width) // 2)
            crop_y = max(0, (scaled_banner.height() - banner_height) // 2)
            splash_banner.setPixmap(
                scaled_banner.copy(crop_x, crop_y, banner_width, banner_height)
            )

        content_layout.addWidget(splash_banner)

        title = QLabel("What would you like to do?")
        title.setObjectName("splashTitle")
        splash_title_font = QFont(self.heading_font_family, 25, QFont.Bold)
        splash_title_font.setItalic(True)
        title.setFont(splash_title_font)
        content_layout.addWidget(title)
        subtitle = QLabel(
            "Start with a simple task. You can switch workspaces at any time "
            "using Quick Nav on the right."
        )
        subtitle.setObjectName("splashSubtitle")
        subtitle.setWordWrap(True)
        content_layout.addWidget(subtitle)
        grid = QGridLayout()
        grid.setSpacing(12)
        choices = [
            ("Connect to a vehicle", "Choose your adapter and passively monitor vehicle traffic.",
             "Open capture", lambda: self._navigate_to_tab("Capture")),
            ("Try the simulator", "Start a clearly labeled demo using synthetic vehicle data. No hardware required.",
             "Start demo", self._start_simulator_demo),
            ("Explore sample modules", "Browse example module categories and sample faults. These are test fixtures, not a real scan.",
             "View sample modules", lambda: self._navigate_to_tab("Modules")),
            ("Open the full workspace", "Go straight to the complete set of generic diagnostic, graphing and history tools.",
             "Open workspace", lambda: self._navigate_to_tab("Capture")),
             ("Vehicle setup wizard", "Detect an interface, read or enter a VIN, identify the vehicle and select its capability package.",
              "Start setup", self.run_setup_wizard),
        ]
        splash_columns = 2 if dialog_width < 900 else 3
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
            grid.addWidget(card, index // splash_columns, index % splash_columns)
        content_layout.addLayout(grid)
        content_scroll.setWidget(content_widget)
        layout.addWidget(content_scroll, 1)
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
        self.backend.addItem("ESP32 serial adapter (single CAN)", ("esp32", "COM3"))
        self.backend.addItem("ESP32 dual serial (two CAN buses)", ("esp32_dual", "COM3,COM4"))
        self.backend.addItem("ELM327 raw CAN monitor", ("elm327", ""))
        self.backend.addItem("ELM327 active OBD-II polling", ("elm327_obd", ""))
        self.backend.addItem("SocketCAN", ("socketcan", "can0"))
        self.backend.addItem("SLCAN", ("slcan", "COM3"))
        controls.addWidget(QLabel("Connection:"))
        controls.addWidget(self.backend)

        self.channel_edit = QComboBox()
        self.channel_edit.setEditable(True)
        self.channel_edit.setInsertPolicy(QComboBox.NoInsert)
        self.channel_edit.setPlaceholderText("COM port or CAN channel")
        self.channel_edit.setToolTip(
            "Choose a detected serial port for ESP32/SLCAN, or type a CAN channel such as can0. "
            "For dual ESP32 capture, enter two different COM ports separated by a comma; "
            "first is HS-CAN, second is MS-CAN."
        )
        controls.addWidget(self.channel_edit)

        refresh_ports_btn = QPushButton("Detect interfaces")
        refresh_ports_btn.setToolTip(
            "List USB and paired Bluetooth serial adapters without opening or probing them."
        )
        refresh_ports_btn.clicked.connect(self.refresh_serial_ports)
        controls.addWidget(refresh_ports_btn)

        self.bitrate = QComboBox()
        self.bitrate.addItems(["125000", "250000", "500000", "1000000"])
        controls.addWidget(QLabel("Bitrate:"))
        controls.addWidget(self.bitrate)
        layout.addLayout(controls)

        hardware_notice = QLabel(
            "ⓘ  Full diagnostic functionality requires the recommended ESP32 CAN interface. "
            "ELM327 Bluetooth/Wi-Fi and other adapters may provide limited access and may not "
            "support complete CAN monitoring, all vehicle modules, or advanced diagnostic functions."
        )
        hardware_notice.setObjectName("hardwareCompatibilityNotice")
        hardware_notice.setWordWrap(True)
        hardware_notice.setToolTip(
            "The ESP32 CAN interface is the recommended hardware for full FreeRov3r functionality."
        )
        layout.addWidget(hardware_notice)

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
        """Inventory serial interfaces and select only a single clear candidate."""
        current = self.channel_edit.currentText().strip()
        ports = discover_interfaces()
        self.channel_edit.blockSignals(True)
        self.channel_edit.clear()
        for port in ports:
            self.channel_edit.addItem(port["device"], port["device"])
            index = self.channel_edit.count() - 1
            self.channel_edit.setItemData(
                index,
                f'{port["label"]} | {port["description"]} | '
                f'VID:PID {port["vid"] or "----"}:{port["pid"] or "----"}',
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

        # Only auto-select when exactly one recognized adapter candidate exists.
        recognized = [port for port in ports if port["kind"] in ("esp32", "elm327", "slcan")]
        if len(recognized) == 1:
            candidate = recognized[0]
            for index in range(self.backend.count()):
                data = self.backend.itemData(index)
                if data and data[0] == candidate["kind"]:
                    self.backend.setCurrentIndex(index)
                    self.channel_edit.setCurrentText(candidate["device"])
                    break

        if ports:
            summary = ", ".join(
                f'{port["device"]}: {port["label"]}' for port in ports
            )
            self.status.setText("Interface inventory: " + summary)
        else:
            self.status.setText(
                "No USB/Bluetooth serial interfaces found. CAN channels can still be entered manually."
            )

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
        self.settings_backend.addItem("ESP32 serial adapter (single CAN)", ("esp32", "COM3"))
        self.settings_backend.addItem("ESP32 dual serial (two CAN buses)", ("esp32_dual", "COM3,COM4"))
        self.settings_backend.addItem("ELM327 raw CAN monitor", ("elm327", ""))
        self.settings_backend.addItem("ELM327 active OBD-II polling", ("elm327_obd", ""))
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

        compatibility_group = QGroupBox("Hardware compatibility")
        compatibility_layout = QVBoxLayout(compatibility_group)
        compatibility_notice = QLabel(
            "Full diagnostic functionality is available only with the recommended ESP32 CAN interface. "
            "Bluetooth ELM327, Wi-Fi, and other third-party adapters are supported on a limited basis "
            "where their hardware and protocols allow. They may not provide complete CAN traffic, "
            "full module coverage, or advanced diagnostic functions."
        )
        compatibility_notice.setObjectName("hardwareCompatibilityNotice")
        compatibility_notice.setWordWrap(True)
        compatibility_layout.addWidget(compatibility_notice)
        preferred_hardware = QLabel("Preferred interface: ESP32 CAN adapter")
        preferred_hardware.setObjectName("preferredHardwareLabel")
        compatibility_layout.addWidget(preferred_hardware)
        layout.addWidget(compatibility_group)

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

        about_group = QGroupBox("About")
        about_layout = QVBoxLayout(about_group)
        about_btn = QPushButton("About FreeRov3r")
        about_btn.setToolTip("Software information and project attribution")
        about_btn.clicked.connect(self.show_about_dialog)
        about_layout.addWidget(about_btn)
        layout.addWidget(about_group)

        layout.addStretch()
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self.save_current_settings)
        layout.addWidget(save_btn)

        self.tabs.addTab(tab, "Settings")

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About FreeRov3r")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)

        title = QLabel("FreeRov3r")
        title.setObjectName("aboutTitle")
        about_title_font = QFont(self.heading_font_family, 22, QFont.Bold)
        about_title_font.setItalic(True)
        title.setFont(about_title_font)
        layout.addWidget(title)

        description = QLabel(
            "Open-source vehicle diagnostics, CAN monitoring, sensor capture, "
            "and analysis tools. Built for hands-on vehicle research."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        credit = QLabel(
            '<b>Built with AI by Shookone</b><br>'
            '<a href="https://x.com/shookone16">x.com/shookone16</a>'
        )
        credit.setOpenExternalLinks(True)
        credit.setTextFormat(Qt.RichText)
        credit.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(credit)

        support_btn = QPushButton("☕  Buy Me a Coffee")
        support_btn.setObjectName("supportButton")
        support_btn.setToolTip("Support FreeRov3r development")
        support_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.buymeacoffee.com/lazygoy"))
        )
        layout.addWidget(support_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

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
            model = info.get("model", "")
            label = nick or model
            self.vehicle_list.addItem(f"{vin}  —  {label}" if label else vin)
        current = self.settings.get("current_vin")
        if current and current in vehicles:
            nick = vehicles[current].get("nickname", "")
            self.current_vehicle_label.setText(f"Current: {current} ({nick})" if nick else f"Current: {current}")
        else:
            self.current_vehicle_label.setText("No vehicle selected")

    def add_or_update_vehicle(self):
        vin = self.vin_edit.text().strip().upper()
        nickname = self.nickname_edit.text().strip()
        if not validate_vin(vin):
            QMessageBox.warning(self, "Invalid VIN", "Enter a valid 17-character VIN (letters I, O and Q are not used).")
            return
        identification = identify_vehicle(vin)
        vehicle = self.settings.setdefault("vehicles", {}).get(vin, {}).copy()
        vehicle.update({
            "nickname": nickname,
            "make": identification.get("make") or vehicle.get("make", ""),
            "model": identification.get("model") or vehicle.get("model", ""),
            "model_year": identification.get("model_year") or vehicle.get("model_year"),
            "profile_id": identification.get("profile_id", "generic"),
            "variant_id": identification.get("variant_id"),
            "identification_confidence": identification.get("confidence", "unknown"),
        })
        self.settings["vehicles"][vin] = vehicle
        self.settings["current_vin"] = vin
        self.settings["active_vehicle"] = vehicle.copy()
        self.research_tab.set_context(vin, self.active_interface)
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
        self.settings["active_vehicle"] = self.settings.get("vehicles", {}).get(vin, {}).copy()
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
        active = vehicles.get(vin, {}) if vin and vin in vehicles else self.settings.get("active_vehicle", {})
        active = dict(active or {})
        if vin and not active.get("profile_id"):
            identification = identify_vehicle(vin)
            active.update({
                "make": identification.get("make") or active.get("make", ""),
                "model": identification.get("model") or active.get("model", ""),
                "model_year": identification.get("model_year") or active.get("model_year"),
                "profile_id": identification.get("profile_id", "generic"),
                "variant_id": identification.get("variant_id"),
                "identification_confidence": identification.get("confidence", "unknown"),
            })
            vehicles[vin] = active.copy()
        profile_id = active.get("profile_id", "generic")
        if profile_id == "generic" and not active.get("profile_selection_explicit"):
            make = str(active.get("make") or "").strip().lower()
            model = str(active.get("model") or "").strip().lower()
            year = active.get("model_year")
            if (not make and not model) or ("land rover" in make and not model):
                profile_id = "land_rover_l319"
            elif "land rover" in make and (
                "discovery" in model or "lr3" in model or "lr4" in model
            ):
                if "discovery 3" in model or "lr3" in model or (year and 2005 <= year <= 2009):
                    profile_id = "land_rover_l319_lr3"
                elif "discovery 4" in model or "lr4" in model or (year and 2010 <= year <= 2016):
                    profile_id = "land_rover_l319_lr4"
                else:
                    profile_id = "land_rover_l319"
            if profile_id != "generic":
                active["profile_id"] = profile_id
        self.active_vehicle_profile = self.vehicle_profiles.get(profile_id)
        self.sensor_capture.vehicle_context = {**active, "vin": vin}
        l319_enabled = profile_id in {
            "land_rover_l319", "land_rover_l319_lr3", "land_rover_l319_lr4"
        }
        l319_tabs = {"Special Functions", "Topology", "Wiring Diagrams"}
        for index in range(self.tabs.count()):
            tab_name = self.tabs.tabText(index)
            if tab_name in l319_tabs:
                self.tabs.setTabEnabled(index, l319_enabled)
                self.tabs.setTabToolTip(
                    index,
                    "" if l319_enabled else
                    "VIN identification indicates a vehicle outside the supported L319 family. Generic OBD-II/CAN tools remain available."
                )

        if vin and hasattr(self, "modules_tab"):
            network = self.module_networks.setdefault(vin, SimulatedModuleNetwork())
            self.modules_tab.set_network(network)
            if hasattr(self, "network_tab"):
                self.network_tab.set_network(network)
            if hasattr(self, "solutions_tab"):
                self.solutions_tab.set_network(network)

        if hasattr(self, "graph_tab"):
            self.graph_tab.set_vehicle_vin(vin)
        if hasattr(self, "special_functions_tab"):
            self.special_functions_tab.refresh()
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
        identification = identify_vehicle(vin)
        vehicle = self.settings.setdefault("vehicles", {}).get(vin, {})
        vehicle.update({
            "make": identification.get("make") or vehicle.get("make", ""),
            "model": identification.get("model") or vehicle.get("model", ""),
            "model_year": identification.get("model_year") or vehicle.get("model_year"),
            "profile_id": identification.get("profile_id", "generic"),
            "variant_id": identification.get("variant_id"),
            "identification_confidence": identification.get("confidence", "unknown"),
        })
        self.settings["vehicles"][vin] = vehicle
        self.settings["active_vehicle"] = vehicle.copy()
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
            self.obd_tab.set_dtc_scan_enabled(False)
            diagnostics = getattr(self.active_adapter, "diagnostics", None)
            if isinstance(diagnostics, dict):
                self._last_receiver_diagnostics = diagnostics
            elapsed = max(0.0, time.time() - (self.capture_started_at or time.time()))
            capture_samples = self.sensor_capture.samples_since(self.capture_start_sample_index)
            capture_samples_dropped = max(
                0,
                self.sensor_capture.total_samples_added
                - self.capture_start_sample_index
                - len(capture_samples),
            )
            capture_frames = self.session.frames[self.capture_start_frame_index:]
            archive_path = self.history_store.archive_capture(
                self.capture_vin,
                {
                    "interface": self.active_interface,
                    "started_at": self.capture_started_at,
                    "duration_seconds": round(elapsed, 2),
                    "sensor_samples_dropped_from_bounded_buffer": capture_samples_dropped,
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
                 "sensor_samples": len(capture_samples),
                 "sensor_samples_dropped_from_bounded_buffer": capture_samples_dropped,
                 "duration_seconds": round(elapsed, 2),
                 "archive_file": str(archive_path)},
                vin=self.capture_vin or "UNASSIGNED",
            )
            self.capture_started_at = None
            self.capture_vin = None
            self.receiver = None
            self.active_adapter = None
            self.research_tab.set_receiver_diagnostics(self._last_receiver_diagnostics)
            self.connect_btn.setText("Start listening")
            self.status.setText("Disconnected")
            self._refresh_workspace_header()
            self.show_toast("CAN capture stopped", "info")
            return

        data = self.backend.currentData()
        interface = data[0]
        channel = self.channel_edit.currentText().strip() or data[1]
        bitrate = int(self.bitrate.currentText())

        if interface == "elm327_obd" and not self.obd_tab.selected_pids():
            self.show_toast("Select at least one OBD-II PID to poll", "warning")
            return

        if interface == "simulator":
            adapter = SimulatedVehicleAdapter(channel=channel or "L319-DEMO")
        elif interface == "esp32":
            adapter = Esp32SerialAdapter(port=channel)
        elif interface == "esp32_dual":
            ports = [part.strip() for part in channel.split(",") if part.strip()]
            if len(ports) != 2 or ports[0].casefold() == ports[1].casefold():
                QMessageBox.warning(
                    self, "Dual ESP32 connection",
                    "Enter two different serial ports, for example COM4,COM5."
                )
                return
            adapter = Esp32DualSerialAdapter(ports, channel_names=("HS-CAN", "MS-CAN"))
        elif interface == "elm327":
            adapter = Elm327SerialAdapter(port=channel)
        elif interface == "elm327_obd":
            adapter = Elm327ObdAdapter(
                port=channel,
                pids=self.obd_tab.selected_pids(),
                request_interval=self.obd_tab.poll_interval_ms.value() / 1000.0,
            )
        else:
            adapter = PythonCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

        self.active_interface = interface
        self.obd_scaling_context.clear()
        self.active_adapter = adapter
        self._last_receiver_diagnostics = {}
        self.research_tab.set_receiver_diagnostics({})
        self.capture_vin = self.settings.get("current_vin")
        self.research_tab.set_context(self.capture_vin, interface)
        self.capture_started_at = time.time()
        self.capture_start_frames = 0
        self.capture_start_sample_index = self.sensor_capture.total_samples_added
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
        self.receiver.dtcs_completed.connect(self._on_dtc_scan_completed)
        self.receiver.dtcs_failed.connect(self._on_dtc_scan_failed)
        self.obd_tab.set_dtc_scan_enabled(interface == "elm327_obd")
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

    def request_dtc_scan(self):
        receiver = self.receiver
        if self.active_interface != "elm327_obd" or receiver is None:
            return False
        return receiver.request_dtcs()

    def _on_dtc_scan_completed(self, codes):
        self.obd_tab.show_dtc_results(codes)
        self.record_vehicle_event(
            "dtc_scan_completed",
            f"OBD-II DTC scan completed: {len(codes)} code record(s)",
            {
                "interface": self.active_interface,
                "services": ["03", "07", "0A"],
                "count": len(codes),
                "dtcs": codes,
                "read_only": True,
            },
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast(
            f"DTC scan complete: {len(codes)} code(s)",
            "success" if codes else "info",
        )

    def _on_dtc_scan_failed(self, message):
        self.obd_tab.set_dtc_scan_error(message)
        self.record_vehicle_event(
            "dtc_scan_failed",
            "OBD-II DTC scan failed",
            {"interface": self.active_interface, "error": str(message), "read_only": True},
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast("DTC scan failed", "warning")

    def on_frame(self, frame):
        detected_vin = self.vin_decoder.feed(frame.arbitration_id, bytes(frame.data))
        if detected_vin:
            self._apply_detected_vin(detected_vin)
        self.session.add(frame)
        self.can_monitor.add(frame)
        self.research_tab.observe_frame(frame)
        self.frame_counter += 1
        self.frame_count_label.setText(f"Frames: {self.frame_counter}")
        ts = frame.timestamp or 0
        if self.can_monitor.matches(frame, self.can_id_filter.text(), self.can_format_filter.currentText()):
            frame_type = "EXT" if frame.is_extended_id else "STD"
            self.log.appendPlainText(
                f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
                f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}"
            )
        measurements = decode_mode01_measurements(frame, self.obd_scaling_context)
        if measurements:
            simulated = self.active_interface == "simulator"
            display_values = []
            for pid, key, name, value, unit in measurements:
                sensor_id = f"obd_{pid:02X}" if key == "value" else f"obd_{pid:02X}_{key}"
                self.sensor_capture.add(SensorSample(
                    timestamp=ts or time.time(), sensor_id=sensor_id, name=name,
                    value=value, unit=unit, source="simulated" if simulated else "ecu",
                    ecu="SIMULATED ECU" if simulated else None,
                    signal=f"Mode 01 PID {pid:02X}" + (f" {key}" if key != "value" else ""),
                    metadata={"can_id": frame.arbitration_id, "raw": frame.data.hex(),
                             "vin": self.capture_vin or "UNASSIGNED"},
                ))
                self.graph_tab.mark_sample(sensor_id)
                known = any(
                    self.graph_tab._sensor_id(self.graph_tab.sensor_list.item(i)) == sensor_id
                    for i in range(self.graph_tab.sensor_list.count())
                )
                if not known:
                    self.graph_tab.refresh_sensor_list()
                display_values.append(f"{value:.2f} {unit}")
                self.sensor_log.appendPlainText(f"{name}: {value:.2f} {unit} [{sensor_id}]")
            self.obd_tab.update_value(measurements[0][0], " | ".join(display_values))

    def _update_receiver_health(self):
        """Publish live ESP32 adapter diagnostics to the Research workspace."""
        adapter = self.active_adapter
        diagnostics = getattr(adapter, "diagnostics", None) if adapter is not None else None
        if isinstance(diagnostics, dict):
            self._last_receiver_diagnostics = diagnostics
            self.research_tab.set_receiver_diagnostics(diagnostics)
        elif adapter is None:
            self.research_tab.set_receiver_diagnostics(self._last_receiver_diagnostics)
        else:
            self.research_tab.set_receiver_diagnostics({})

    def _update_rate(self):
        self._update_receiver_health()
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
            palette.setColor(QPalette.Highlight, QColor("#2c8054"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            app.setPalette(palette)
            self.setStyleSheet("""
                QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
                QMainWindow, QWidget { background: #171b22; color: #e7ebf0; }
                QWidget#workspaceHeader { background: #1b2a22; border: 1px solid #42684f; border-radius: 12px; }
                QLabel#brandBanner { background: #08140f; border: 1px solid #42684f; border-radius: 10px; padding: 2px; }
                QDockWidget#quickDrawer { background: #20242c; color: #e7ebf0; border-left: 1px solid #3a4655; }
                QDockWidget#quickDrawer::title { background: #20242c; padding: 10px 14px; font-weight: 700; }
                QWidget#drawerBody { background: #111d17; }
                QLabel#drawerBrandName { color: #f2f7f3; font-size: 16pt; font-weight: 850; letter-spacing: 0.5px; }
                QLabel#drawerBrandTagline { color: #8fb39a; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }
                QLabel#drawerBrandLogo { background: transparent; }
                QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
                QFrame#drawerCard { background: #252e39; border: 1px solid #3a4655; border-radius: 12px; }
                QLabel#drawerTitle { color: #f4f7fb; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#drawerSubtitle, QLabel#drawerCaption { color: #aeb9c6; font-size: 9pt; }
                QLabel#drawerValue { color: #f4f7fb; font-size: 10pt; font-weight: 700; }
                QLabel#drawerStatus { color: #82c5ff; font-weight: 700; }
                QLabel#drawerSection { color: #91a5bb; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
                QLabel#drawerNote { color: #9caaba; background: #202a36; border: 1px solid #34475b; border-radius: 9px; padding: 10px; font-size: 9pt; }
                QPushButton#drawerNavButton { text-align: left; background: #1b2c22; border: 1px solid #344e3b; border-radius: 8px; padding: 9px 12px; min-height: 22px; }
                QPushButton#drawerNavButton:hover { background: #294b35; border-color: #6da17a; }
                QPushButton#drawerNavButton:checked { background: #245a39; border: 1px solid #72b486; color: #ffffff; font-weight: 800; }
                QToolButton#drawerToggle { background: #214b32; color: #eef8f0; border: 1px solid #4c8c60; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
                QToolButton#drawerToggle:hover { background: #2d6843; }
                QFrame#toastNotification { background: #252e39; border: 1px solid #48617b; border-radius: 12px; }
                QFrame#toastNotification[kind="success"] { border-left: 4px solid #35b779; }
                QFrame#toastNotification[kind="warning"] { border-left: 4px solid #e5a93d; }
                QFrame#toastNotification[kind="error"] { border-left: 4px solid #e05d67; }
                QLabel#toastMarker { color: #8cc8ff; font-size: 15pt; font-weight: 800; }
                QLabel#toastText { color: #f2f6fa; font-size: 9pt; font-weight: 600; }
                QLabel#workspaceTitle { color: #ffffff; font-family: "{HEADING_FONT}"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
                QLabel#workspaceSubtitle { color: #aebdcb; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 500; }
                QLabel#headerVehicle { background: #303d4c; color: #f3f7fb; border: 1px solid #46586b; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 700; }
                QLabel#headerOffline { background: #343b45; color: #c4ccd5; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerOnline { background: #173e30; color: #83e0b2; border: 1px solid #286849; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerSimulation { background: #4a391b; color: #ffd27c; border: 1px solid #80602b; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerTraffic { color: #dce9f7; font-family: "{BODY_FONT}"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
                QWidget#navigationRail { background: #111720; border: 1px solid #2c3744; border-radius: 10px; }
                QWidget#navigationSeparator { background: #344252; max-height: 1px; }
                QToolButton { background: transparent; color: #aebdcb; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
                QToolButton:hover { background: #263342; color: #ffffff; border-color: #3b5269; }
                QToolButton:checked { background: #24496b; color: #ffffff; border: 1px solid #3989d8; }
                QGroupBox { border: 1px solid #303a47; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 600; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
                QLabel#modeBanner { background: #202a36; border: 1px solid #34475b; border-radius: 8px; padding: 14px 16px; color: #dce9f7; font-family: "{BODY_FONT}"; font-size: 11pt; font-weight: 600; }
                QLabel#welcomeSubtitle { color: #9eabb9; font-size: 11pt; }
                QPushButton { background: #283443; color: #eaf1f8; border: 1px solid #3a4b5e; border-radius: 7px; padding: 8px 14px; min-height: 24px; }
                QPushButton:hover { background: #34485e; border-color: #5486b8; }
                QPushButton:pressed { background: #1d5d9c; }
                QPushButton#taskButton { text-align: left; font-size: 11pt; font-weight: 600; padding: 16px 18px; background: #202a36; }
                QPushButton#taskButton:hover { background: #293b4e; }
                QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget, QSpinBox { background: #10141a; color: #e7ebf0; border: 1px solid #35404d; border-radius: 5px; padding: 5px; selection-background-color: #2c8054; }
                QComboBox QAbstractItemView { background: #202630; color: #e7ebf0; selection-background-color: #2675c9; }
                QTabWidget::pane { border: 1px solid #303a47; border-radius: 8px; background: #171b22; top: 0; }
                QTabBar::tab { background: #202630; color: #aeb9c6; border: 0; border-bottom: 1px solid #303a47; padding: 14px 12px; min-width: 118px; text-align: left; }
                QTabBar::tab:selected { background: #293b4e; color: #ffffff; border-left: 3px solid #3989d8; font-weight: 600; }
                QHeaderView::section { background: #252e39; color: #dce4ed; border: 0; border-bottom: 1px solid #3a4654; padding: 7px; }
                QCheckBox { spacing: 8px; }
                QDialog#startupSplash { background: #171b22; }
                QLabel#splashEyebrow { color: #78b9f2; font-size: 9pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#splashTitle { color: #f4f7fb; font-family: "{HEADING_FONT}"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
                QLabel#splashSubtitle { color: #aebdcb; font-size: 10pt; }
                QFrame#splashCard { background: #202a36; border: 1px solid #34475b; border-radius: 12px; }
                QLabel#splashCardTitle { color: #f4f7fb; font-size: 12pt; font-weight: 700; }
                QLabel#splashCardText { color: #aebdcb; font-size: 9pt; }
                QPushButton#splashAction, QPushButton#splashContinue { background: #245a39; border: 1px solid #72b486; font-weight: 700; }
                QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #2d7048; }
                QLabel#splashLogo { background: transparent; }
                QToolTip { background: #202630; color: #ffffff; border: 1px solid #526174; }
            """.replace("{BODY_FONT}", self.body_font_family).replace("{HEADING_FONT}", self.heading_font_family))
        else:
            palette = app.style().standardPalette()
            palette.setColor(QPalette.Highlight, QColor("#2c8054"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            app.setPalette(palette)
            self.setStyleSheet("""
                QWidget { font-family: "{BODY_FONT}"; font-size: 10pt; }
                QWidget#workspaceHeader { background: #edf5ef; border: 1px solid #b9d2c0; border-radius: 12px; }
                QLabel#brandBanner { background: #0a1710; border: 1px solid #8da996; border-radius: 10px; padding: 2px; }
                QDockWidget#quickDrawer { background: #f8fafc; color: #1e293b; border-left: 1px solid #d9e0e8; }
                QDockWidget#quickDrawer::title { background: #f1f5f9; padding: 10px 14px; font-weight: 700; }
                QWidget#drawerBody { background: #f0f6f1; }
                QLabel#drawerBrandName { color: #173323; font-size: 16pt; font-weight: 850; letter-spacing: 0.5px; }
                QLabel#drawerBrandTagline { color: #52745d; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }
                QLabel#drawerBrandLogo { background: transparent; }
                QLabel#drawerTitle, QLabel#drawerSubtitle, QLabel#drawerCaption, QLabel#drawerValue, QLabel#drawerStatus, QLabel#drawerSection, QLabel#drawerNote, QLabel#toastMarker, QLabel#toastText { background: transparent; }
                QFrame#drawerCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
                QLabel#drawerTitle { color: #172033; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
                QLabel#drawerSubtitle, QLabel#drawerCaption { color: #64748b; font-size: 9pt; }
                QLabel#drawerValue { color: #172033; font-size: 10pt; font-weight: 700; }
                QLabel#drawerStatus { color: #1769aa; font-weight: 700; }
                QLabel#drawerSection { color: #64748b; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 8px; }
                QLabel#drawerNote { color: #475569; background: #eff6ff; border: 1px solid #d5e5f6; border-radius: 9px; padding: 10px; font-size: 9pt; }
                QPushButton#drawerNavButton { text-align: left; background: #ffffff; border: 1px solid #d0dfd3; border-radius: 8px; padding: 9px 12px; min-height: 22px; color: #243449; }
                QPushButton#drawerNavButton:hover { background: #e7f3e9; border-color: #8bb797; }
                QPushButton#drawerNavButton:checked { background: #245a39; border: 1px solid #72b486; color: #ffffff; font-weight: 800; }
                QToolButton#drawerToggle { background: #e5f0e7; color: #1c5131; border: 1px solid #a7c9ae; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
                QToolButton#drawerToggle:hover { background: #d5e8d9; }
                QFrame#toastNotification { background: #ffffff; border: 1px solid #d3deea; border-radius: 12px; }
                QFrame#toastNotification[kind="success"] { border-left: 4px solid #219b64; }
                QFrame#toastNotification[kind="warning"] { border-left: 4px solid #d28a16; }
                QFrame#toastNotification[kind="error"] { border-left: 4px solid #d94853; }
                QLabel#toastMarker { color: #2675c9; font-size: 15pt; font-weight: 800; }
                QLabel#toastText { color: #243449; font-size: 9pt; font-weight: 600; }
                QLabel#workspaceTitle { color: #172033; font-family: "{HEADING_FONT}"; font-size: 20pt; font-weight: 850; letter-spacing: 1.2px; }
                QLabel#workspaceSubtitle { color: #596b7d; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 500; }
                QLabel#headerVehicle { background: #edf2f7; color: #24384c; border: 1px solid #cbd6e0; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 700; }
                QLabel#headerOffline { background: #eef0f2; color: #596675; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerOnline { background: #e1f4e9; color: #17633b; border: 1px solid #a6d7b8; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerSimulation { background: #fff1d6; color: #80520b; border: 1px solid #e6c98d; border-radius: 7px; padding: 9px 12px; font-family: "{BODY_FONT}"; font-size: 9.5pt; font-weight: 750; }
                QLabel#headerTraffic { color: #26394b; font-family: "{BODY_FONT}"; font-size: 10.5pt; font-weight: 700; padding: 4px 6px; }
                QWidget#navigationRail { background: #f1f4f7; border: 1px solid #d5dde5; border-radius: 10px; }
                QWidget#navigationSeparator { background: #d5dde5; max-height: 1px; }
                QToolButton { background: transparent; color: #526273; border: 1px solid transparent; border-radius: 8px; padding: 7px 2px; font-size: 9pt; font-weight: 600; }
                QToolButton:hover { background: #e2eaf2; color: #1f3448; border-color: #c4d1de; }
                QToolButton:checked { background: #dceaf7; color: #174b78; border: 1px solid #6a9dcc; }
                QLabel#modeBanner { background: #edf3f8; border: 1px solid #cbd7e2; border-radius: 8px; padding: 14px 16px; color: #26394b; font-family: "{BODY_FONT}"; font-size: 11pt; font-weight: 600; }
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
                QLabel#splashTitle { color: #172033; font-family: "{HEADING_FONT}"; font-size: 25pt; font-weight: 850; letter-spacing: -0.4px; }
                QLabel#splashSubtitle { color: #596b7d; font-size: 10pt; }
                QFrame#splashCard { background: #ffffff; border: 1px solid #d9e0e8; border-radius: 12px; }
                QLabel#splashCardTitle { color: #172033; font-size: 12pt; font-weight: 700; }
                QLabel#splashCardText { color: #596b7d; font-size: 9pt; }
                QPushButton#splashAction, QPushButton#splashContinue { background: #245a39; color: #ffffff; border: 1px solid #72b486; font-weight: 700; }
                QPushButton#splashAction:hover, QPushButton#splashContinue:hover { background: #2d7048; }
                QLabel#splashLogo { background: transparent; }
            """.replace("{BODY_FONT}", self.body_font_family).replace("{HEADING_FONT}", self.heading_font_family))


        # Shared interaction and data-view polish inspired by Beautiful UI / Notchset.
        # Kept native to Qt so the desktop app does not acquire a React runtime.
        self.setStyleSheet(self.styleSheet() + """
            QPushButton {
                border-radius: 7px;
                padding: 5px 9px;
                min-height: 19px;
                font-weight: 650;
            }
            QPushButton:disabled { opacity: 0.45; }
            QLineEdit, QComboBox, QSpinBox, QListWidget, QTreeWidget,
            QTableWidget, QPlainTextEdit {
                border-radius: 6px;
                padding: 4px 6px;
            }
            QGroupBox {
                border-radius: 9px;
                margin-top: 11px;
                padding: 10px 9px 8px 9px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QTabBar::tab {
                padding: 8px 9px;
                min-width: 92px;
            }
            QHeaderView::section {
                padding: 5px 6px;
            }
            QTableWidget::item {
                padding: 3px 5px;
            }
            QCheckBox, QRadioButton {
                spacing: 6px;
                padding: 1px;
            }
            QLabel#workspaceTitle {
                font-size: 16pt;
                letter-spacing: 0.6px;
            }
            QLabel#workspaceSubtitle {
                font-size: 8.5pt;
            }
            QLabel#headerVehicle, QLabel#headerOffline, QLabel#headerOnline,
            QLabel#headerSimulation {
                padding: 6px 8px;
                font-size: 8.5pt;
            }
            QLabel#headerTraffic {
                font-size: 9pt;
                padding: 2px 4px;
            }
            QToolButton#drawerToggle {
                padding: 5px 8px;
            }
            QTableWidget {
                alternate-background-color: rgba(120, 145, 160, 0.08);
                gridline-color: rgba(130, 150, 170, 0.18);
                selection-background-color: #286344;
            }
            QTableWidget::item {
                padding: 7px 8px;
                border-bottom: 1px solid rgba(130, 150, 170, 0.12);
            }
            QHeaderView::section {
                padding: 10px 9px;
                font-weight: 750;
                border: none;
            }
            QCheckBox, QRadioButton { spacing: 9px; padding: 4px 2px; }
            QToolTip { padding: 7px 9px; border-radius: 6px; }
            QScrollBar:vertical {
                width: 10px; margin: 3px; border: none; border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                min-height: 28px; border-radius: 5px;
                background: rgba(130, 150, 170, 0.45);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal {
                height: 10px; margin: 3px; border: none; border-radius: 5px;
            }
            QScrollBar::handle:horizontal {
                min-width: 28px; border-radius: 5px;
                background: rgba(130, 150, 170, 0.45);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        """)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        compact = width < 980
        if hasattr(self, "header_vehicle"):
            self.header_vehicle.setVisible(not compact)
        if hasattr(self, "header_traffic"):
            self.header_traffic.setVisible(width >= 860)
        if hasattr(self, "drawer_button"):
            self.drawer_button.setText("☷  NAV" if compact else "☷  QUICK PANEL")
            self.drawer_button.setToolTip(
                "Open workspace navigation" if compact
                else "Open vehicle context and workspace shortcuts"
            )
        if hasattr(self, "quick_drawer") and compact and self.quick_drawer.isVisible():
            self.quick_drawer.hide()

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
