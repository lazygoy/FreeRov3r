import pytest

from freerov3r.sensors.presets import PRESET_GROUPS, build_sensor_preset


@pytest.mark.parametrize("name", list(PRESET_GROUPS))
def test_presets_only_select_signals_present_in_capture(name):
    available = {
        sensor_id
        for group in PRESET_GROUPS[name]
        for sensor_id in group
    }
    layout = build_sensor_preset(name, available)
    assert layout is not None
    assert layout["panel_count"] in (1, 2, 4)
    assert len(layout["panels"]) == 8
    selected = {
        sensor_id
        for panel in layout["panels"]
        for sensor_id in panel["sensor_ids"]
    }
    assert selected <= available


def test_preset_returns_none_when_no_matching_signals_are_captured():
    assert build_sensor_preset("Fuel trims", {"obd_0C", "obd_05"}) is None


def test_preset_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_sensor_preset("Invented OEM calibration", {"obd_0C"})
