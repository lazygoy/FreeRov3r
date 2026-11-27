import pytest

from freerov3r.sensor_dashboard import (
    PANEL_COUNTS,
    normalize_dashboard_layout,
    panel_grid_dimensions,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, (1, 1)),
        (2, (2, 1)),
        (4, (2, 2)),
        (6, (2, 3)),
        (8, (2, 4)),
    ],
)
def test_panel_grid_dimensions(count, expected):
    assert panel_grid_dimensions(count) == expected


@pytest.mark.parametrize("count", [0, 3, 5, 7, 9, 10])
def test_panel_grid_dimensions_rejects_unsupported_counts(count):
    with pytest.raises(ValueError, match="panel count"):
        panel_grid_dimensions(count)


def test_dashboard_panel_counts_are_ordered_and_capped_at_eight():
    assert PANEL_COUNTS == (1, 2, 4, 6, 8)


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
    assert len(layout["panels"]) == 8


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


def test_dashboard_favorite_and_persistence_methods_belong_to_dock():
    from freerov3r.sensor_dashboard import SensorDashboardDock

    assert callable(getattr(SensorDashboardDock, "_refresh_favorites", None))
    assert callable(getattr(SensorDashboardDock, "_favorite_selection_changed", None))
    assert callable(getattr(SensorDashboardDock, "persist_layout", None))
    assert callable(getattr(SensorDashboardDock, "_restore_saved_layout", None))
    assert callable(getattr(SensorDashboardDock, "load_favorite", None))
    assert callable(getattr(SensorDashboardDock, "save_layout_to_favorite", None))


@pytest.fixture
def qapp(monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_dashboard_initializes_persists_and_loads_sensor_favorites(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    favorite_layout = {
        "panel_count": 2,
        "panels": [
            {"sensor_ids": ["obd_0C"], "window_seconds": 10, "auto_scale": False},
            {"sensor_ids": ["obd_05"], "window_seconds": 300, "auto_scale": True},
        ],
    }
    settings = {
        "obd_pid_favorites": {"Engine": ["obd_0C", "obd_05"]},
        "sensor_dashboard_favorites": {"Engine": favorite_layout},
        "sensor_dashboard_layout": favorite_layout,
    }
    saved = []
    dock = SensorDashboardDock(
        SimpleNamespace(samples=[]),
        settings=settings,
        save_settings_callback=lambda value: saved.append(dict(value)),
    )

    assert dock.panel_count.currentData() == 2
    assert dock.panels[0].selected_sensor_ids() == {"obd_0C"}
    assert dock.panels[1].selected_sensor_ids() == {"obd_05"}
    assert dock.favorite_combo.findData("Engine") >= 0

    dock.favorite_combo.setCurrentIndex(dock.favorite_combo.findData("Engine"))
    dock.load_favorite()
    dock.save_layout_to_favorite()
    dock.persist_layout()

    assert settings["sensor_dashboard_favorites"]["Engine"]["panel_count"] == 2
    assert saved

    restored = SensorDashboardDock(SimpleNamespace(samples=[]), settings=settings)
    assert restored.panel_count.currentData() == 2
    assert restored.panels[0].selected_sensor_ids() == {"obd_0C"}
    assert restored.panels[1].selected_sensor_ids() == {"obd_05"}

    restored.close()
    dock.close()


def test_legacy_sensor_favorite_loads_into_first_graph(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    settings = {"obd_pid_favorites": {"Idle test": ["obd_0C", "obd_05"]}}
    dock = SensorDashboardDock(SimpleNamespace(samples=[]), settings=settings)
    dock.favorite_combo.setCurrentIndex(dock.favorite_combo.findData("Idle test"))
    dock.load_favorite()

    assert dock.panel_count.currentData() == 1
    assert dock.panels[0].selected_sensor_ids() == {"obd_0C", "obd_05"}
    assert all(not panel.selected_sensor_ids() for panel in dock.panels[1:])

    dock.close()



def test_graph_panel_popout_and_close_restore_widget_parent(qapp):
    from types import SimpleNamespace

    from freerov3r.sensor_dashboard import SensorDashboardDock

    dock = SensorDashboardDock(SimpleNamespace(samples=[]))
    panel = dock.panels[0]

    panel.popout_button.click()
    qapp.processEvents()
    host = panel._floating_host
    assert host is not None
    assert host.isWindow()
    assert host.isVisible()
    assert panel.parent() is host
    assert not panel.isHidden()

    host.close()
    qapp.processEvents()

    assert panel._floating_host is None
    assert panel.parent() is dock.grid_host
    assert not panel.isHidden()
    dock.close()
