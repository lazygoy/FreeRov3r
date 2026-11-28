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
        SensorSample(1, "rpm", "RPM", 800, "", "simulated", metadata={"vin": "THIS"}, monotonic_timestamp=1),
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



def test_waterfall_caps_scene_at_eight_sensors_in_stable_name_order():
    samples = []
    for index in range(10):
        name = f"Sensor {index:02d}"
        samples.extend([
            sample(f"id_{index:02d}", name, index, 1),
            sample(f"id_{index:02d}", name, index + 1, 2),
        ])

    lanes = prepare_waterfall_lanes(samples, window_seconds=0)

    assert len(lanes) == 8
    assert [lane["sensor_id"] for lane in lanes] == [
        f"id_{index:02d}" for index in range(8)
    ]


def test_waterfall_retains_raw_engineering_values_for_cursor_readout():
    samples = [
        sample("rpm", "Engine speed", 825, 1, "rpm"),
        sample("rpm", "Engine speed", 1425, 2, "rpm"),
    ]

    lane = prepare_waterfall_lanes(samples, window_seconds=0)[0]

    assert lane["raw_points"] == [(0.0, 825.0), (1.0, 1425.0)]
    assert lane["minimum"] == 825
    assert lane["maximum"] == 1425



def test_waterfall_renderer_is_a_real_opengl_3d_view():
    from pyqtgraph.opengl import GLViewWidget

    from freerov3r.sensor_waterfall_gl import WaterfallPlot

    assert issubclass(WaterfallPlot, GLViewWidget)



def test_waterfall_cursor_data_keeps_full_resolution_when_surface_is_downsampled():
    samples = [
        sample("rpm", "Engine speed", value, timestamp)
        for timestamp, value in enumerate([800, 850, 900, 950, 1000, 1050], start=1)
    ]

    lane = prepare_waterfall_lanes(samples, window_seconds=0, max_points=2)[0]

    assert len(lane["points"]) <= 2
    assert lane["raw_points"] == [
        (float(index), float(value))
        for index, value in enumerate([800, 850, 900, 950, 1000, 1050])
    ]
    assert lane["raw_times"] == [point[0] for point in lane["raw_points"]]



def test_2d_scope_exposes_synchronized_cursor_signals():
    from PySide6.QtWidgets import QWidget

    from freerov3r.sensor_waterfall_2d import SharedCrosshairStackedPlot

    assert issubclass(SharedCrosshairStackedPlot, QWidget)
    assert hasattr(SharedCrosshairStackedPlot, "cursorMoved")
    assert hasattr(SharedCrosshairStackedPlot, "cursorLocked")


def test_2d_scope_cursor_uses_raw_engineering_values():
    from freerov3r.sensor_waterfall_2d import SharedCrosshairStackedPlot

    lane = {
        "raw_points": [(0.0, 800.0), (1.0, 1000.0), (2.0, 1200.0)],
        "raw_times": [0.0, 1.0, 2.0],
    }

    assert SharedCrosshairStackedPlot._nearest_value(lane, 0.2) == 800.0
    assert SharedCrosshairStackedPlot._nearest_value(lane, 1.7) == 1200.0
    assert SharedCrosshairStackedPlot._nearest_value(lane, 8.0) == 1200.0


def test_waterfall_renderer_has_ground_grid_without_extra_geometry_layers():
    import inspect

    from freerov3r.sensor_waterfall_gl import WaterfallPlot

    source = inspect.getsource(WaterfallPlot)
    assert "def _add_ground_plane" in source
    assert "self._ground_surface = floor" in source
    assert "_contour_items" not in source
    assert "_side_surface_items" not in source
    assert "_underside_items" not in source


def test_2d_sensor_names_use_horizontal_headers():
    import inspect

    from freerov3r.sensor_waterfall_2d import SharedCrosshairStackedPlot

    source = inspect.getsource(SharedCrosshairStackedPlot.set_lanes)
    assert "header = QLabel" in source
    assert 'setLabel("left"' not in source


def test_sensor_scope_defaults_to_3d_waterfall_and_fits_embedded_layout():
    import inspect

    from freerov3r.sensor_waterfall import SensorWaterfallDialog

    source = inspect.getsource(SensorWaterfallDialog.__init__)
    assert "setCurrentWidget(waterfall_page)" in source
    assert "self.setMinimumSize(0, 0)" in source



def test_waterfall_camera_fits_wide_viewport_instead_of_fixed_cube_scale():
    from freerov3r.sensor_waterfall_gl import camera_fit_distance

    wide = camera_fit_distance(1200, 600, 12.0, 2.0)
    square = camera_fit_distance(600, 600, 12.0, 2.0)
    many_lanes = camera_fit_distance(1200, 600, 12.0, 13.0)

    assert wide < square
    assert many_lanes > wide
    assert wide >= 4.0
