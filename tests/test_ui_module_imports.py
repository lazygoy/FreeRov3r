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
    assert tab.stats_table.rowCount() == 0
    assert tab.activity_timer.isActive()

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

