import pytest

from freerov3r.sensor_dashboard import (
    PANEL_COUNTS,
    normalize_dashboard_layout,
    panel_grid_dimensions,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, (1, 1)), (2, (2, 1)), (4, (2, 2))],
)
def test_panel_grid_dimensions(count, expected):
    assert panel_grid_dimensions(count) == expected


@pytest.mark.parametrize("count", [0, 3, 5, 6, 8, 9])
def test_panel_grid_dimensions_rejects_unsupported_counts(count):
    with pytest.raises(ValueError, match="panel count"):
        panel_grid_dimensions(count)


def test_dashboard_panel_counts_are_ordered_and_capped_at_four():
    assert PANEL_COUNTS == (1, 2, 4)


def test_normalize_dashboard_layout_preserves_independent_panel_settings():
    layout = normalize_dashboard_layout({
        "panel_count": 2,
        "panels": [
            {"sensor_ids": ["obd_0C", "obd_0D"], "window_seconds": 10, "auto_scale": False},
            {"sensor_ids": ["coolant_temp"], "window_seconds": 300, "auto_scale": True},
        ],
    })

    assert layout["panel_count"] == 2
    assert layout["panels"][0] == {
        "sensor_ids": ["obd_0C", "obd_0D"],
        "window_seconds": 10,
        "auto_scale": False,
    }
    assert layout["panels"][1] == {
        "sensor_ids": ["coolant_temp"],
        "window_seconds": 300,
        "auto_scale": True,
    }
    assert len(layout["panels"]) == 4


def test_normalize_dashboard_layout_handles_legacy_favorite_without_layout():
    layout = normalize_dashboard_layout({"sensor_ids": ["obd_0C"]})

    assert layout["panel_count"] == 4
    assert all(not panel["sensor_ids"] for panel in layout["panels"])


def test_normalize_dashboard_layout_sanitizes_invalid_settings():
    layout = normalize_dashboard_layout({
        "panel_count": 3,
        "panels": [
            {"sensor_ids": ["obd_0C", None, "", "obd_0C"], "window_seconds": 999, "auto_scale": 0},
            "invalid panel",
        ],
    })

    assert layout["panel_count"] == 4
    assert layout["panels"][0] == {
        "sensor_ids": ["obd_0C"],
        "window_seconds": 60,
        "auto_scale": False,
    }
    assert layout["panels"][1] == {
        "sensor_ids": [],
        "window_seconds": 60,
        "auto_scale": True,
    }


def test_dashboard_exposes_picker_and_embedded_scope_controls():
    from freerov3r.sensor_dashboard import SensorDashboardDock

    assert callable(getattr(SensorDashboardDock, "choose_sensors", None))
    assert callable(getattr(SensorDashboardDock, "set_selected_sensor_ids", None))
    assert callable(getattr(SensorDashboardDock, "persist_layout", None))
    assert callable(getattr(SensorDashboardDock, "_restore_saved_layout", None))


@pytest.fixture
def qapp(monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_dashboard_initializes_and_persists_four_way_layout(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    layout = {
        "panel_count": 2,
        "panels": [
            {"sensor_ids": ["obd_0C"], "window_seconds": 10, "auto_scale": False},
            {"sensor_ids": ["obd_05"], "window_seconds": 300, "auto_scale": True},
        ],
    }
    settings = {"sensor_dashboard_layout": layout}
    saved = []
    dashboard = SensorDashboardDock(
        SimpleNamespace(samples=[]),
        settings=settings,
        save_settings_callback=lambda value: saved.append(dict(value)),
    )

    assert dashboard.panel_count.currentData() == 2
    assert dashboard.panels[0].selected_sensor_ids() == {"obd_0C"}
    assert dashboard.panels[1].selected_sensor_ids() == {"obd_05"}
    assert not hasattr(dashboard.panels[0], "popout_button")
    assert dashboard.panels[0].sensor_list.isHidden()

    dashboard.panel_count.setCurrentIndex(dashboard.panel_count.findData(4))
    dashboard.persist_layout()
    assert settings["sensor_dashboard_layout"]["panel_count"] == 4
    assert saved

    restored = SensorDashboardDock(SimpleNamespace(samples=[]), settings=settings)
    assert restored.panel_count.currentData() == 4
    restored.close()
    dashboard.close()


def test_obd_selection_sync_targets_first_graph(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    dashboard = SensorDashboardDock(SimpleNamespace(samples=[]))
    dashboard.set_selected_sensor_ids({"obd_0C", "obd_05"})

    assert dashboard.panels[0].selected_sensor_ids() == {"obd_0C", "obd_05"}
    assert all(not panel.selected_sensor_ids() for panel in dashboard.panels[1:])
    dashboard.close()


def test_graph_tab_has_no_sensor_health_panel(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_graph_tab import SensorGraphTab

    tab = SensorGraphTab(SimpleNamespace(samples=[]))
    assert not hasattr(tab, "stats_table")
    assert not hasattr(tab, "chart")
    tab.activity_timer.stop()
    tab.close()



def test_waterfall_switch_stays_inside_dashboard(qapp):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QDialog, QWidget
    from freerov3r.sensor_dashboard import SensorDashboardDock

    dashboard = SensorDashboardDock(SimpleNamespace(samples=[]))

    # Waterfall is the default page, and the traditional 2D dashboard remains
    # available without destroying or recreating the OpenGL-backed widget.
    waterfall = dashboard._waterfall_widget
    assert waterfall is not None
    assert dashboard.view_stack.currentWidget() is waterfall
    assert dashboard.waterfall_button.text() == "Back to Graphs"
    assert waterfall.parentWidget() is dashboard.view_stack
    assert dashboard.view_stack.indexOf(waterfall) >= 0
    assert isinstance(waterfall, QWidget)
    assert not isinstance(waterfall, QDialog)

    dashboard.open_waterfall()
    assert dashboard.view_stack.currentWidget() is dashboard.grid_host
    assert dashboard.waterfall_button.text() == "2D / 3D View"

    dashboard.open_waterfall()
    assert dashboard.view_stack.currentWidget() is waterfall
    assert dashboard.waterfall_button.text() == "Back to Graphs"
    assert dashboard._waterfall_widget is waterfall
    assert waterfall.parentWidget() is dashboard.view_stack
    dashboard.close()


def test_first_run_defaults_to_four_engine_obd_signals(qapp):
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from freerov3r.sensor_dashboard import DEFAULT_GRAPH_SENSOR_IDS, SensorDashboardDock

    dashboard = SensorDashboardDock(SimpleNamespace(samples=[]))

    assert dashboard.panel_count.currentData() == 4
    assert [panel.selected_sensor_ids() for panel in dashboard.panels] == [
        {sensor_id} for sensor_id in DEFAULT_GRAPH_SENSOR_IDS
    ]
    waterfall_selected = {
        dashboard._waterfall_widget.sensor_list.item(i).data(Qt.UserRole)
        for i in range(dashboard._waterfall_widget.sensor_list.count())
        if dashboard._waterfall_widget.sensor_list.item(i).checkState() == Qt.Checked
    }
    assert waterfall_selected == set(DEFAULT_GRAPH_SENSOR_IDS)
    dashboard.close()


def test_first_run_defaults_do_not_override_saved_empty_layout(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    settings = {"sensor_dashboard_layout": {"panel_count": 2, "panels": []}}
    dashboard = SensorDashboardDock(SimpleNamespace(samples=[]), settings=settings)

    assert dashboard.panel_count.currentData() == 2
    assert all(not panel.selected_sensor_ids() for panel in dashboard.panels)
    dashboard.close()
