from freerov3r.diagnostics.obd2 import OBD_PIDS, decode_mode01
from freerov3r.models import CanFrame


def test_pid_table_is_vehicle_independent_and_contains_supported_pids():
    pids = {pid for pid, _, _ in OBD_PIDS}
    assert {"04", "05", "0C", "0D", "1F", "21", "42", "5C"} <= pids


def test_decode_engine_rpm():
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x0C, 0x1A, 0xF8, 0, 0, 0]))
    decoded = decode_mode01(frame)
    assert decoded[0] == 0x0C
    assert decoded[1] == "Engine speed"
    assert decoded[2] == 1726.0
    assert decoded[3] == "rpm"


def test_decode_run_time_and_mil_distance():
    runtime = CanFrame(0x7E8, bytes([4, 0x41, 0x1F, 0x00, 0x3C, 0, 0, 0]))
    distance = CanFrame(0x7E8, bytes([4, 0x41, 0x21, 0x01, 0x2C, 0, 0, 0]))
    assert decode_mode01(runtime)[2] == 60.0
    assert decode_mode01(distance)[2] == 300.0


def test_reject_non_obd_response_frames():
    assert decode_mode01(CanFrame(0x123, bytes([4, 0x41, 0x0C, 0, 0]))) is None
    assert decode_mode01(CanFrame(0x7E8, bytes([4, 0x42, 0x0C, 0, 0]))) is None


import pytest

from freerov3r.diagnostics.obd2 import PID_CATEGORIES, PID_DEFINITIONS, search_mode01_pids


@pytest.mark.parametrize(
    ("pid", "a", "b", "expected"),
    [
        (0x06, 0xC0, 0x00, 50.0),
        (0x07, 0x40, 0x00, -50.0),
        (0x08, 0x80, 0x00, 0.0),
        (0x09, 0xFF, 0x00, 99.21875),
        (0x0A, 10, 0, 30.0),
        (0x0E, 128, 0, 0.0),
        (0x22, 1, 0, 20.224),
        (0x23, 1, 2, 2580.0),
        (0x2C, 128, 0, 12800.0 / 255.0),
        (0x2D, 128, 0, 0.0),
        (0x2E, 255, 0, 100.0),
        (0x30, 5, 0, 5.0),
        (0x31, 1, 2, 258.0),
        (0x33, 100, 0, 100.0),
        (0x3C, 1, 144, 0.0),
        (0x3D, 3, 232, 60.0),
        (0x3E, 1, 144, 0.0),
        (0x3F, 3, 232, 60.0),
        (0x4C, 128, 0, 12800.0 / 255.0),
        (0x4D, 1, 2, 258.0),
        (0x4E, 3, 4, 772.0),
        (0x52, 128, 0, 12800.0 / 255.0),
        (0x53, 1, 0, 1.28),
        (0x55, 128, 0, 0.0),
        (0x56, 0, 0, -100.0),
        (0x57, 255, 0, 99.21875),
        (0x58, 64, 0, -50.0),
        (0x59, 1, 2, 2580.0),
        (0x5A, 128, 0, 12800.0 / 255.0),
        (0x5B, 255, 0, 100.0),
        (0x5D, 1, 0, -208.0),
        (0x5E, 1, 0, 12.8),
    ],
)
def test_decode_added_mode01_pid_scaling(pid, a, b, expected):
    frame = CanFrame(0x7E8, bytes([4, 0x41, pid, a, b, 0, 0, 0]))
    decoded = decode_mode01(frame)
    assert decoded is not None
    assert decoded[0] == pid
    assert decoded[2] == pytest.approx(expected)


def test_every_numeric_pid_has_category_and_search_terms():
    from freerov3r.diagnostics.obd2 import PID_SEARCH_TERMS

    assert set(PID_DEFINITIONS) == set(PID_CATEGORIES)
    assert set(PID_DEFINITIONS) == set(PID_SEARCH_TERMS)


def test_search_finds_new_fuel_trim_and_catalyst_pids():
    assert {row[0] for row in search_mode01_pids("long term trim bank two")} == {"09"}
    assert {row[0] for row in search_mode01_pids("catalytic temperature", "Temperatures")} == {
        "3C", "3D", "3E", "3F"
    }


def test_two_byte_mode01_pid_rejects_truncated_response():
    frame = CanFrame(0x7E8, bytes([3, 0x41, 0x23, 0x01]))
    assert decode_mode01(frame) is None


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (0x80, 0x00, -32768.0),
        (0x7F, 0xFF, 32767.0),
        (0xFF, 0xFF, -1.0),
        (0x00, 0x00, 0.0),
    ],
)
def test_evap_vapor_pressure_pid_54_uses_signed_16_bit_value(a, b, expected):
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x54, a, b, 0, 0, 0]))
    decoded = decode_mode01(frame)
    assert decoded is not None
    assert decoded[0] == 0x54
    assert decoded[2] == expected
    assert decoded[3] == "Pa"


def test_catalyst_temperature_pid_bank_and_sensor_labels_match_j1979():
    assert PID_DEFINITIONS[0x3C][0] == "Catalyst temperature bank 1 sensor 1"
    assert PID_DEFINITIONS[0x3D][0] == "Catalyst temperature bank 2 sensor 1"
    assert PID_DEFINITIONS[0x3E][0] == "Catalyst temperature bank 1 sensor 2"
    assert PID_DEFINITIONS[0x3F][0] == "Catalyst temperature bank 2 sensor 2"


def test_pid_59_is_distinguished_as_absolute_fuel_rail_pressure():
    assert PID_DEFINITIONS[0x59] == ("Fuel rail absolute pressure", "kPa")
    assert {row[0] for row in search_mode01_pids("absolute fuel rail pressure")} == {"59"}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (0x80, 0x00, -8192.0),
        (0x7F, 0xFF, 8191.75),
        (0xFF, 0xFF, -0.25),
        (0x00, 0x00, 0.0),
    ],
)
def test_evap_system_vapor_pressure_pid_32_uses_signed_quarter_pascal_value(a, b, expected):
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x32, a, b, 0, 0, 0]))
    decoded = decode_mode01(frame)
    assert decoded is not None
    assert decoded[0] == 0x32
    assert decoded[2] == expected
    assert decoded[3] == "Pa"

from freerov3r.diagnostics.obd2 import decode_mode01_measurements, PID_MULTI_VALUE_KEYS


@pytest.mark.parametrize(
    ("pid", "a", "b", "expected_voltage", "expected_trim"),
    [
        (0x14, 100, 128, 0.5, 0.0),
        (0x15, 200, 0, 1.0, -100.0),
        (0x1B, 255, 255, 1.275, None),
    ],
)
def test_decode_narrowband_oxygen_sensor_returns_independent_values(
    pid, a, b, expected_voltage, expected_trim
):
    frame = CanFrame(0x7E8, bytes([4, 0x41, pid, a, b, 0, 0, 0]))
    measurements = decode_mode01_measurements(frame)
    assert measurements[0][0:2] == (pid, "voltage")
    assert measurements[0][3] == pytest.approx(expected_voltage)
    if expected_trim is None:
        assert len(measurements) == 1
    else:
        assert measurements[1][0:2] == (pid, "fuel_trim")
        assert measurements[1][3] == pytest.approx(expected_trim)


@pytest.mark.parametrize(
    ("pid", "expected_keys", "expected_second_unit", "expected_second_value"),
    [
        (0x24, ("lambda", "voltage"), "V", 4.0),
        (0x34, ("lambda", "current"), "mA", 0.0),
    ],
)
def test_decode_wideband_oxygen_sensor_keeps_lambda_and_electrical_value_separate(
    pid, expected_keys, expected_second_unit, expected_second_value
):
    frame = CanFrame(0x7E8, bytes([6, 0x41, pid, 0x40, 0x00, 0x80, 0x00, 0]))
    measurements = decode_mode01_measurements(frame)
    assert tuple(item[1] for item in measurements) == expected_keys
    assert measurements[0][3] == pytest.approx(0.5)
    assert measurements[1][3] == pytest.approx(expected_second_value)
    assert measurements[1][4] == expected_second_unit


def test_multi_value_pid_rejects_truncated_wideband_payload():
    frame = CanFrame(0x7E8, bytes([6, 0x41, 0x24, 0x40, 0x00, 0x80]))
    assert decode_mode01_measurements(frame) == []


def test_legacy_scalar_decoder_remains_available_for_multi_value_pid():
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x14, 100, 128, 0, 0, 0]))
    assert decode_mode01(frame)[2] == pytest.approx(0.5)
    assert PID_MULTI_VALUE_KEYS[0x14] == ("voltage", "fuel_trim")


def test_secondary_oxygen_trim_pid_exposes_both_bank_values():
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x55, 128, 192, 0, 0, 0]))
    measurements = decode_mode01_measurements(frame)
    assert [(item[1], item[3]) for item in measurements] == [
        ("bank_1", 0.0), ("bank_3", 50.0)
    ]
