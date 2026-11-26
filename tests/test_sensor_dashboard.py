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
