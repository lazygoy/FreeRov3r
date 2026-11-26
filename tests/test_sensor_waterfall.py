import pytest

from freerov3r.sensors.models import SensorSample
from freerov3r.sensor_waterfall import prepare_waterfall_lanes


def sample(sensor_id, name, value, timestamp, unit=""):
    return SensorSample(timestamp, sensor_id, name, value, unit, "simulated",
                        monotonic_timestamp=timestamp)


def test_waterfall_builds_separate_sensor_lanes_with_native_ranges():
    samples = [
        sample("rpm", "Engine speed", 800, 1, "rpm"),
        sample("rpm", "Engine speed", 1200, 2, "rpm"),
        sample("temp", "Coolant", 80, 1, "°C"),
        sample("temp", "Coolant", 90, 2, "°C"),
    ]
    lanes = prepare_waterfall_lanes(samples, window_seconds=0)

    assert [lane["sensor_id"] for lane in lanes] == ["temp", "rpm"] or {
        lane["sensor_id"] for lane in lanes
    } == {"rpm", "temp"}
    by_id = {lane["sensor_id"]: lane for lane in lanes}
    assert (by_id["rpm"]["minimum"], by_id["rpm"]["maximum"]) == (800, 1200)
    assert by_id["rpm"]["unit"] == "rpm"
    assert by_id["temp"]["current"] == 90


def test_waterfall_normalized_mode_maps_each_sensor_to_zero_to_one_hundred():
    samples = [
        sample("rpm", "RPM", 800, 1),
        sample("rpm", "RPM", 1200, 2),
        sample("temp", "Coolant", 20, 1),
        sample("temp", "Coolant", 40, 2),
    ]
    lanes = prepare_waterfall_lanes(samples, window_seconds=0, scale_mode="normalized")
    assert all(lane["points"][0][1] == 0 for lane in lanes)
    assert all(lane["points"][-1][1] == 100 for lane in lanes)


def test_waterfall_filters_selection_vin_quality_and_non_finite_values():
    samples = [
        sample("rpm", "RPM", 800, 1),
        SensorSample(2, "temp", "Coolant", 80, "C", "ecu",
                     metadata={"vin": "OTHER"}),
        SensorSample(3, "bad", "Bad", float("nan"), "", "ecu"),
        SensorSample(4, "invalid", "Invalid", 2, "", "ecu", quality="invalid"),
    ]
    lanes = prepare_waterfall_lanes(samples, selected_ids={"rpm", "temp", "bad", "invalid"},
                                    window_seconds=0, vin="THIS")
    assert [lane["sensor_id"] for lane in lanes] == ["rpm"]


def test_waterfall_time_window_excludes_old_samples():
    samples = [sample("rpm", "RPM", value, timestamp) for value, timestamp in
               [(500, 1), (700, 8), (900, 10)]]
    lanes = prepare_waterfall_lanes(samples, window_seconds=3)
    assert lanes[0]["minimum"] == 700
    assert lanes[0]["maximum"] == 900


def test_waterfall_downsampling_preserves_local_minimum_and_maximum():
    samples = [sample("rpm", "RPM", value, timestamp) for timestamp, value in
               enumerate([1, 2, 100, 3, 4, 5, 6, 7, 8, 9], start=1)]
    lanes = prepare_waterfall_lanes(samples, window_seconds=0, max_points=4)
    values = [value for _, value in lanes[0]["points"]]
    assert max(values) == 1.0
