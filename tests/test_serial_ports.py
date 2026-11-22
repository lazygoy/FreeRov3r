from types import SimpleNamespace

from freerov3r.hardware.serial_ports import normalize_port_info


def test_normalize_port_info_includes_usb_identifiers():
    port = SimpleNamespace(
        device="COM5",
        description="USB-SERIAL CH340",
        hwid="USB VID:PID=1A86:7523",
        vid=0x1A86,
        pid=0x7523,
    )
    assert normalize_port_info(port) == {
        "device": "COM5",
        "description": "USB-SERIAL CH340",
        "hwid": "USB VID:PID=1A86:7523",
        "vid": "1A86",
        "pid": "7523",
    }


def test_normalize_port_info_handles_missing_metadata():
    port = SimpleNamespace(device="COM8")
    result = normalize_port_info(port)
    assert result["device"] == "COM8"
    assert result["description"] == "Serial device"
    assert result["vid"] is None
    assert result["pid"] is None
