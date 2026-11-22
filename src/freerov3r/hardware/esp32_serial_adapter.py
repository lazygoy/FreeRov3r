"""Serial line adapter for the FreeRov3r ESP32 Classical-CAN firmware.

Expected line format: arbitration_id_hex,DLC,HEXDATA
Example: 00000123,2,0102
Only Classical CAN frames (0..8 data bytes) are accepted. This adapter is
receive-only; it does not send frames or configure ECU services.
"""
import serial

from .base import CanAdapter
from ..models import CanFrame


def parse_can_line(raw, channel=None):
    """Parse one firmware line. Return None for boot text or malformed input."""
    try:
        text = raw.decode("ascii", errors="strict") if isinstance(raw, bytes) else str(raw)
        parts = text.strip().split(",")
        if len(parts) != 3:
            return None
        arbitration_id = int(parts[0], 16)
        dlc = int(parts[1], 10)
        data = bytes.fromhex(parts[2])
        if not 0 <= arbitration_id <= 0x1FFFFFFF:
            return None
        if not 0 <= dlc <= 8 or len(data) != dlc:
            return None
        return CanFrame(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=arbitration_id > 0x7FF,
            channel=channel,
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        return None


class Esp32SerialAdapter(CanAdapter):
    def __init__(self, port="COM3", baudrate=115200, timeout=0.2):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.connection = None
        self.frames_received = 0
        self.invalid_lines = 0
        self.last_error = None

    @property
    def description(self):
        return f"FreeRov3r ESP32 serial: {self.port} @ {self.baudrate}"

    @property
    def connected(self):
        return self.connection is not None and bool(getattr(self.connection, "is_open", True))

    @property
    def diagnostics(self):
        return {
            "connected": self.connected,
            "port": self.port,
            "baudrate": self.baudrate,
            "frames_received": self.frames_received,
            "invalid_lines": self.invalid_lines,
            "last_error": self.last_error,
        }

    def open(self):
        self.last_error = None
        self.connection = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def receive(self, timeout=0.2):
        if self.connection is None:
            raise RuntimeError("ESP32 serial adapter is not open")
        self.connection.timeout = timeout
        raw = self.connection.readline()
        if not raw:
            return None
        frame = parse_can_line(raw, channel=self.port)
        if frame is None:
            self.invalid_lines += 1
            try:
                self.last_error = raw.decode("ascii", errors="replace").strip()[:120]
            except Exception:
                self.last_error = "Unreadable serial input"
            return None
        self.frames_received += 1
        self.last_error = None
        return frame
