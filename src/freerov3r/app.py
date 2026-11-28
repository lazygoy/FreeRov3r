"""FreeRov3r – user-friendly diagnostic interface with graphing, OBD-II, and modules."""
import csv
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, QGroupBox, QStackedWidget,
    QGridLayout, QDialog,
)

from .vehicle_profiles.registry import VehicleProfileRegistry
from .hardware.receiver import FrameBatcher, Receiver
from .session import CaptureSession
from .core.capture.session_context import CaptureSessionContext
from .can_monitor import CanMonitor
from .diagnostics.obd2 import Mode01ScalingContext
from .sensors.capture import SensorCapture
from .sensor_dashboard import SensorDashboardDock
from .diagnostics.simulated_modules import SimulatedModuleNetwork

from .vehicle_history import VehicleHistoryStore
from .vehicle_history_tab import VehicleHistoryTab
from .solutions_tab import SolutionsTab
from .special_functions_tab import SpecialFunctionsTab
from .wiring_diagrams_tab import WiringDiagramsTab
from .network_overview_tab import NetworkOverviewTab
from .sensor_graph_tab import HAS_CHARTS, SensorGraphTab
from .obd_tab import OBDTab
from .modules_tab import ModulesTab
from .vehicle_setup_wizard import VehicleSetupWizard, VinDecodeWorker, VinQueryWorker
from .settings_tab import SettingsTab
from .capture_tab import CaptureTab
from .dpdu_tab import DPduTab
from .sensors_tab import SensorsTab
from .navigation_workspace import NavigationWorkspace
from .workspace_modes import WorkspaceMode, tab_is_visible
from .theme import apply_theme
from .capture_control import toggle_capture as toggle_capture_impl
from .frame_processing import process_frame, process_frames
from .startup_splash import show_startup_splash
from .vehicle_context import update_vehicle_context
from .setup_flow import run_setup_wizard as run_setup_wizard_flow
from .port_selection import refresh_serial_ports
from .vehicle_management import (
    _refresh_vehicle_list as _refresh_vehicle_list_action,
    add_or_update_vehicle as add_or_update_vehicle_action,
    set_current_vehicle as set_current_vehicle_action,
    on_vehicle_selected as on_vehicle_selected_action,
    _apply_detected_vin as _apply_detected_vin_action,
)
from .diagnostic_actions import (
    request_dtc_scan as request_dtc_scan_action,
    request_readiness_scan as request_readiness_scan_action,
    request_vehicle_info_scan as request_vehicle_info_scan_action,
    request_monitor_tests_scan as request_monitor_tests_scan_action,
    _on_monitor_tests_scan_completed as _on_monitor_tests_scan_completed_action,
    _on_monitor_tests_scan_failed as _on_monitor_tests_scan_failed_action,
    _on_vehicle_info_scan_completed as _on_vehicle_info_scan_completed_action,
    _on_vehicle_info_scan_failed as _on_vehicle_info_scan_failed_action,
    request_freeze_frame_scan as request_freeze_frame_scan_action,
    _on_freeze_frame_scan_completed as _on_freeze_frame_scan_completed_action,
    _on_freeze_frame_scan_failed as _on_freeze_frame_scan_failed_action,
    _on_readiness_scan_completed as _on_readiness_scan_completed_action,
    _on_readiness_scan_failed as _on_readiness_scan_failed_action,
    _on_dtc_scan_completed as _on_dtc_scan_completed_action,
    _on_dtc_scan_failed as _on_dtc_scan_failed_action,
)
from .responsive_banner import ResponsiveBanner
from .diagnostics.vin_decoder import VinFrameDecoder
from .ui_feedback import QuickDrawer, ToastManager
from .asset_loader import ASSET_DIR, load_asset_pixmap
from .research_tab import ResearchTab
from .tuning_tab import TuningTab

SETTINGS_DIR = Path.home() / ".freerov3r"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "interface": "elm327_obd",
    "channel": "",
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
        self.capture_session_context = None
        self.capture_started_at = None
        self.capture_channel = None
        self.capture_bitrate = None
        self.capture_start_frames = 0
        self.capture_start_sample_index = 0
        self.capture_start_frame_index = 0
        self.capture_start_diagnostic_event_index = 0
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

        self.workspace_mode = WorkspaceMode.DIAGNOSTICS
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

        # Workspace chooser: always shown at launch.
        welcome = QWidget()
        welcome.setObjectName("workspaceChooser")
        wlayout = QVBoxLayout(welcome)
        wlayout.setAlignment(Qt.AlignCenter)
        wlayout.setSpacing(18)
        wlayout.setContentsMargins(54, 36, 54, 42)

        self.welcome_banner = ResponsiveBanner()
        self.welcome_banner.set_source_pixmap(load_asset_pixmap("brand_banner.svg"))
        self.welcome_banner.setMaximumHeight(190)
        wlayout.addWidget(self.welcome_banner)

        eyebrow = QLabel("FREEROV3R  /  VEHICLE SYSTEMS")
        eyebrow.setObjectName("chooserEyebrow")
        eyebrow.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(eyebrow)

        title = QLabel("What are you here to do?")
        title.setObjectName("chooserTitle")
        title_font = QFont(self.heading_font_family, 27, QFont.Bold)
        title_font.setItalic(False)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        wlayout.addWidget(title)

        subtitle = QLabel(
            "Choose a workspace. You can switch at any time without losing your session."
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("welcomeSubtitle")
        wlayout.addWidget(subtitle)

        choice_row = QGridLayout()
        choice_row.setSpacing(16)

        diagnostic_card = QWidget()
        diagnostic_card.setObjectName("chooserCard")
        diagnostic_layout = QVBoxLayout(diagnostic_card)
        diagnostic_layout.setContentsMargins(22, 22, 22, 22)
        diagnostic_layout.setSpacing(10)
        diagnostic_icon = QLabel("⌁")
        diagnostic_icon.setObjectName("chooserIcon")
        diagnostic_layout.addWidget(diagnostic_icon)
        diagnostic_title = QLabel("VEHICLE DIAGNOSTICS")
        diagnostic_title.setObjectName("chooserCardTitle")
        diagnostic_layout.addWidget(diagnostic_title)
        diagnostic_description = QLabel(
            "Identify a vehicle, scan control modules, inspect trouble codes, "
            "monitor live data, graph sensors and run supported service checks."
        )
        diagnostic_description.setObjectName("chooserCardDescription")
        diagnostic_description.setWordWrap(True)
        diagnostic_layout.addWidget(diagnostic_description, 1)
        self.diagnostics_entry_button = QPushButton("OPEN DIAGNOSTICS  →")
        self.diagnostics_entry_button.setObjectName("chooserPrimaryButton")
        self.diagnostics_entry_button.setMinimumHeight(48)
        self.diagnostics_entry_button.clicked.connect(self.show_diagnostics_mode)
        diagnostic_layout.addWidget(self.diagnostics_entry_button)

        development_card = QWidget()
        development_card.setObjectName("chooserCard")
        development_layout = QVBoxLayout(development_card)
        development_layout.setContentsMargins(22, 22, 22, 22)
        development_layout.setSpacing(10)
        development_icon = QLabel("⌘")
        development_icon.setObjectName("chooserIcon")
        development_layout.addWidget(development_icon)
        development_title = QLabel("DEVELOPMENT & RESEARCH")
        development_title.setObjectName("chooserCardTitle")
        development_layout.addWidget(development_title)
        development_description = QLabel(
            "Capture raw CAN traffic, inspect protocols, compare sessions, "
            "develop signal definitions and extend vehicle support."
        )
        development_description.setObjectName("chooserCardDescription")
        development_description.setWordWrap(True)
        development_layout.addWidget(development_description, 1)
        self.development_entry_button = QPushButton("OPEN DEVELOPMENT LAB  →")
        self.development_entry_button.setObjectName("chooserSecondaryButton")
        self.development_entry_button.setMinimumHeight(48)
        self.development_entry_button.clicked.connect(self.show_development_mode)
        development_layout.addWidget(self.development_entry_button)

        choice_row.addWidget(diagnostic_card, 0, 0)
        choice_row.addWidget(development_card, 0, 1)
        wlayout.addLayout(choice_row)

        note = QLabel(
            "DIAGNOSTICS keeps engineering tools out of the operator workflow. "
            "DEVELOPMENT exposes the low-level workbench."
        )
        note.setObjectName("chooserFootnote")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        wlayout.addWidget(note)

        welcome.setStyleSheet("""
            QWidget#workspaceChooser { background: #0b1014; }
            QLabel#chooserEyebrow {
                color: #78a58b; font-size: 8pt; font-weight: 800;
                letter-spacing: 2px; padding-top: 6px;
            }
            QLabel#chooserTitle {
                color: #f0f5f1; letter-spacing: 0.4px;
            }
            QLabel#welcomeSubtitle { color: #91a69b; font-size: 10pt; }
            QWidget#chooserCard {
                background: #121d22; border: 1px solid #2a3b3d;
                border-radius: 14px; min-width: 310px; min-height: 250px;
            }
            QLabel#chooserIcon {
                color: #8dc39e; font-size: 34pt; font-weight: 400;
            }
            QLabel#chooserCardTitle {
                color: #e8f1eb; font-size: 12pt; font-weight: 800;
                letter-spacing: 1px;
            }
            QLabel#chooserCardDescription {
                color: #9aada4; font-size: 9pt; line-height: 1.4;
            }
            QPushButton#chooserPrimaryButton {
                color: #f0fff4; background: #24563c;
                border: 1px solid #4d8a64; border-radius: 8px;
                font-weight: 800; padding: 10px 14px;
            }
            QPushButton#chooserPrimaryButton:hover { background: #2d6b49; }
            QPushButton#chooserSecondaryButton {
                color: #dcebe2; background: #1b292d;
                border: 1px solid #49605b; border-radius: 8px;
                font-weight: 800; padding: 10px 14px;
            }
            QPushButton#chooserSecondaryButton:hover {
                background: #263d3b; border-color: #628575;
            }
            QLabel#chooserFootnote {
                color: #667a70; font-size: 8pt; padding-top: 8px;
            }
        """)

        self.stack.addWidget(welcome)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        self._build_capture_tab()
        self.dpdu_tab = DPduTab(self.on_diagnostic_events, parent=self)
        self.tabs.addTab(self.dpdu_tab, "D-PDU")
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
        self.tabs.currentChanged.connect(
            lambda index: self.modules_tab.refresh_evidence_inventory()
            if self.tabs.widget(index) is self.modules_tab else None
        )
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
        self.tabs.currentChanged.connect(
            lambda index: self.research_tab._set_live_enabled(
                self.tabs.widget(index) is self.research_tab
            )
        )
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
        self.navigation_workspace = NavigationWorkspace(
            tabs=self.tabs,
            heading_font_family=self.heading_font_family,
            body_font_family=self.body_font_family,
            toggle_quick_drawer=self.toggle_quick_drawer,
            on_tab_changed=self._sync_navigation_selection,
            on_workspace_mode_changed=self._set_workspace_mode,
            on_home=self.show_workspace_chooser,
            parent=self,
        )
        self.workspace_scroll = self.navigation_workspace
        for name in (
            "workspace_title",
            "workspace_subtitle",
            "header_vehicle",
            "header_connection",
            "header_traffic",
            "drawer_button",
            "home_button",
        ):
            setattr(self, name, getattr(self.navigation_workspace, name))
        self.stack.addWidget(self.navigation_workspace)
        self._set_workspace_mode(self.workspace_mode.value)
        self.stack.setCurrentIndex(0)
        self._sync_navigation_selection(self.tabs.currentIndex())

    def _set_workspace_mode(self, mode_value):
        """Show only the tabs belonging to the selected top-level workspace."""
        try:
            mode = WorkspaceMode(mode_value)
        except ValueError:
            return
        self.workspace_mode = mode
        if hasattr(self, "quick_drawer"):
            self.quick_drawer.set_workspace_mode(mode.value)
        if hasattr(self, "navigation_workspace"):
            self.navigation_workspace.set_workspace_mode(mode.value)
        for index in range(self.tabs.count()):
            self.tabs.setTabVisible(
                index, tab_is_visible(self.tabs.tabText(index), mode)
            )
        if hasattr(self, "navigation_workspace"):
            self.navigation_workspace._refresh_navigation_visibility()

        current_index = self.tabs.currentIndex()
        current_name = self.tabs.tabText(current_index) if current_index >= 0 else ""
        if not tab_is_visible(current_name, mode):
            fallback = "Research" if mode is WorkspaceMode.RESEARCH else "OBD-II"
            self._navigate_to_tab(fallback)
        if hasattr(self, "workspace_title"):
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
        run_setup_wizard_flow(self)

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
        show_startup_splash(self)

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
        refresh_serial_ports(self)

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

    def show_workspace_chooser(self):
        """Return to the initial purpose selector without ending the session."""
        self.stack.setCurrentIndex(0)

    def show_diagnostics_mode(self):
        self._set_workspace_mode(WorkspaceMode.DIAGNOSTICS.value)
        self.tabs.setCurrentWidget(self.obd_tab)
        self.stack.setCurrentIndex(1)

    def show_development_mode(self):
        self._set_workspace_mode(WorkspaceMode.RESEARCH.value)
        self.tabs.setCurrentWidget(self.research_tab)
        self.stack.setCurrentIndex(1)

    def show_dtc_mode(self):
        self._set_workspace_mode(WorkspaceMode.DIAGNOSTICS.value)
        self.tabs.setCurrentWidget(self.obd_tab)
        self.stack.setCurrentIndex(1)

    def show_obd_mode(self):
        self.show_dtc_mode()

    def show_sensor_mode(self):
        self._set_workspace_mode(WorkspaceMode.DIAGNOSTICS.value)
        self.tabs.setCurrentWidget(self.sensors_tab)
        self.stack.setCurrentIndex(1)

    def show_graph_mode(self):
        self._set_workspace_mode(WorkspaceMode.DIAGNOSTICS.value)
        self.tabs.setCurrentWidget(self.graph_tab)
        self.stack.setCurrentIndex(1)

    def show_vehicle_info_mode(self):
        self.show_sensor_mode()

    def show_modules_mode(self):
        self._set_workspace_mode(WorkspaceMode.DIAGNOSTICS.value)
        self.tabs.setCurrentWidget(self.modules_tab)
        self.stack.setCurrentIndex(1)

    def _apply_settings(self):
        iface = self.settings.get("interface", "virtual")
        self.capture_tab.select_backend(iface)
        self.channel_edit.setCurrentText(self.settings.get("channel", "freerov3r"))
        self.bitrate.setCurrentText(str(self.settings.get("bitrate", 500000)))
        self.settings_tab.select_backend(iface)
        self.settings_channel.setText(self.settings.get("channel", "freerov3r"))
        self.settings_bitrate.setCurrentText(str(self.settings.get("bitrate", 500000)))
        self.max_log_spin.setValue(self.settings.get("max_log_lines", 5000))
        self.auto_refresh_graph_cb.setChecked(self.settings.get("auto_refresh_graph", True))
        self.graph_refresh_spin.setValue(self.settings.get("graph_refresh_ms", 1000))
        self.dark_mode_cb.setChecked(self.settings.get("dark_mode", True))
        self.apply_dark_mode(self.settings.get("dark_mode", True))
        self._refresh_vehicle_list()

    def _refresh_vehicle_list(self):
        return _refresh_vehicle_list_action(self)

    def add_or_update_vehicle(self):
        return add_or_update_vehicle_action(self)

    def set_current_vehicle(self):
        return set_current_vehicle_action(self)

    def on_vehicle_selected(self, item):
        return on_vehicle_selected_action(self, item)

    def _update_vehicle_context(self):
        update_vehicle_context(self)

    def _apply_detected_vin(self, vin):
        return _apply_detected_vin_action(self, vin)

    def toggle_capture(self):
        toggle_capture_impl(self)
    def request_dtc_scan(self):
        return request_dtc_scan_action(self)

    def request_readiness_scan(self):
        return request_readiness_scan_action(self)

    def request_vehicle_info_scan(self):
        return request_vehicle_info_scan_action(self)

    def request_monitor_tests_scan(self):
        return request_monitor_tests_scan_action(self)

    def _on_monitor_tests_scan_completed(self, result):
        return _on_monitor_tests_scan_completed_action(self, result)

    def _on_monitor_tests_scan_failed(self, message):
        return _on_monitor_tests_scan_failed_action(self, message)

    def _on_vehicle_info_scan_completed(self, results):
        return _on_vehicle_info_scan_completed_action(self, results)

    def _on_vehicle_info_scan_failed(self, message):
        return _on_vehicle_info_scan_failed_action(self, message)

    def request_freeze_frame_scan(self, pids, frame_number=0):
        return request_freeze_frame_scan_action(self, pids, frame_number)

    def _on_freeze_frame_scan_completed(self, results):
        return _on_freeze_frame_scan_completed_action(self, results)

    def _on_freeze_frame_scan_failed(self, message):
        return _on_freeze_frame_scan_failed_action(self, message)

    def _on_readiness_scan_completed(self, results):
        return _on_readiness_scan_completed_action(self, results)

    def _on_readiness_scan_failed(self, message):
        return _on_readiness_scan_failed_action(self, message)

    def _on_dtc_scan_completed(self, codes):
        return _on_dtc_scan_completed_action(self, codes)

    def _on_dtc_scan_failed(self, message):
        return _on_dtc_scan_failed_action(self, message)

    def on_frames(self, frames):
        process_frames(self, frames)

    def on_diagnostic_events(self, events):
        """Accept normalized protocol events from a dedicated diagnostic worker."""
        for event in events or ():
            self.session.add_diagnostic_event(event)

    def on_frame(self, frame, update_display=True):
        return process_frame(self, frame, update_display=update_display)

    def _update_receiver_health(self):
        """Publish live ESP32 adapter diagnostics to the Research workspace."""
        adapter = self.active_adapter
        diagnostics = getattr(adapter, "diagnostics", None) if adapter is not None else None
        self.research_tab.set_clock_sync_adapters(getattr(adapter, "adapters", ())) if hasattr(self.research_tab, "set_clock_sync_adapters") else None
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
        apply_theme(
            self,
            enabled,
            self.body_font_family,
            self.heading_font_family,
        )

    def save_current_settings(self):
        backend_data = self.settings_backend.currentData()
        if backend_data:
            self.settings["interface"] = backend_data[0]
            self.settings["channel"] = self.settings_channel.text().strip() or backend_data[1]
            self.settings["bitrate"] = int(self.settings_bitrate.currentText())
            self.capture_tab.select_backend(backend_data[0])
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
        if hasattr(self, "dpdu_tab") and not self.dpdu_tab.shutdown():
            self.status.setText(
                "D-PDU worker is still shutting down. Close cancelled to avoid unloading an active driver."
            )
            event.ignore()
            return
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
