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
