"""Unified passive inventory of serial and installed J2534 interfaces."""

from .interface_discovery import discover_interfaces
from .j2534_discovery import discover_j2534_devices


def discover_all_interfaces(
    serial_discover=discover_interfaces,
    j2534_discover=discover_j2534_devices,
):
    """Return normalized serial ports and registered J2534 devices.

    Both discovery paths are passive. J2534 DLLs are not loaded and no
    hardware channel is opened. The returned `device` value for J2534 is
    the registered FunctionLibrary path, used only after explicit selection.
    """
    found = list(serial_discover())
    for registration in j2534_discover():
        found.append({
            "device": registration.function_library,
            "description": (
                f"{registration.name} | {registration.vendor or 'Unknown vendor'}"
            ),
            "hwid": "J2534 registry registration",
            "vid": "",
            "pid": "",
            "kind": "j2534",
            "confidence": "registered",
            "label": (
                f"J2534 Pass-Thru ({registration.api_version})"
                if registration.api_version else "J2534 Pass-Thru"
            ),
        })
    return found
