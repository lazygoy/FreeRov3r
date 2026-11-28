def test_responsive_banner_remains_available_from_app_module():
    from freerov3r.app import ResponsiveBanner as app_banner
    from freerov3r.responsive_banner import ResponsiveBanner

    assert app_banner is ResponsiveBanner


def test_vehicle_history_tab_remains_available_from_app_module():
    from freerov3r.app import VehicleHistoryTab as app_history_tab
    from freerov3r.vehicle_history_tab import VehicleHistoryTab

    assert app_history_tab is VehicleHistoryTab

def test_solutions_tab_remains_available_from_app_module():
    from freerov3r.app import SolutionsTab as app_solutions_tab
    from freerov3r.solutions_tab import SolutionsTab

    assert app_solutions_tab is SolutionsTab

def test_special_functions_tab_remains_available_from_app_module():
    from freerov3r.app import SpecialFunctionsTab as app_special_functions_tab
    from freerov3r.special_functions_tab import SpecialFunctionsTab

    assert app_special_functions_tab is SpecialFunctionsTab

def test_wiring_diagrams_tab_remains_available_from_app_module():
    from freerov3r.app import WiringDiagramsTab as app_wiring_tab
    from freerov3r.wiring_diagrams_tab import WiringDiagramsTab

    assert app_wiring_tab is WiringDiagramsTab


def test_network_overview_tab_remains_available_from_app_module():
    from freerov3r.app import NetworkOverviewTab as app_network_tab
    from freerov3r.network_overview_tab import NetworkOverviewTab

    assert app_network_tab is NetworkOverviewTab


def test_vehicle_history_store_remains_available_from_app_module():
    from freerov3r.app import VehicleHistoryStore as app_history_store
    from freerov3r.vehicle_history import VehicleHistoryStore

    assert app_history_store is VehicleHistoryStore



def test_sensor_graph_tab_remains_available_from_app_module():
    from freerov3r.app import SensorGraphTab as app_sensor_graph_tab
    from freerov3r.sensor_graph_tab import SensorGraphTab

    assert app_sensor_graph_tab is SensorGraphTab

_QT_TEST_APP = None


def test_sensor_graph_tab_constructs_with_empty_capture():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.sensor_graph_tab import SensorGraphTab
    from freerov3r.sensors.capture import SensorCapture

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = SensorGraphTab(SensorCapture())
    assert tab.sensor_list.count() == 0
    assert not hasattr(tab, "stats_table")
    assert tab.activity_timer.isActive()
    assert tab.dashboard_widget is None

    tab.activity_timer.stop()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_obd_tab_remains_available_from_app_module():
    from freerov3r.app import OBDTab as app_obd_tab
    from freerov3r.obd_tab import OBDTab

    assert app_obd_tab is OBDTab


def test_obd_tab_constructs_with_default_settings():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.obd_tab import OBDTab

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = OBDTab(settings={}, settings_save_callback=lambda _settings: None)
    assert tab.table.rowCount() > 0
    assert tab.activity_timer.isActive()

    tab.activity_timer.stop()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_modules_tab_remains_available_from_app_module():
    from freerov3r.app import ModulesTab as app_modules_tab
    from freerov3r.modules_tab import ModulesTab

    assert app_modules_tab is ModulesTab


def test_modules_tab_constructs_with_simulated_network():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.diagnostics.simulated_modules import SimulatedModuleNetwork
    from freerov3r.modules_tab import ModulesTab

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = ModulesTab(SimulatedModuleNetwork())
    assert tab.module_tree.topLevelItemCount() > 0
    assert tab.dtc_table.rowCount() == 0

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_vehicle_setup_wizard_and_workers_remain_available_from_app_module():
    from freerov3r.app import (
        VehicleSetupWizard as app_wizard,
        VinDecodeWorker as app_decode_worker,
        VinQueryWorker as app_query_worker,
    )
    from freerov3r.vehicle_setup_wizard import (
        VehicleSetupWizard, VinDecodeWorker, VinQueryWorker,
    )

    assert app_wizard is VehicleSetupWizard
    assert app_decode_worker is VinDecodeWorker
    assert app_query_worker is VinQueryWorker


def test_vehicle_setup_wizard_constructs():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.vehicle_setup_wizard import VehicleSetupWizard

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    dialog = VehicleSetupWizard(current_settings={})
    assert dialog.isModal()
    assert dialog.result_data is None

    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(dialog, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_settings_tab_remains_available_from_app_module():
    from freerov3r.app import SettingsTab as app_settings_tab
    from freerov3r.settings_tab import SettingsTab

    assert app_settings_tab is SettingsTab


def test_settings_tab_constructs_and_exposes_controls():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.settings_tab import SettingsTab

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = SettingsTab(
        toggle_dark_mode=lambda _enabled: None,
        show_about_dialog=lambda: None,
        save_settings=lambda: None,
    )
    assert tab.settings_backend.count() == 3
    assert {tab.settings_backend.itemData(index)[0] for index in range(tab.settings_backend.count())} == {
        "elm327_obd", "esp32_framed_dual_usb", "esp32_framed_dual_wifi"
    }
    tab.show_advanced_interfaces.setChecked(True)
    assert any(
        tab.settings_backend.itemData(index)
        and tab.settings_backend.itemData(index)[0] == "j2534"
        for index in range(tab.settings_backend.count())
    )
    assert tab.graph_refresh_spin.minimum() == 250
    assert tab.graph_refresh_spin.maximum() == 5000

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_capture_tab_remains_available_from_app_module():
    from freerov3r.app import CaptureTab as app_capture_tab
    from freerov3r.capture_tab import CaptureTab

    assert app_capture_tab is CaptureTab


def test_capture_tab_constructs_with_callbacks():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QLabel

    from freerov3r.capture_tab import CaptureTab

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = CaptureTab(
        mode_label=QLabel("Mode"),
        settings={"max_log_lines": 1200},
        refresh_serial_ports=lambda: None,
        toggle_capture=lambda: None,
        refresh_can_display=lambda: None,
        export_capture=lambda: None,
        clear_capture_display=lambda: None,
        back_to_tasks=lambda: None,
    )
    assert tab.backend.count() == 3
    assert {tab.backend.itemData(index)[0] for index in range(tab.backend.count())} == {
        "elm327_obd", "esp32_framed_dual_usb", "esp32_framed_dual_wifi"
    }
    tab.show_advanced_interfaces.setChecked(True)
    assert any(
        tab.backend.itemData(index)
        and tab.backend.itemData(index)[0] == "j2534"
        for index in range(tab.backend.count())
    )
    assert tab.log.maximumBlockCount() == 1200
    assert tab.can_format_filter.count() == 3

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_sensors_tab_remains_available_from_app_module():
    from freerov3r.app import SensorsTab as app_sensors_tab
    from freerov3r.sensors_tab import SensorsTab

    assert app_sensors_tab is SensorsTab


def test_sensors_tab_constructs_with_callbacks():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.sensors_tab import SensorsTab

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tab = SensorsTab(
        add_or_update_vehicle=lambda: None,
        set_current_vehicle=lambda: None,
        on_vehicle_selected=lambda _item: None,
        export_llm_report=lambda: None,
        export_sensor_csv=lambda: None,
    )
    assert tab.vin_edit.text() == ""
    assert tab.vehicle_list.count() == 0
    assert tab.sensor_log.isReadOnly()

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_navigation_workspace_remains_available_from_app_module():
    from freerov3r.app import NavigationWorkspace as app_navigation_workspace
    from freerov3r.navigation_workspace import NavigationWorkspace

    assert app_navigation_workspace is NavigationWorkspace


def test_navigation_workspace_constructs_with_tabs():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

    from freerov3r.navigation_workspace import NavigationWorkspace

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Capture")
    workspace = NavigationWorkspace(
        tabs=tabs,
        heading_font_family="Arial",
        body_font_family="Arial",
        toggle_quick_drawer=lambda: None,
        on_tab_changed=lambda _index: None,
    )
    assert workspace.widget() is not None
    assert workspace.workspace_title.text() == "Capture"
    assert tabs.tabBar().isHidden()

    workspace.deleteLater()
    tabs.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

def test_theme_function_is_available_from_app_module():
    from freerov3r.app import apply_theme as app_apply_theme
    from freerov3r.theme import apply_theme

    assert app_apply_theme is apply_theme


def test_theme_engine_applies_light_and_dark_styles():
    global _QT_TEST_APP

    from PySide6.QtWidgets import QApplication, QWidget

    from freerov3r.theme import apply_theme

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    window = QWidget()
    apply_theme(window, True, "Arial", "Arial")
    assert "workspaceHeader" in window.styleSheet()
    apply_theme(window, False, "Arial", "Arial")
    assert "workspaceHeader" in window.styleSheet()

    window.deleteLater()
    _QT_TEST_APP.processEvents()

def test_capture_controller_is_available_from_app_module():
    from freerov3r.app import toggle_capture_impl as app_capture_controller
    from freerov3r.capture_control import toggle_capture

    assert app_capture_controller is toggle_capture
    assert callable(toggle_capture)

def test_frame_processing_helpers_are_available_from_app_module():
    from freerov3r.app import process_frame as app_process_frame
    from freerov3r.app import process_frames as app_process_frames
    from freerov3r.frame_processing import process_frame, process_frames

    assert app_process_frame is process_frame
    assert app_process_frames is process_frames


def test_frame_processor_records_non_obd_can_frame():
    from types import SimpleNamespace

    from freerov3r.frame_processing import process_frame

    window = SimpleNamespace(
        vin_decoder=SimpleNamespace(feed=lambda *_args: None),
        session=SimpleNamespace(add=lambda _frame: None),
        can_monitor=SimpleNamespace(
            add=lambda _frame: None,
            matches=lambda *_args: True,
        ),
        research_tab=SimpleNamespace(observe_frame=lambda _frame: None),
        frame_counter=0,
        frame_count_label=SimpleNamespace(setText=lambda _text: None),
        can_id_filter=SimpleNamespace(text=lambda: ""),
        can_format_filter=SimpleNamespace(currentText=lambda: "All"),
        active_interface="virtual",
        obd_scaling_context={},
        log=SimpleNamespace(appendPlainText=lambda _line: None),
    )
    frame = SimpleNamespace(
        timestamp=1.25,
        arbitration_id=0x123,
        data=bytes([0x01, 0x02]),
        is_extended_id=False,
    )

    line = process_frame(window, frame)
    assert "00000123" in line
    assert "STD" in line
    assert window.frame_counter == 1

def test_startup_splash_helper_remains_available_from_app_module():
    from freerov3r.app import show_startup_splash as app_show_startup_splash
    from freerov3r.startup_splash import show_startup_splash

    assert app_show_startup_splash is show_startup_splash

def test_diagnostic_action_helpers_are_available_from_app_module():
    from freerov3r.app import request_dtc_scan_action as app_request_dtc_scan
    from freerov3r.diagnostic_actions import request_dtc_scan

    assert app_request_dtc_scan is request_dtc_scan
    assert callable(request_dtc_scan)

def test_vehicle_context_helper_is_available_from_app_module():
    from freerov3r.app import update_vehicle_context as app_update_vehicle_context
    from freerov3r.vehicle_context import update_vehicle_context

    assert app_update_vehicle_context is update_vehicle_context


def test_vehicle_context_disables_l319_workspaces_for_generic_vehicle():
    from types import SimpleNamespace

    from freerov3r.vehicle_context import update_vehicle_context

    tab_state = {}
    tabs = SimpleNamespace(
        count=lambda: 3,
        tabText=lambda index: ["Capture", "Special Functions", "Topology"][index],
        setTabEnabled=lambda index, enabled: tab_state.__setitem__(index, enabled),
        setTabToolTip=lambda index, tooltip: None,
    )
    window = SimpleNamespace(
        settings={"active_vehicle": {"profile_id": "generic", "make": "Toyota", "model": "Camry"}},
        vehicle_profiles=SimpleNamespace(get=lambda _profile: None),
        sensor_capture=SimpleNamespace(vehicle_context={}),
        tabs=tabs,
        _refresh_workspace_header=lambda: None,
        graph_tab=SimpleNamespace(set_vehicle_vin=lambda _vin: None),
    )

    update_vehicle_context(window)
    assert window.sensor_capture.vehicle_context["vin"] is None
    assert tab_state == {1: False, 2: False}

def test_vehicle_management_helpers_are_available_from_app_module():
    from freerov3r.app import add_or_update_vehicle_action as app_add_vehicle
    from freerov3r.vehicle_management import add_or_update_vehicle

    assert app_add_vehicle is add_or_update_vehicle
    assert callable(add_or_update_vehicle)

def test_setup_flow_helper_is_available_from_app_module():
    from freerov3r.app import run_setup_wizard_flow as app_setup_flow
    from freerov3r.setup_flow import run_setup_wizard

    assert app_setup_flow is run_setup_wizard

def test_port_selection_helper_is_available_from_app_module():
    from freerov3r.app import refresh_serial_ports as app_refresh_ports
    from freerov3r.port_selection import refresh_serial_ports

    assert app_refresh_ports is refresh_serial_ports


def test_port_selection_prefers_one_recognized_adapter():
    global _QT_TEST_APP

    from PySide6.QtWidgets import QApplication, QComboBox, QLabel
    from types import SimpleNamespace

    from freerov3r.port_selection import refresh_serial_ports

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    channel = QComboBox()
    channel.setEditable(True)
    backend = QComboBox()
    backend.addItem("Virtual", ("virtual", ""))
    backend.addItem("ESP32", ("esp32", "COM3"))
    window = SimpleNamespace(
        channel_edit=channel,
        backend=backend,
        status=QLabel(),
    )
    ports = [{
        "device": "COM4",
        "label": "ESP32 CAN",
        "description": "USB serial",
        "vid": "303A",
        "pid": "1001",
        "kind": "esp32",
    }]

    refresh_serial_ports(window, discover=lambda: ports)
    assert channel.currentText() == "COM4"
    assert backend.currentData()[0] == "esp32"
    assert "COM4" in window.status.text()

    channel.deleteLater()
    backend.deleteLater()
    window.status.deleteLater()
    _QT_TEST_APP.processEvents()

def test_app_shell_keeps_optional_chart_capability_export():
    from freerov3r.app import HAS_CHARTS as app_has_charts
    from freerov3r.sensor_graph_tab import HAS_CHARTS

    assert app_has_charts is HAS_CHARTS

def test_main_window_constructs_without_hardware():
    global _QT_TEST_APP

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from freerov3r.app import MainWindow

    _QT_TEST_APP = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.tabs.count() >= 8
    assert "Sensors" not in [
        window.tabs.tabText(index) for index in range(window.tabs.count())
    ]
    assert "Sensors" not in window.quick_drawer.nav_buttons
    from PySide6.QtWidgets import QPushButton
    assert all(
        button.text() != "Collect sensor data"
        for button in window.stack.widget(0).findChildren(QPushButton)
    )
    assert window.receiver is None
    assert window.header_connection.text() == "● OFFLINE"
    assert window.research_tab.live_enabled is False
    assert window.backend.count() == 3

    window.rate_timer.stop()
    window.graph_tab.activity_timer.stop()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.DeferredDelete)
    _QT_TEST_APP.processEvents()

