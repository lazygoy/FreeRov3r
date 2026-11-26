"""Vehicle-independent SAE J1979 OBD-II Mode 01 PID definitions and decoding.

This module only decodes observed response frames. Active PID requests are a
separate transport capability and are not implied by having a PID definition.
"""
from ..models import CanFrame


PID_DEFINITIONS = {
    0x14: ("Narrowband oxygen sensor 1", "V / %"),
    0x15: ("Narrowband oxygen sensor 2", "V / %"),
    0x16: ("Narrowband oxygen sensor 3", "V / %"),
    0x17: ("Narrowband oxygen sensor 4", "V / %"),
    0x18: ("Narrowband oxygen sensor 5", "V / %"),
    0x19: ("Narrowband oxygen sensor 6", "V / %"),
    0x1A: ("Narrowband oxygen sensor 7", "V / %"),
    0x1B: ("Narrowband oxygen sensor 8", "V / %"),
    0x24: ("Wide-range oxygen sensor 1", "λ / V"),
    0x25: ("Wide-range oxygen sensor 2", "λ / V"),
    0x26: ("Wide-range oxygen sensor 3", "λ / V"),
    0x27: ("Wide-range oxygen sensor 4", "λ / V"),
    0x28: ("Wide-range oxygen sensor 5", "λ / V"),
    0x29: ("Wide-range oxygen sensor 6", "λ / V"),
    0x2A: ("Wide-range oxygen sensor 7", "λ / V"),
    0x2B: ("Wide-range oxygen sensor 8", "λ / V"),
    0x34: ("Wide-range oxygen sensor 1", "λ / mA"),
    0x35: ("Wide-range oxygen sensor 2", "λ / mA"),
    0x36: ("Wide-range oxygen sensor 3", "λ / mA"),
    0x37: ("Wide-range oxygen sensor 4", "λ / mA"),
    0x38: ("Wide-range oxygen sensor 5", "λ / mA"),
    0x39: ("Wide-range oxygen sensor 6", "λ / mA"),
    0x3A: ("Wide-range oxygen sensor 7", "λ / mA"),
    0x3B: ("Wide-range oxygen sensor 8", "λ / mA"),
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
    0x32: ("Evaporative system vapor pressure", "Pa"),
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
    0x14: "Emissions",
    0x15: "Emissions",
    0x16: "Emissions",
    0x17: "Emissions",
    0x18: "Emissions",
    0x19: "Emissions",
    0x1A: "Emissions",
    0x1B: "Emissions",
    0x24: "Emissions",
    0x25: "Emissions",
    0x26: "Emissions",
    0x27: "Emissions",
    0x28: "Emissions",
    0x29: "Emissions",
    0x2A: "Emissions",
    0x2B: "Emissions",
    0x34: "Emissions",
    0x35: "Emissions",
    0x36: "Emissions",
    0x37: "Emissions",
    0x38: "Emissions",
    0x39: "Emissions",
    0x3A: "Emissions",
    0x3B: "Emissions",
    0x04: "Engine", 0x05: "Temperatures",
    0x06: "Fuel", 0x07: "Fuel", 0x08: "Fuel", 0x09: "Fuel",
    0x0A: "Fuel", 0x0B: "Air & Intake", 0x0C: "Engine",
    0x0D: "Vehicle", 0x0E: "Engine", 0x0F: "Temperatures",
    0x10: "Air & Intake", 0x11: "Engine", 0x1F: "Engine",
    0x21: "Emissions", 0x22: "Fuel", 0x23: "Fuel",
    0x2C: "Air & Intake", 0x2D: "Air & Intake", 0x2E: "Emissions",
    0x2F: "Fuel", 0x30: "Emissions", 0x31: "Emissions", 0x32: "Emissions",
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
    0x14: "oxygen o2 narrowband sensor 1 voltage short term fuel trim stft",
    0x15: "oxygen o2 narrowband sensor 2 voltage short term fuel trim stft",
    0x16: "oxygen o2 narrowband sensor 3 voltage short term fuel trim stft",
    0x17: "oxygen o2 narrowband sensor 4 voltage short term fuel trim stft",
    0x18: "oxygen o2 narrowband sensor 5 voltage short term fuel trim stft",
    0x19: "oxygen o2 narrowband sensor 6 voltage short term fuel trim stft",
    0x1A: "oxygen o2 narrowband sensor 7 voltage short term fuel trim stft",
    0x1B: "oxygen o2 narrowband sensor 8 voltage short term fuel trim stft",
    0x24: "oxygen o2 wideband sensor 1 lambda equivalence ratio voltage",
    0x25: "oxygen o2 wideband sensor 2 lambda equivalence ratio voltage",
    0x26: "oxygen o2 wideband sensor 3 lambda equivalence ratio voltage",
    0x27: "oxygen o2 wideband sensor 4 lambda equivalence ratio voltage",
    0x28: "oxygen o2 wideband sensor 5 lambda equivalence ratio voltage",
    0x29: "oxygen o2 wideband sensor 6 lambda equivalence ratio voltage",
    0x2A: "oxygen o2 wideband sensor 7 lambda equivalence ratio voltage",
    0x2B: "oxygen o2 wideband sensor 8 lambda equivalence ratio voltage",
    0x34: "oxygen o2 wideband sensor 1 lambda equivalence ratio current milliamps",
    0x35: "oxygen o2 wideband sensor 2 lambda equivalence ratio current milliamps",
    0x36: "oxygen o2 wideband sensor 3 lambda equivalence ratio current milliamps",
    0x37: "oxygen o2 wideband sensor 4 lambda equivalence ratio current milliamps",
    0x38: "oxygen o2 wideband sensor 5 lambda equivalence ratio current milliamps",
    0x39: "oxygen o2 wideband sensor 6 lambda equivalence ratio current milliamps",
    0x3A: "oxygen o2 wideband sensor 7 lambda equivalence ratio current milliamps",
    0x3B: "oxygen o2 wideband sensor 8 lambda equivalence ratio current milliamps",
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
    0x32: "evap evaporative system vapor pressure signed pascals",
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

# Stable measurement keys used to expose each value carried by a multi-value PID.
PID_MULTI_VALUE_KEYS = {
    **{pid: ("voltage", "fuel_trim") for pid in range(0x14, 0x1C)},
    **{pid: ("lambda", "voltage") for pid in range(0x24, 0x2C)},
    **{pid: ("lambda", "current") for pid in range(0x34, 0x3C)},
    0x55: ("bank_1", "bank_3"),
    0x56: ("bank_1", "bank_3"),
    0x57: ("bank_2", "bank_4"),
    0x58: ("bank_2", "bank_4"),
}



def _is_mode01_response_id(arbitration_id, is_extended_id=False):
    """Recognize ISO 15765-4 physical OBD response IDs (11-bit and 29-bit)."""
    can_id = int(arbitration_id)
    if is_extended_id:
        return 0x18DAF100 <= can_id <= 0x18DAF1FF
    return 0x7E8 <= can_id <= 0x7EF


class Mode01ScalingContext:
    """Per-ECU dynamic scaling advertised by Mode 01 PID 4F."""

    def __init__(self):
        self._limits = {}

    def clear(self):
        """Discard learned limits when the active vehicle/session changes."""
        self._limits.clear()

    def observe(self, frame):
        data = frame.data
        if (not _is_mode01_response_id(frame.arbitration_id, frame.is_extended_id)
                or len(data) < 7 or data[1:3] != bytes((0x41, 0x4F))):
            return False
        self._limits[frame.arbitration_id] = {
            "lambda": float(data[3]),
            "voltage": float(data[4]),
            "current": float(data[5]),
        }
        return True

    def limits_for(self, ecu_id):
        return self._limits.get(int(ecu_id), {})

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


def decode_mode01_measurements(frame: CanFrame, scaling_context=None):
    """Return every decoded measurement as (pid, key, name, value, unit).

    A single Mode 01 PID can carry more than one independent measurement.
    Measurement keys are stable sensor identifiers, not display labels.
    Unsupported frames, malformed payloads and unavailable values return [].
    """
    data = frame.data
    if not _is_mode01_response_id(frame.arbitration_id, frame.is_extended_id):
        return []
    if len(data) < 4 or data[1] != 0x41:
        return []
    pid = data[2]
    if pid == 0x4F:
        if scaling_context is not None:
            scaling_context.observe(frame)
        return []
    if pid not in PID_DEFINITIONS:
        return []

    multi_two_byte_pids = {0x55, 0x56, 0x57, 0x58}
    two_byte_pids = {
        0x1F, 0x21, 0x22, 0x23, 0x31, 0x32, 0x3C, 0x3D, 0x3E, 0x3F,
        0x42, 0x4D, 0x4E, 0x53, 0x54, 0x59, 0x5D, 0x5E,
        *multi_two_byte_pids,
    }
    four_byte_pids = set(range(0x24, 0x2C)) | set(range(0x34, 0x3C))
    if pid in four_byte_pids and len(data) < 7:
        return []
    if pid in range(0x14, 0x1C) and len(data) < 5:
        return []
    if pid in two_byte_pids and len(data) < 5:
        return []

    a, b = data[3], data[4] if len(data) > 4 else 0
    ab = a * 256 + b
    name, unit = PID_DEFINITIONS[pid]
    limits = scaling_context.limits_for(frame.arbitration_id) if scaling_context is not None else {}
    lambda_max = limits.get("lambda") or 2.0
    voltage_max = limits.get("voltage") or 8.0
    current_max = limits.get("current") or 128.0

    def single(value):
        return [(pid, "value", name, value, unit)]

    if pid in range(0x14, 0x1C):
        sensor_number = pid - 0x13
        measurements = [
            (pid, "voltage", f"Narrowband oxygen sensor {sensor_number} voltage", a / 200.0, "V"),
        ]
        if b != 0xFF:
            measurements.append((
                pid, "fuel_trim",
                f"Narrowband oxygen sensor {sensor_number} short-term fuel trim",
                (b - 128.0) * 100.0 / 128.0, "%",
            ))
        return measurements
    if pid in range(0x24, 0x2C):
        sensor_number = pid - 0x23
        cd = data[5] * 256 + data[6]
        return [
            (pid, "lambda", f"Wide-range oxygen sensor {sensor_number} lambda", ab * lambda_max / 65535.0, "λ"),
            (pid, "voltage", f"Wide-range oxygen sensor {sensor_number} voltage", cd * voltage_max / 65535.0, "V"),
        ]
    if pid in range(0x34, 0x3C):
        sensor_number = pid - 0x33
        cd = data[5] * 256 + data[6]
        return [
            (pid, "lambda", f"Wide-range oxygen sensor {sensor_number} lambda", ab * lambda_max / 65535.0, "λ"),
            (pid, "current", f"Wide-range oxygen sensor {sensor_number} current", (cd - 0x8000) * current_max / 32768.0, "mA"),
        ]
    if pid in multi_two_byte_pids:
        bank_a, bank_b = {
            0x55: (1, 3), 0x56: (1, 3),
            0x57: (2, 4), 0x58: (2, 4),
        }[pid]
        return [
            (pid, f"bank_{bank_a}", f"Secondary oxygen sensor trim bank {bank_a}", (a - 128.0) * 100.0 / 128.0, "%"),
            (pid, f"bank_{bank_b}", f"Secondary oxygen sensor trim bank {bank_b}", (b - 128.0) * 100.0 / 128.0, "%"),
        ]

    if pid in (0x04, 0x11, 0x2C, 0x2E, 0x2F, 0x4C, 0x52, 0x5A, 0x5B):
        value = a * 100.0 / 255.0
    elif pid in (0x05, 0x0F, 0x46, 0x5C):
        value = a - 40.0
    elif pid in (0x06, 0x07, 0x08, 0x09, 0x2D):
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
    elif pid == 0x32:
        signed_ab = ab if ab < 0x8000 else ab - 0x10000
        value = signed_ab / 4.0
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
        value = float(ab if ab < 0x8000 else ab - 0x10000)
    elif pid == 0x5D:
        value = ab / 128.0 - 210.0
    elif pid == 0x5E:
        value = ab / 20.0
    else:
        return []
    return single(value)


def decode_mode01(frame: CanFrame):
    """Backward-compatible scalar view of a Mode 01 response.

    For a multi-value PID this returns its first measurement. New code that
    needs all fields must use decode_mode01_measurements().
    """
    measurements = decode_mode01_measurements(frame)
    if not measurements:
        return None
    pid, _key, name, value, unit = measurements[0]
    return pid, name, value, unit
