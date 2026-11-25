"""Vehicle-independent SAE J1979 OBD-II Mode 01 PID definitions and decoding.

This module only decodes observed response frames. Active PID requests are a
separate transport capability and are not implied by having a PID definition.
"""
from ..models import CanFrame


PID_DEFINITIONS = {
    0x04: ("Calculated engine load", "%"),
    0x05: ("Engine coolant temperature", "°C"),
    0x0B: ("Intake manifold pressure", "kPa"),
    0x0C: ("Engine speed", "rpm"),
    0x0D: ("Vehicle speed", "km/h"),
    0x0F: ("Intake air temperature", "°C"),
    0x10: ("MAF air flow", "g/s"),
    0x11: ("Throttle position", "%"),
    0x1F: ("Run time since engine start", "s"),
    0x21: ("Distance traveled with MIL on", "km"),
    0x2F: ("Fuel tank level", "%"),
    0x42: ("Control module voltage", "V"),
    0x46: ("Ambient air temperature", "°C"),
    0x5C: ("Engine oil temperature", "°C"),
}

# Categories are navigation aids, not claims that a particular vehicle supports
# the PID. Support must be discovered from the responding ECU.
PID_CATEGORIES = {
    0x04: "Engine",
    0x05: "Temperatures",
    0x0B: "Air & Intake",
    0x0C: "Engine",
    0x0D: "Vehicle",
    0x0F: "Temperatures",
    0x10: "Air & Intake",
    0x11: "Engine",
    0x1F: "Engine",
    0x21: "Emissions",
    0x2F: "Fuel",
    0x42: "Electrical",
    0x46: "Temperatures",
    0x5C: "Temperatures",
}

PID_SEARCH_TERMS = {
    0x04: "load engine load calculated torque",
    0x05: "coolant water temperature engine ect",
    0x0B: "map manifold absolute pressure boost intake",
    0x0C: "rpm revs revolutions engine speed",
    0x0D: "speed road vehicle speed",
    0x0F: "iat intake air temperature",
    0x10: "maf mass air flow airflow",
    0x11: "throttle tps accelerator position",
    0x1F: "runtime run time engine start",
    0x21: "mil emissions distance check engine light",
    0x2F: "fuel tank level fuel",
    0x42: "voltage battery charging electrical module",
    0x46: "ambient outside air temperature",
    0x5C: "oil temperature engine lubricant",
}

PID_CATEGORIES_ALL = ("All", "Engine", "Temperatures", "Air & Intake",
                      "Fuel", "Emissions", "Electrical", "Vehicle")


def search_mode01_pids(query="", category="All"):
    """Return searchable PID rows as (hex_pid, name, unit, category).

    Search covers PID number, displayed name, unit, category and common
    workshop terminology. It does not imply that a PID is supported.
    """
    needle = str(query or "").strip().casefold()
    rows = []
    for pid, (name, unit) in PID_DEFINITIONS.items():
        group = PID_CATEGORIES.get(pid, "Other")
        if category not in (None, "", "All") and group != category:
            continue
        haystack = " ".join((
            f"{pid:02X}", name, unit, group, PID_SEARCH_TERMS.get(pid, "")
        )).casefold()
        if needle and needle not in haystack:
            continue
        rows.append((f"{pid:02X}", name, unit, group))
    return rows


OBD_PIDS = [
    (f"{pid:02X}", name, unit)
    for pid, (name, unit) in PID_DEFINITIONS.items()
]


def decode_mode01(frame: CanFrame):
    """Return (pid, name, value, unit) for a supported 11-bit CAN response."""
    data = frame.data
    if frame.is_extended_id or not 0x7E8 <= frame.arbitration_id <= 0x7EF:
        return None
    if len(data) < 4 or data[1] != 0x41:
        return None
    pid = data[2]
    if pid not in PID_DEFINITIONS:
        return None
    if pid in (0x0C, 0x10, 0x1F, 0x21, 0x42) and len(data) < 5:
        return None
    a, b = data[3], data[4] if len(data) > 4 else 0
    name, unit = PID_DEFINITIONS[pid]
    if pid == 0x04 or pid == 0x11 or pid == 0x2F:
        value = a * 100.0 / 255.0
    elif pid in (0x05, 0x0F, 0x46, 0x5C):
        value = a - 40.0
    elif pid == 0x0B or pid == 0x0D:
        value = float(a)
    elif pid == 0x0C:
        value = (a * 256 + b) / 4.0
    elif pid == 0x10:
        value = (a * 256 + b) / 100.0
    elif pid == 0x1F or pid == 0x21:
        value = float(a * 256 + b)
    elif pid == 0x42:
        value = (a * 256 + b) / 1000.0
    else:
        return None
    return pid, name, value, unit
