import pytest
from freerov3r.hardware.interface_discovery import classify_serial_port
from freerov3r.hardware.elm327_serial_adapter import parse_elm_line

@pytest.mark.parametrize("port,expected", [
    ({"description": "Standard Serial over Bluetooth link"}, "elm327"),
    ({"description": "Silicon Labs CP210x USB to UART Bridge", "vid": "10C4", "pid": "EA60"}, "esp32"),
    ({"description": "USB CANable"}, "slcan"),
    ({"description": "USB Serial Device"}, "serial"),
])
def test_classify_serial_port(port, expected):
    assert classify_serial_port(port)[0] == expected

def test_parse_standard_elm_monitor_line():
    frame = parse_elm_line("7E8 03 41 0C 1A F8")
    assert frame is not None
    assert frame.arbitration_id == 0x7E8
    assert frame.data == bytes.fromhex("03 41 0C 1A F8")
    assert frame.is_extended_id is False

def test_parse_extended_elm_monitor_line():
    frame = parse_elm_line("18DAF110 03 41 0D 28")
    assert frame is not None
    assert frame.arbitration_id == 0x18DAF110
    assert frame.is_extended_id is True

def test_parse_elm_ignores_prompt_and_noise():
    assert parse_elm_line(">") is None
    assert parse_elm_line("SEARCHING...") is None
    assert parse_elm_line("garbage") is None