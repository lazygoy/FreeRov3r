from PySide6.QtWidgets import QApplication, QMainWindow

from freerov3r.ui_feedback import QuickDrawer


def test_quick_drawer_filters_workspace_buttons_and_recovers():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    destinations = []
    drawer = QuickDrawer(window, destinations.append)

    drawer.nav_search.setText("obd")
    assert drawer.nav_buttons["OBD-II"].isHidden() is False
    assert drawer.nav_buttons["Home"].isHidden() is True
    assert drawer.nav_empty_label.isHidden() is True

    drawer.nav_buttons["OBD-II"].click()
    assert destinations == ["OBD-II"]

    drawer.nav_search.setText("no such workspace")
    assert all(button.isHidden() for button in drawer.nav_buttons.values())
    assert drawer.nav_empty_label.isHidden() is False

    drawer.nav_search.clear()
    assert all(not button.isHidden() for button in drawer.nav_buttons.values())
    assert drawer.nav_empty_label.isHidden() is True

    drawer.deleteLater()
    window.close()
