"""Read-only discovery of installed SAE J2534 Pass-Thru drivers.

Discovery reads the standard Windows registry registration only. It does not
load vendor DLLs, open a device, connect to a vehicle, or transmit messages.
The actual J2534 runtime belongs in a separate, explicitly opened adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, Iterable


J2534_REGISTRY_ROOTS = {
    "04.04": r"SOFTWARE\PassThruSupport.04.04",
    "05.00": r"SOFTWARE\PassThruSupport.05.00",
}


@dataclass(frozen=True)
class J2534DeviceRegistration:
    """A J2534 driver registration discovered in the local Windows registry."""

    name: str
    vendor: str
    function_library: str
    api_version: str
    registry_key: str
    config_application: str = ""


def _windows_registry_records() -> list[dict[str, str]]:
    """Read J2534 registrations from both 64-bit and 32-bit registry views."""
    if os.name != "nt":
        return []

    try:
        import winreg
    except ImportError:
        return []

    records: list[dict[str, str]] = []
    views = [getattr(winreg, "KEY_WOW64_64KEY", 0),
             getattr(winreg, "KEY_WOW64_32KEY", 0)]
    seen: set[tuple[str, str]] = set()

    for api_version, root in J2534_REGISTRY_ROOTS.items():
        for view in views:
            try:
                root_key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    root,
                    0,
                    winreg.KEY_READ | view,
                )
            except OSError:
                continue

            with root_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root_key, index)
                    except OSError:
                        break
                    index += 1
                    identity = (api_version, subkey_name.casefold())
                    if identity in seen:
                        continue
                    seen.add(identity)

                    try:
                        device_key = winreg.OpenKey(root_key, subkey_name)
                    except OSError:
                        continue
                    with device_key:
                        values: dict[str, str] = {}
                        for value_name in (
                            "Name",
                            "Vendor",
                            "FunctionLibrary",
                            "ConfigApplication",
                        ):
                            try:
                                value, _value_type = winreg.QueryValueEx(
                                    device_key, value_name
                                )
                            except OSError:
                                value = ""
                            values[value_name] = (
                                value if isinstance(value, str) else ""
                            )
                    records.append({
                        "name": values["Name"],
                        "vendor": values["Vendor"],
                        "function_library": values["FunctionLibrary"],
                        "config_application": values["ConfigApplication"],
                        "api_version": api_version,
                        "registry_key": root + chr(92) + subkey_name,
                    })
    return records


def discover_j2534_devices(
    registry_reader: Callable[[], Iterable[dict[str, str]]] | None = None,
) -> list[J2534DeviceRegistration]:
    """Return installed J2534 registrations without loading or opening them.

    registry_reader is an injection point for tests and platform-specific
    discovery. Records missing a name or FunctionLibrary are ignored because
    they cannot identify a usable Pass-Thru driver registration.
    """
    reader = registry_reader or _windows_registry_records
    devices: list[J2534DeviceRegistration] = []
    seen: set[tuple[str, str]] = set()

    for record in reader():
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or "").strip()
        library = str(record.get("function_library") or "").strip()
        if not name or not library:
            continue

        api_version = str(record.get("api_version") or "").strip()
        registry_key = str(record.get("registry_key") or "").strip()
        identity = (api_version, library.casefold())
        if identity in seen:
            continue
        seen.add(identity)

        devices.append(J2534DeviceRegistration(
            name=name,
            vendor=str(record.get("vendor") or "").strip(),
            function_library=library,
            api_version=api_version,
            registry_key=registry_key,
            config_application=str(
                record.get("config_application") or ""
            ).strip(),
        ))

    return sorted(
        devices,
        key=lambda device: (
            device.name.casefold(),
            device.api_version,
            device.function_library.casefold(),
        ),
    )
