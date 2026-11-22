from types import SimpleNamespace

from freerov3r.hardware import serial_ports


def test_normalize_port_info_includes_usb_identifiers():
    port = SimpleNamespace(
        device="COM5",
        description="USB-SERIAL CH340",
        hwid="USB VID:PID=1A86:7523",
        vid=0x1A86,
        pid=0x7523,
    )
    assert serial_ports.normalize_port_info(port) == {
        "device": "COM5",
        "description": "USB-SERIAL CH340",
        "hwid": "USB VID:PID=1A86:7523",
        "vid": "1A86",
        "pid": "7523",
    }


def test_normalize_port_info_handles_missing_metadata():
    result = serial_ports.normalize_port_info(SimpleNamespace(device="COM8"))
    assert result["device"] == "COM8"
    assert result["description"] == "Serial device"
    assert result["vid"] is None
    assert result["pid"] is None


def test_list_serial_ports_sorts_by_device(monkeypatch):
    ports = [
        SimpleNamespace(device="COM9", description="Second", hwid="x", vid=None, pid=None),
        SimpleNamespace(device="COM2", description="First", hwid="y", vid=None, pid=None),
    ]
    monkeypatch.setattr(serial_ports.list_ports, "comports", lambda: ports)
    assert [port["device"] for port in serial_ports.list_serial_ports()] == ["COM2", "COM9"]


def test_list_serial_ports_survives_enumeration_error(monkeypatch):
    def fail():
        raise OSError("port enumeration failed")
    monkeypatch.setattr(serial_ports.list_ports, "comports", fail)
    assert serial_ports.list_serial_ports() == []
