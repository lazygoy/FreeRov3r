"""Serial line adapter for the FreeRov3r ESP32 Classical-CAN firmware.

Current line format: S-or-E,arbitration_id_hex,DLC,HEXDATA
Examples: S,00000123,2,0102 and E,18DAF110,8,032201F190000000

The legacy three-field format remains accepted for older firmware. This
adapter only receives frames; it never sends serial commands or CAN traffic.
"""
import time

import serial

from .base import CanAdapter
from ..models import CanFrame


def parse_can_line(raw, channel=None):
    """Parse one firmware frame line; return None for status/noise/malformed input."""
    try:
        text = raw.decode("ascii", errors="strict") if isinstance(raw, bytes) else str(raw)
        text = text.strip()
        if not text or text.startswith("#"):
            return None

        parts = text.split(",")
        if len(parts) == 4 and parts[0].upper() in {"S", "E"}:
            is_extended = parts[0].upper() == "E"
            id_text, dlc_text, data_text = parts[1:]
        elif len(parts) == 3:
            # Backward compatibility with the original prototype protocol.
            id_text, dlc_text, data_text = parts
            is_extended = int(id_text, 16) > 0x7FF
        else:
            return None

        arbitration_id = int(id_text, 16)
        dlc = int(dlc_text, 10)
        data = bytes.fromhex(data_text)
        if not 0 <= arbitration_id <= 0x1FFFFFFF:
            return None
        if not is_extended and arbitration_id > 0x7FF:
            return None
        if not 0 <= dlc <= 8 or len(data) != dlc:
            return None

        return CanFrame(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=is_extended,
            channel=channel,
            timestamp=time.monotonic(),
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        return None


class Esp32SerialAdapter(CanAdapter):
    ACTIVE_FRAME_WINDOW_SECONDS = 2.5

    def __init__(self, port="COM3", baudrate=921600, timeout=0.2, channel_name=None):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.channel_name = channel_name or port
        self.connection = None
        self.frames_received = 0
        self.invalid_lines = 0
        self.last_error = None
        self.last_status = None
        self.status_lines = 0
        self.alert_count = 0
        self.firmware_error_count = 0
        self.last_frame_monotonic = None
        self.last_status_monotonic = None

    @property
    def description(self):
        return f"FreeRov3r ESP32 serial: {self.port} @ {self.baudrate} (listen-only)"

    @property
    def connected(self):
        return self.connection is not None and bool(getattr(self.connection, "is_open", True))

    @property
    def diagnostics(self):
        now = time.monotonic()
        frame_age = (
            max(0.0, now - self.last_frame_monotonic)
            if self.last_frame_monotonic is not None else None
        )
        status_age = (
            max(0.0, now - self.last_status_monotonic)
            if self.last_status_monotonic is not None else None
        )
        if not self.connected:
            receiver_state = "disconnected/error" if self.last_error else "disconnected"
        elif self.firmware_error_count or (
            self.last_error and not self.last_error.startswith("ALERT,")
        ):
            receiver_state = "connected/error"
        elif frame_age is None or frame_age > self.ACTIVE_FRAME_WINDOW_SECONDS:
            receiver_state = "connected/silent"
        else:
            receiver_state = "receiving"

        return {
            "connected": self.connected,
            "receiver_state": receiver_state,
            "port": self.port,
            "baudrate": self.baudrate,
            "frames_received": self.frames_received,
            "invalid_lines": self.invalid_lines,
            "status_lines": self.status_lines,
            "alert_count": self.alert_count,
            "firmware_error_count": self.firmware_error_count,
            "last_frame_age_seconds": frame_age,
            "last_status_age_seconds": status_age,
            "last_error": self.last_error,
            "last_status": self.last_status,
            "mode": "receive-only",
        }

    def open(self):
        self.last_error = None
        self.last_status = None
        self.status_lines = 0
        self.alert_count = 0
        self.firmware_error_count = 0
        self.last_frame_monotonic = None
        self.last_status_monotonic = None
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

        # Firmware metadata and alerts are diagnostic lines, not malformed frames.
        try:
            status = raw.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError:
            status = ""
        if status.startswith("#"):
            self.status_lines += 1
            self.last_status_monotonic = time.monotonic()
            self.last_status = status[1:][:120]
            if status.startswith("#ALERT,"):
                self.alert_count += 1
                self.last_error = status[1:][:120]
            elif status.startswith("#ERROR,"):
                self.firmware_error_count += 1
                self.last_error = status[1:][:120]
            return None

        frame = parse_can_line(raw, channel=self.channel_name)
        if frame is None:
            self.invalid_lines += 1
            self.last_error = status[:120] if status else "Unreadable serial input"
            return None
        self.frames_received += 1
        self.last_frame_monotonic = time.monotonic()
        self.last_error = None
        return frame
