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

