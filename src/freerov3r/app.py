"""FreeRov3r – user-friendly diagnostic interface with graphing, OBD-II, and modules."""
import csv
import json
import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QTimer, Qt, QUrl
from PySide6.QtGui import QPalette, QColor, QFont, QFontDatabase, QPainter, QBrush, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow,
    QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QGroupBox,
    QFormLayout, QCheckBox, QSpinBox, QStackedWidget, QColorDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QGridLayout, QToolButton, QButtonGroup,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QScrollArea, QSizePolicy, QInputDialog,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False

from .hardware.receiver import FrameBatcher, Receiver
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
from .hardware.capture_replay_adapter import CaptureReplayAdapter
from .hardware.dual_channel_simulator import DualChannelSimulator
from .diagnostics.obd2 import (OBD_PIDS, PID_CATEGORIES_ALL, PID_MULTI_VALUE_KEYS, search_mode01_pids, decode_mode01_measurements, Mode01ScalingContext)
from .session import CaptureSession
from .can_monitor import CanMonitor
from .sensors.capture import SensorCapture
from .sensors.models import SensorSample
from .sensors.scaling import normalize_values, sample_clock, sample_time
from .sensors.analysis import summarize_sensor_samples
from .sensors.thresholds import evaluate_sensor_threshold, normalize_sensor_thresholds
from .sensor_dashboard import SensorDashboardDock
from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .diagnostics.service_routines import ServiceRoutine, ServiceRoutineManager
from .diagnostics.l319_wiring import NETWORKS as L319_WIRING_NETWORKS, SOURCE_URL as L319_WIRING_SOURCE_URL, DEFAULT_ENGINE as L319_DEFAULT_ENGINE

from .vehicle_history import VehicleHistoryStore
from .vehicle_history_tab import VehicleHistoryTab
from .solutions_tab import SolutionsTab
from .special_functions_tab import SpecialFunctionsTab
from .wiring_diagrams_tab import WiringDiagramsTab
from .network_overview_tab import NetworkOverviewTab
from .sensor_graph_tab import SensorGraphTab
from .obd_tab import OBDTab
from .modules_tab import ModulesTab
from .vehicle_setup_wizard import VehicleSetupWizard, VinDecodeWorker, VinQueryWorker
from .settings_tab import SettingsTab
from .capture_tab import CaptureTab
from .sensors_tab import SensorsTab
from .responsive_banner import ResponsiveBanner
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
        self.capture_channel = None
        self.capture_bitrate = None
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
        self.graph_tab = SensorGraphTab(self.sensor_capture, settings_save_callback=save_settings)
        self.graph_tab.parent_settings = self.settings
        self.graph_tab.update_statistics(force=True)
        self.graph_tab.refresh_favorite_groups()
        self.tabs.addTab(self.graph_tab, "Graph")
        self.obd_tab = OBDTab(self.settings, settings_save_callback=save_settings)
        self.obd_tab.read_dtcs_callback = self.request_dtc_scan
        self.obd_tab.read_readiness_callback = self.request_readiness_scan
        self.obd_tab.read_freeze_frame_callback = self.request_freeze_frame_scan
        self.obd_tab.read_vehicle_info_callback = self.request_vehicle_info_scan
        self.obd_tab.read_monitor_tests_callback = self.request_monitor_tests_scan
        self.graph_tab.selection_changed_callback = self.obd_tab.set_selected_sensor_ids
        self.obd_tab.selection_changed_callback = self.graph_tab.set_selected_sensor_ids
        self.graph_tab.navigate_to_obd_callback = lambda: self.tabs.setCurrentWidget(self.obd_tab)
        self.obd_tab.navigate_to_graph_callback = lambda: self.tabs.setCurrentWidget(self.graph_tab)
        self.graph_tab.favorites_changed_callback = self._refresh_sensor_favorites
        self.obd_tab.favorites_changed_callback = self._refresh_sensor_favorites
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
        self.sensor_dashboard_dock = SensorDashboardDock(
            self.sensor_capture,
            self,
            initial_sensor_ids=self.graph_tab.selected_sensor_ids(),
            vin_provider=lambda: self.settings.get("current_vin"),
            settings=self.settings,
            save_settings_callback=save_settings,
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self.sensor_dashboard_dock)
        self.sensor_dashboard_dock.hide()
        self.graph_tab.open_dashboard_callback = self.show_sensor_dashboard

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

    def _refresh_sensor_favorites(self, selected_name=None):
        """Keep sensor favorites synchronized across Graph, OBD-II and dashboard."""
        if hasattr(self, "graph_tab"):
            self.graph_tab.refresh_favorite_groups(selected_name)
        if hasattr(self, "obd_tab"):
            self.obd_tab._refresh_favorite_combo(selected_name)
        if hasattr(self, "sensor_dashboard_dock"):
            self.sensor_dashboard_dock._refresh_favorites(selected_name)
        # A dashboard layout belongs to its sensor favorite. Remove orphaned
        # layouts when the corresponding sensor favorite is deleted.
        groups = self.settings.get("obd_pid_favorites", {})
        layouts = self.settings.get("sensor_dashboard_favorites", {})
        if isinstance(groups, dict) and isinstance(layouts, dict):
            retained = {name: value for name, value in layouts.items() if name in groups}
            if retained != layouts:
                self.settings["sensor_dashboard_favorites"] = retained
                save_settings(self.settings)

    def show_sensor_dashboard(self):
        if hasattr(self, "sensor_dashboard_dock"):
            self.sensor_dashboard_dock.refresh()
            self.sensor_dashboard_dock._refresh_favorites()
            self.sensor_dashboard_dock.show()
            self.sensor_dashboard_dock.raise_()

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
        try:
            self.history_store.record(vehicle_vin, event_type, summary, details)
        except (OSError, RuntimeError) as exc:
            if hasattr(self, "history_tab"):
                self.history_tab.refresh()
            self.statusBar().showMessage(
                f"Vehicle history was not saved: {exc}", 15000
            )
            return False
        if hasattr(self, "history_tab"):
            self.history_tab.refresh()
        if hasattr(self, "solutions_tab"):
            self.solutions_tab.refresh()
        return True

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
        self.capture_tab = CaptureTab(
            mode_label=self.mode_label,
            settings=self.settings,
            refresh_serial_ports=self.refresh_serial_ports,
            toggle_capture=self.toggle_capture,
            refresh_can_display=self.refresh_can_display,
            export_capture=self.export_capture,
            clear_capture_display=self.clear_capture_display,
            back_to_tasks=lambda: self.stack.setCurrentIndex(0),
            parent=self,
        )
        for name in (
            "status",
            "backend",
            "channel_edit",
            "bitrate",
            "connect_btn",
            "frame_count_label",
            "rate_label",
            "can_id_filter",
            "can_format_filter",
            "can_data_filter",
            "monitor_summary",
            "log",
        ):
            setattr(self, name, getattr(self.capture_tab, name))
        self.tabs.addTab(self.capture_tab, "Capture")
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
        self.sensors_tab = SensorsTab(
            add_or_update_vehicle=self.add_or_update_vehicle,
            set_current_vehicle=self.set_current_vehicle,
            on_vehicle_selected=self.on_vehicle_selected,
            export_llm_report=self.export_llm_report,
            export_sensor_csv=self.export_sensor_csv,
            parent=self,
        )
        for name in (
            "vin_edit",
            "nickname_edit",
            "vehicle_list",
            "current_vehicle_label",
            "sensor_log",
        ):
            setattr(self, name, getattr(self.sensors_tab, name))
        self.tabs.addTab(self.sensors_tab, "Sensors")

    def _build_settings_tab(self):
        self.settings_tab = SettingsTab(
            toggle_dark_mode=self.toggle_dark_mode,
            show_about_dialog=self.show_about_dialog,
            save_settings=self.save_current_settings,
            parent=self,
        )
        for name in (
            "settings_backend",
            "settings_channel",
            "settings_bitrate",
            "dark_mode_cb",
            "max_log_spin",
            "auto_refresh_graph_cb",
            "graph_refresh_spin",
        ):
            setattr(self, name, getattr(self.settings_tab, name))
        self.tabs.addTab(self.settings_tab, "Settings")

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
                {"interface": self.active_interface,
                 "channel": self.capture_channel or "Unknown",
                 "bitrate": self.capture_bitrate or "Unknown",
                 "frames": len(capture_frames),
                 "sensor_samples": len(capture_samples),
                 "sensor_samples_dropped_from_bounded_buffer": capture_samples_dropped,
                 "duration_seconds": round(elapsed, 2),
                 "archive_file": str(archive_path)},
                vin=self.capture_vin or "UNASSIGNED",
            )
            self.capture_started_at = None
            self.capture_channel = None
            self.capture_bitrate = None
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

        if interface == "dual_simulator":
            channel = "HS-CAN,MS-CAN"
            adapter = DualChannelSimulator()
        elif interface == "capture_replay":
            replay_path = channel
            if not replay_path or not Path(replay_path).is_file():
                replay_path, _ = QFileDialog.getOpenFileName(
                    self, "Select FreeRov3r capture", str(Path.home()),
                    "FreeRov3r captures (*.jsonl);;All files (*)",
                )
            if not replay_path:
                return
            channel = replay_path
            adapter = CaptureReplayAdapter(replay_path)
        elif interface == "simulator":
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
        self.capture_channel = channel
        self.capture_bitrate = bitrate
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
        self.receiver.frames_received.connect(self.on_frames)
        self.receiver.status.connect(self.status.setText)
        self.receiver.dtcs_completed.connect(self._on_dtc_scan_completed)
        self.receiver.dtcs_failed.connect(self._on_dtc_scan_failed)
        self.receiver.readiness_completed.connect(self._on_readiness_scan_completed)
        self.receiver.readiness_failed.connect(self._on_readiness_scan_failed)
        self.receiver.freeze_frame_completed.connect(self._on_freeze_frame_scan_completed)
        self.receiver.freeze_frame_failed.connect(self._on_freeze_frame_scan_failed)
        self.receiver.vehicle_info_completed.connect(self._on_vehicle_info_scan_completed)
        self.receiver.vehicle_info_failed.connect(self._on_vehicle_info_scan_failed)
        self.receiver.monitor_tests_completed.connect(self._on_monitor_tests_scan_completed)
        self.receiver.monitor_tests_failed.connect(self._on_monitor_tests_scan_failed)
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

    def request_readiness_scan(self):
        receiver = self.receiver
        if self.active_interface != "elm327_obd" or receiver is None:
            return False
        return receiver.request_readiness()

    def request_vehicle_info_scan(self):
        receiver = self.receiver
        if self.active_interface != "elm327_obd" or receiver is None:
            return False
        return receiver.request_vehicle_info()

    def request_monitor_tests_scan(self):
        receiver = self.receiver
        if self.active_interface != "elm327_obd" or receiver is None:
            return False
        return receiver.request_monitor_tests()

    def _on_monitor_tests_scan_completed(self, result):
        self.obd_tab.show_monitor_test_results(result)
        responses = result.get("responses", [])
        count = sum(len(response.get("results", [])) for response in responses)
        self.record_vehicle_event(
            "monitor_tests_scan_completed",
            f"OBD-II Mode 06 monitor test scan completed: {count} result(s)",
            {
                "interface": self.active_interface,
                "service": "06",
                "supported_monitor_ids": result.get("supported_monitor_ids", []),
                "count": count,
                "results": result,
                "read_only": True,
                "values_are_raw": True,
            },
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast(
            f"Mode 06 read: {count} test result(s)",
            "success" if count else "warning",
        )

    def _on_monitor_tests_scan_failed(self, message):
        self.obd_tab.set_monitor_tests_scan_error(message)
        self.record_vehicle_event(
            "monitor_tests_scan_failed",
            "OBD-II Mode 06 monitor test read failed",
            {"interface": self.active_interface, "error": str(message), "read_only": True},
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast("Mode 06 read failed", "warning")

    def _on_vehicle_info_scan_completed(self, results):
        self.obd_tab.show_vehicle_info_results(results)
        detected_vins = {
            validate_vin(item.get("value"))
            for result in results if result.get("pid") == 0x02
            for item in result.get("items", []) if item.get("type") == "vin"
        }
        detected_vins.discard(None)
        if len(detected_vins) == 1:
            self._apply_detected_vin(next(iter(detected_vins)))
        self.record_vehicle_event(
            "vehicle_info_scan_completed",
            f"OBD-II Mode 09 identification read: {sum(len(item.get('items', [])) for item in results)} record(s)",
            {
                "interface": self.active_interface,
                "service": "09",
                "count": len(results),
                "results": results,
                "read_only": True,
            },
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast(
            f"Vehicle information read: {len(results)} ECU response(s)",
            "success" if results else "warning",
        )

    def _on_vehicle_info_scan_failed(self, message):
        self.obd_tab.set_vehicle_info_scan_error(message)
        self.record_vehicle_event(
            "vehicle_info_scan_failed",
            "OBD-II Mode 09 vehicle-information read failed",
            {"interface": self.active_interface, "error": str(message), "read_only": True},
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast("Vehicle-information read failed", "warning")

    def request_freeze_frame_scan(self, pids, frame_number=0):
        receiver = self.receiver
        if self.active_interface != "elm327_obd" or receiver is None:
            return False
        return receiver.request_freeze_frame(pids, frame_number)

    def _on_freeze_frame_scan_completed(self, results):
        self.obd_tab.show_freeze_frame_results(results)
        self.record_vehicle_event(
            "freeze_frame_scan_completed",
            f"OBD-II freeze-frame scan completed: {len(results)} PID response(s)",
            {
                "interface": self.active_interface,
                "service": "02",
                "frame_number": self.obd_tab.freeze_frame_number.value(),
                "count": len(results),
                "results": results,
                "read_only": True,
            },
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast(
            f"Freeze-frame scan complete: {len(results)} PID response(s)",
            "success" if results else "warning",
        )

    def _on_freeze_frame_scan_failed(self, message):
        self.obd_tab.set_freeze_frame_scan_error(message)
        self.record_vehicle_event(
            "freeze_frame_scan_failed",
            "OBD-II freeze-frame scan failed",
            {"interface": self.active_interface, "error": str(message), "read_only": True},
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast("Freeze-frame scan failed", "warning")

    def _on_readiness_scan_completed(self, results):
        self.obd_tab.show_readiness_results(results)
        self.record_vehicle_event(
            "readiness_scan_completed",
            f"OBD-II readiness scan completed: {len(results)} ECU response(s)",
            {
                "interface": self.active_interface,
                "service": "01",
                "pid": "01",
                "count": len(results),
                "results": results,
                "read_only": True,
            },
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast(
            f"Readiness scan complete: {len(results)} ECU response(s)",
            "success" if results else "warning",
        )

    def _on_readiness_scan_failed(self, message):
        self.obd_tab.set_readiness_scan_error(message)
        self.record_vehicle_event(
            "readiness_scan_failed",
            "OBD-II readiness scan failed",
            {"interface": self.active_interface, "error": str(message), "read_only": True},
            vin=self.capture_vin or self.settings.get("current_vin") or "UNASSIGNED",
        )
        self.show_toast("Readiness scan failed", "warning")

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

    def on_frames(self, frames):
        """Process receiver batches with one visible log/counter update."""
        log_lines = []
        for frame in frames:
            line = self.on_frame(frame, update_display=False)
            if line:
                log_lines.append(line)
        self.frame_count_label.setText(f"Frames: {self.frame_counter}")
        if log_lines:
            self.log.appendPlainText("\n".join(log_lines))

    def on_frame(self, frame, update_display=True):
        detected_vin = self.vin_decoder.feed(frame.arbitration_id, bytes(frame.data))
        if detected_vin:
            self._apply_detected_vin(detected_vin)
        self.session.add(frame)
        self.can_monitor.add(frame)
        self.research_tab.observe_frame(frame)
        self.frame_counter += 1
        if update_display:
            self.frame_count_label.setText(f"Frames: {self.frame_counter}")
        ts = frame.timestamp or 0
        line = None
        if self.can_monitor.matches(frame, self.can_id_filter.text(), self.can_format_filter.currentText()):
            frame_type = "EXT" if frame.is_extended_id else "STD"
            line = (
                f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
                f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}"
            )
            if update_display:
                self.log.appendPlainText(line)
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
                    monotonic_timestamp=time.monotonic(),
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

        return line

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
            if self.tabs.currentWidget() is self.graph_tab:
                self.graph_tab.update_statistics()
            rate = (self.frame_counter - self.last_rate_count) / elapsed
            rolling_rate = self.can_monitor.rate()
            self.rate_label.setText(f"Rate: {rate:.1f} fps | Rolling: {rolling_rate:.1f} fps")
            self._refresh_workspace_header()
            top_ids = self.can_monitor.id_stats()[:5]
            summary = " | ".join(
                f"{item.arbitration_id:08X}{'X' if item.extended else 'S'}: "
                f"{item.frames_per_second:.1f}/s, Δ{item.payload_changes}, "
                f"{item.median_interval_ms:.1f}ms"
                if item.median_interval_ms is not None else
                f"{item.arbitration_id:08X}{'X' if item.extended else 'S'}: "
                f"{item.frames_per_second:.1f}/s, Δ{item.payload_changes}"
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
                frame, self.can_id_filter.text(), self.can_format_filter.currentText(),
                self.can_data_filter.text(),
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
