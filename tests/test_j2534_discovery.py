from freerov3r.hardware.j2534_discovery import (
    J2534DeviceRegistration,
    discover_j2534_devices,
)


def test_discovery_returns_registered_devices_without_opening_them():
    records = [
        {
            "name": "Example Pass-Thru",
            "vendor": "Example Vendor",
            "function_library": r"C:\\Drivers\\example.dll",
            "api_version": "04.04",
            "registry_key": r"SOFTWARE\\PassThruSupport.04.04\\Example",
            "config_application": r"C:\\Drivers\\configure.exe",
        }
    ]

    devices = discover_j2534_devices(registry_reader=lambda: records)

    assert devices == [
        J2534DeviceRegistration(
            name="Example Pass-Thru",
            vendor="Example Vendor",
            function_library=r"C:\\Drivers\\example.dll",
            api_version="04.04",
            registry_key=r"SOFTWARE\\PassThruSupport.04.04\\Example",
            config_application=r"C:\\Drivers\\configure.exe",
        )
    ]


def test_discovery_ignores_incomplete_registry_entries():
    records = [
        {"name": "Missing DLL", "function_library": ""},
        {"name": "", "function_library": r"C:\\Drivers\\unnamed.dll"},
        {"vendor": "No device identity", "function_library": r"C:\\Drivers\\unknown.dll"},
    ]

    assert discover_j2534_devices(registry_reader=lambda: records) == []


def test_discovery_deduplicates_same_api_and_library_case_insensitively():
    records = [
        {
            "name": "Pass-Thru",
            "function_library": r"C:\\Drivers\\device.dll",
            "api_version": "04.04",
        },
        {
            "name": "Pass-Thru duplicate",
            "function_library": r"c:\\drivers\\DEVICE.DLL",
            "api_version": "04.04",
        },
        {
            "name": "New API registration",
            "function_library": r"C:\\Drivers\\device.dll",
            "api_version": "05.00",
        },
    ]

    devices = discover_j2534_devices(registry_reader=lambda: records)

    assert len(devices) == 2
    assert {device.api_version for device in devices} == {"04.04", "05.00"}


def test_discovery_sorts_devices_for_stable_ui_display():
    records = [
        {"name": "Zulu", "function_library": "z.dll", "api_version": "04.04"},
        {"name": "Alpha", "function_library": "a.dll", "api_version": "04.04"},
    ]

    devices = discover_j2534_devices(registry_reader=lambda: records)

    assert [device.name for device in devices] == ["Alpha", "Zulu"]


def test_discovery_does_not_call_reader_more_than_once():
    calls = []

    def reader():
        calls.append(True)
        return []

    assert discover_j2534_devices(registry_reader=reader) == []
    assert len(calls) == 1
