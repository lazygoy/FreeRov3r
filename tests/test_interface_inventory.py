from freerov3r.hardware.interface_inventory import discover_all_interfaces
from freerov3r.hardware.j2534_discovery import J2534DeviceRegistration


def test_inventory_combines_serial_and_j2534_without_opening_devices():
    serial = [{
        "device": "COM4",
        "description": "USB serial",
        "hwid": "USB VID:PID=10C4:EA60",
        "vid": "10C4",
        "pid": "EA60",
        "kind": "esp32",
        "confidence": "possible",
        "label": "USB serial (ESP32 firmware candidate)",
    }]
    j2534 = [
        J2534DeviceRegistration(
            name="Mock VCI",
            vendor="Example",
            function_library=r"C:\\VCI\\driver.dll",
            api_version="04.04",
            registry_key="test",
        )
    ]
    inventory = discover_all_interfaces(
        serial_discover=lambda: serial,
        j2534_discover=lambda: j2534,
    )

    assert inventory[0] == serial[0]
    assert inventory[1]["kind"] == "j2534"
    assert inventory[1]["device"] == r"C:\\VCI\\driver.dll"
    assert inventory[1]["label"] == "J2534 Pass-Thru (04.04)"
    assert "Mock VCI" in inventory[1]["description"]


def test_inventory_returns_serial_devices_when_no_j2534_is_installed():
    serial = [{"device": "COM2", "kind": "serial"}]

    assert discover_all_interfaces(
        serial_discover=lambda: serial,
        j2534_discover=lambda: [],
    ) == serial


def test_inventory_returns_j2534_devices_when_no_serial_ports_exist():
    device = J2534DeviceRegistration(
        name="Standalone VCI",
        vendor="Vendor",
        function_library="vcidriver.dll",
        api_version="05.00",
        registry_key="test",
    )

    inventory = discover_all_interfaces(
        serial_discover=lambda: [],
        j2534_discover=lambda: [device],
    )

    assert len(inventory) == 1
    assert inventory[0]["kind"] == "j2534"
    assert inventory[0]["confidence"] == "registered"
