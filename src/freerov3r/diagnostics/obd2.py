"""Vehicle-independent SAE J1979 OBD-II Mode 01 PID definitions and decoding.

This module only decodes observed response frames. Active PID requests are a
separate transport capability and are not implied by having a PID definition.
"""
from ..models import CanFrame


PID_DEFINITIONS = {
    0x04: ("Calculated engine load", "%"),
    0x05: ("Engine coolant temperature", "°C"),
    0x06: ("Short-term fuel trim bank 1", "%"),
    0x07: ("Long-term fuel trim bank 1", "%"),
    0x08: ("Short-term fuel trim bank 2", "%"),
    0x09: ("Long-term fuel trim bank 2", "%"),
    0x0A: ("Fuel pressure", "kPa"),
    0x0B: ("Intake manifold pressure", "kPa"),
    0x0C: ("Engine speed", "rpm"),
    0x0D: ("Vehicle speed", "km/h"),
    0x0E: ("Ignition timing advance", "°"),
    0x0F: ("Intake air temperature", "°C"),
    0x10: ("MAF air flow", "g/s"),
    0x11: ("Throttle position", "%"),
    0x1F: ("Run time since engine start", "s"),
    0x21: ("Distance traveled with MIL on", "km"),
    0x22: ("Fuel rail pressure relative to manifold vacuum", "kPa"),
    0x23: ("Fuel rail pressure", "kPa"),
    0x2C: ("Commanded EGR", "%"),
    0x2D: ("EGR error", "%"),
    0x2E: ("Commanded evaporative purge", "%"),
    0x2F: ("Fuel tank level", "%"),
    0x30: ("Warm-ups since codes cleared", "count"),
    0x31: ("Distance since codes cleared", "km"),
    0x33: ("Barometric pressure", "kPa"),
    0x3C: ("Catalyst temperature bank 1 sensor 1", "°C"),
    0x3D: ("Catalyst temperature bank 2 sensor 1", "°C"),
    0x3E: ("Catalyst temperature bank 1 sensor 2", "°C"),
    0x3F: ("Catalyst temperature bank 2 sensor 2", "°C"),
    0x42: ("Control module voltage", "V"),
    0x46: ("Ambient air temperature", "°C"),
    0x4C: ("Commanded throttle actuator", "%"),
    0x4D: ("Time run with MIL on", "min"),
    0x4E: ("Time since codes cleared", "min"),
    0x52: ("Ethanol fuel percentage", "%"),
    0x53: ("Absolute evaporative system vapor pressure", "kPa"),
    0x54: ("Evaporative system vapor pressure", "Pa"),
    0x55: ("Short-term secondary oxygen sensor trim bank 1 and 3", "%"),
    0x56: ("Long-term secondary oxygen sensor trim bank 1 and 3", "%"),
    0x57: ("Short-term secondary oxygen sensor trim bank 2 and 4", "%"),
    0x58: ("Long-term secondary oxygen sensor trim bank 2 and 4", "%"),
    0x59: ("Fuel rail absolute pressure", "kPa"),
    0x5A: ("Relative accelerator pedal position", "%"),
    0x5B: ("Hybrid battery pack remaining life", "%"),
    0x5C: ("Engine oil temperature", "°C"),
    0x5D: ("Fuel injection timing", "°"),
    0x5E: ("Engine fuel rate", "L/h"),
}

# Categories are navigation aids, not claims that a particular vehicle supports
# the PID. Support must be discovered from the responding ECU.
PID_CATEGORIES = {
    0x04: "Engine", 0x05: "Temperatures",
    0x06: "Fuel", 0x07: "Fuel", 0x08: "Fuel", 0x09: "Fuel",
    0x0A: "Fuel", 0x0B: "Air & Intake", 0x0C: "Engine",
    0x0D: "Vehicle", 0x0E: "Engine", 0x0F: "Temperatures",
    0x10: "Air & Intake", 0x11: "Engine", 0x1F: "Engine",
    0x21: "Emissions", 0x22: "Fuel", 0x23: "Fuel",
    0x2C: "Air & Intake", 0x2D: "Air & Intake", 0x2E: "Emissions",
    0x2F: "Fuel", 0x30: "Emissions", 0x31: "Emissions",
    0x33: "Air & Intake", 0x3C: "Temperatures", 0x3D: "Temperatures",
    0x3E: "Temperatures", 0x3F: "Temperatures", 0x42: "Electrical",
    0x46: "Temperatures", 0x4C: "Engine", 0x4D: "Emissions",
    0x4E: "Emissions", 0x52: "Fuel", 0x53: "Emissions",
    0x54: "Emissions", 0x55: "Fuel", 0x56: "Fuel",
    0x57: "Fuel", 0x58: "Fuel", 0x59: "Fuel",
    0x5A: "Engine", 0x5B: "Electrical", 0x5C: "Temperatures",
    0x5D: "Engine", 0x5E: "Fuel",
}

PID_SEARCH_TERMS = {
    0x04: "load engine load calculated torque",
    0x05: "coolant water temperature engine ect",
    0x06: "short term fuel trim stft bank one b1",
    0x07: "long term fuel trim ltft bank one b1",
    0x08: "short term fuel trim stft bank two b2",
    0x09: "long term fuel trim ltft bank two b2",
    0x0A: "fuel pressure rail gauge low pressure",
    0x0B: "map manifold absolute pressure boost intake",
    0x0C: "rpm revs revolutions engine speed",
    0x0D: "speed road vehicle speed",
    0x0E: "spark ignition timing advance degrees before top dead center",
    0x0F: "iat intake air temperature",
    0x10: "maf mass air flow airflow",
    0x11: "throttle tps accelerator position",
    0x1F: "runtime run time engine start",
    0x21: "mil emissions distance check engine light",
    0x22: "fuel rail pressure manifold vacuum relative",
    0x23: "fuel rail pressure direct injection high pressure",
    0x2C: "egr exhaust gas recirculation commanded",
    0x2D: "egr exhaust gas recirculation error",
    0x2E: "evap evaporative purge command",
    0x2F: "fuel tank level fuel",
    0x30: "warmups warm up cycles since clear reset",
    0x31: "distance since codes cleared reset",
    0x33: "barometric baro atmospheric pressure",
    0x3C: "catalyst catalytic converter temperature bank 1 sensor 1",
    0x3D: "catalyst catalytic converter temperature bank 2 sensor 1",
    0x3E: "catalyst catalytic converter temperature bank 1 sensor 2",
    0x3F: "catalyst catalytic converter temperature bank 2 sensor 2",
    0x42: "voltage battery charging electrical module",
    0x46: "ambient outside air temperature",
    0x4C: "throttle actuator commanded",
    0x4D: "time mil malfunction indicator lamp",
    0x4E: "time since codes cleared reset",
    0x52: "ethanol alcohol fuel content percentage",
    0x53: "evap evaporative vapor pressure absolute",
    0x54: "evap evaporative vapor pressure",
    0x55: "secondary oxygen sensor short term fuel trim bank 1 bank 3",
    0x56: "secondary oxygen sensor long term fuel trim bank 1 bank 3",
    0x57: "secondary oxygen sensor short term fuel trim bank 2 bank 4",
    0x58: "secondary oxygen sensor long term fuel trim bank 2 bank 4",
    0x59: "fuel rail absolute pressure absolute high pressure",
    0x5A: "accelerator pedal position relative app",
    0x5B: "hybrid battery remaining life charge",
    0x5C: "oil temperature engine lubricant",
    0x5D: "fuel injection timing start of injection",
    0x5E: "fuel rate consumption engine liters per hour",
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
        if needle and not all(term in haystack for term in needle.split()):
            continue
        rows.append((f"{pid:02X}", name, unit, group))
    return rows



def parse_mode01_supported_pids(response, base_pid):
    """Decode a Mode 01 PID-support bitmap into the supported PID numbers.

    ELM327 text responses commonly look like: 7E8 06 41 00 BE 3E B8 13.
    The four bitmap bytes describe the next 32 PIDs after base_pid.
    Returns an empty set when the response contains no valid bitmap.
    """
    base_pid = int(base_pid)
    if base_pid < 0 or base_pid > 0xE0 or base_pid % 0x20:
        raise ValueError("base_pid must be a Mode 01 bitmap base (00, 20, ... E0)")

    supported = set()
    for raw_line in str(response or "").replace(">", "\n").replace("\r", "\n").splitlines():
        tokens = [token.strip().upper().strip(",") for token in raw_line.split()]
        for index in range(len(tokens) - 5):
            if tokens[index] != "41" or tokens[index + 1] != f"{base_pid:02X}":
                continue
            try:
                bitmap_bytes = [int(token, 16) for token in tokens[index + 2:index + 6]]
            except ValueError:
                continue
            if len(bitmap_bytes) != 4:
                continue
            bitmap = int.from_bytes(bytes(bitmap_bytes), "big")
            for bit in range(32):
                if bitmap & (1 << (31 - bit)):
                    supported.add(base_pid + bit + 1)
    return supported


OBD_PIDS = [
    (f"{pid:02X}", name, unit)
    for pid, (name, unit) in PID_DEFINITIONS.items()
]


def decode_mode01(frame: CanFrame):
    """Return (pid, name, value, unit) for a supported 11-bit CAN response.

    Values follow the SAE J1979 Mode 01 scaling. This numeric decoder
    intentionally leaves bitfields and enumerated status PIDs out of scope.
    """
    data = frame.data
    if frame.is_extended_id or not 0x7E8 <= frame.arbitration_id <= 0x7EF:
        return None
    if len(data) < 4 or data[1] != 0x41:
        return None
    pid = data[2]
    if pid not in PID_DEFINITIONS:
        return None

    two_byte_pids = {
        0x1F, 0x21, 0x22, 0x23, 0x31, 0x3C, 0x3D, 0x3E, 0x3F,
        0x42, 0x4D, 0x4E, 0x53, 0x54, 0x59, 0x5D, 0x5E,
    }
    if pid in two_byte_pids and len(data) < 5:
        return None

    a, b = data[3], data[4] if len(data) > 4 else 0
    ab = a * 256 + b
    name, unit = PID_DEFINITIONS[pid]

    if pid in (0x04, 0x11, 0x2C, 0x2E, 0x2F, 0x4C, 0x52, 0x5A, 0x5B):
        value = a * 100.0 / 255.0
    elif pid in (0x05, 0x0F, 0x46, 0x5C):
        value = a - 40.0
    elif pid in (0x06, 0x07, 0x08, 0x09, 0x2D, 0x55, 0x56, 0x57, 0x58):
        value = (a - 128.0) * 100.0 / 128.0
    elif pid == 0x0A:
        value = a * 3.0
    elif pid in (0x0B, 0x0D, 0x33):
        value = float(a)
    elif pid == 0x0C:
        value = ab / 4.0
    elif pid == 0x0E:
        value = a / 2.0 - 64.0
    elif pid == 0x10:
        value = ab / 100.0
    elif pid in (0x1F, 0x21, 0x30, 0x31, 0x4D, 0x4E):
        value = float(ab if pid not in (0x30,) else a)
    elif pid == 0x22:
        value = ab * 0.079
    elif pid in (0x23, 0x59):
        value = ab * 10.0
    elif pid in (0x3C, 0x3D, 0x3E, 0x3F):
        value = ab / 10.0 - 40.0
    elif pid == 0x42:
        value = ab / 1000.0
    elif pid == 0x53:
        value = ab / 200.0
    elif pid == 0x54:
        # PID 54 is a signed 16-bit two's-complement pressure value.
        value = float(ab if ab < 0x8000 else ab - 0x10000)
    elif pid == 0x5D:
        value = ab / 128.0 - 210.0
    elif pid == 0x5E:
        value = ab / 20.0
    else:
        return None
    return pid, name, value, unit
