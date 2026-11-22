"""Synthetic OBD-II traffic for UI development; never represents real L319 data."""
import math
import time

from .base import CanAdapter
from ..models import CanFrame


# Generic SAE J1979 Mode 01 PIDs. These are demonstration values only.
PID_DEFINITIONS = {
    0x04: ("Calculated engine load", "%"),
    0x05: ("Engine coolant temperature", "°C"),
    0x0B: ("Intake manifold pressure", "kPa"),
    0x0C: ("Engine speed", "rpm"),
    0x0D: ("Vehicle speed", "km/h"),
    0x0F: ("Intake air temperature", "°C"),
    0x10: ("MAF air flow", "g/s"),
    0x11: ("Throttle position", "%"),
    0x2F: ("Fuel tank level", "%"),
    0x42: ("Control module voltage", "V"),
    0x46: ("Ambient air temperature", "°C"),
    0x5C: ("Engine oil temperature", "°C"),
}


def decode_mode01(frame: CanFrame):
    """Return (pid, name, value, unit) for a supported Mode 01 response."""
    data = frame.data
    if frame.is_extended_id or not 0x7E8 <= frame.arbitration_id <= 0x7EF:
        return None
    if len(data) < 4 or data[1] != 0x41:
        return None
    pid = data[2]
    if pid not in PID_DEFINITIONS:
        return None
    a, b = data[3], data[4] if len(data) > 4 else 0
    name, unit = PID_DEFINITIONS[pid]
    if pid == 0x04:
        value = a * 100.0 / 255.0
    elif pid == 0x05 or pid == 0x0F or pid == 0x46:
        value = a - 40.0
    elif pid == 0x0B:
        value = float(a)
    elif pid == 0x0C:
        value = (a * 256 + b) / 4.0
    elif pid == 0x0D:
        value = float(a)
    elif pid == 0x10:
        value = (a * 256 + b) / 100.0
    elif pid == 0x11:
        value = a * 100.0 / 255.0
    elif pid == 0x2F:
        value = a * 100.0 / 255.0
    elif pid == 0x42:
        value = (a * 256 + b) / 1000.0
    elif pid == 0x5C:
        value = a - 40.0
    else:
        return None
    return pid, name, value, unit


class SimulatedVehicleAdapter(CanAdapter):
    """Generates a changing stream of generic OBD-II responses."""

    def __init__(self, channel="L319-DEMO", update_interval=0.08):
        self.channel = channel
        self.update_interval = update_interval
        self._opened = False
        self._last_emit = 0.0
        self._index = 0
        self._started = 0.0
        self._pids = list(PID_DEFINITIONS)

    @property
    def description(self):
        return f"SIMULATOR:{self.channel} (synthetic data only)"

    def open(self):
        self._opened = True
        self._started = time.monotonic()
        self._last_emit = 0.0
        self._index = 0

    def close(self):
        self._opened = False

    def _values(self, elapsed):
        wave = math.sin(elapsed * 0.7)
        fast = math.sin(elapsed * 2.1)
        return {
            0x04: round(34 + 12 * wave),
            0x05: round(88 + 3 * math.sin(elapsed * 0.08) + 40),
            0x0B: round(42 + 8 * wave),
            0x0C: round(850 + 350 * abs(fast)),
            0x0D: round(32 + 18 * math.sin(elapsed * 0.22)),
            0x0F: round(24 + 2 * math.sin(elapsed * 0.1) + 40),
            0x10: round((8 + 5 * abs(fast)) * 100),
            0x11: round(18 + 9 * abs(fast)),
            0x2F: 173,  # about 68%
            0x42: 14000,  # 14.0 V
            0x46: 65,  # 25 °C
            0x5C: 130,  # 90 °C
        }

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("Simulator is not open")
        now = time.monotonic()
        due = self._last_emit + self.update_interval
        if now < due:
            time.sleep(min(timeout, due - now))
            now = time.monotonic()
            if now < due:
                return None
        elapsed = now - self._started
        pid = self._pids[self._index % len(self._pids)]
        self._index += 1
        self._last_emit = now
        raw = self._values(elapsed)[pid]
        if pid in (0x0C, 0x10, 0x42):
            a, b = (raw >> 8) & 0xFF, raw & 0xFF
        else:
            a, b = raw & 0xFF, 0
        # ISO-TP single-frame payload: length, positive response, PID, A, B, padding.
        data = bytes((4, 0x41, pid, a, b, 0, 0, 0))
        return CanFrame(0x7E8, data, channel=self.channel, timestamp=time.time())
