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
