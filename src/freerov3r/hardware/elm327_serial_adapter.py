"""Receive-only ELM327 serial monitor adapter.

The adapter is configured with ELM control commands, then uses ATMA to
monitor CAN traffic. No OBD requests or ECU control commands are sent.
"""
import time
import serial
from .base import CanAdapter
from ..models import CanFrame


def parse_elm_line(raw, channel=None):
    """Parse an ELM327 ATH1/ATS1 monitor line into a classical CAN frame."""
    try:
        line = raw.decode("ascii", errors="ignore") if isinstance(raw, bytes) else str(raw)
        line = line.strip().replace("\r", "").replace("\n", "")
        if not line or line in {">", "STOPPED", "SEARCHING..."}:
            return None
        parts = line.split()
        if len(parts) < 2:
            return None
        header = parts[0]
        if len(header) not in (3, 8):
            return None
        arbitration_id = int(header, 16)
        data_parts = parts[1:]
        if any(len(part) != 2 for part in data_parts):
            return None
        data = bytes(int(part, 16) for part in data_parts)
        if not 0 <= arbitration_id <= 0x1FFFFFFF or len(data) > 8:
            return None
        return CanFrame(arbitration_id=arbitration_id, data=data,
                        is_extended_id=(len(header) == 8), channel=channel,
                        timestamp=time.time())
    except (ValueError, TypeError):
        return None


class Elm327SerialAdapter(CanAdapter):
    """ELM327 over a serial COM port, including Windows Bluetooth COM ports."""
    def __init__(self, port, baudrate=38400, timeout=0.2):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.connection = None
        self.frames_received = 0
        self.invalid_lines = 0

    @property
    def description(self):
        return f"ELM327 serial: {self.port} @ {self.baudrate}"

    def _command(self, command, wait=0.15):
        self.connection.write((command + "\r").encode("ascii"))
        self.connection.flush()
        time.sleep(wait)
        return self.connection.read_all().decode("ascii", errors="replace")

    def open(self):
        self.connection = serial.Serial(self.port, self.baudrate, timeout=self.timeout, write_timeout=1)
        try:
            self.connection.reset_input_buffer()
            identity = self._command("ATI", wait=0.35).upper()
            if "ELM327" not in identity and "STN" not in identity:
                detail = identity.strip()[:100] or "no response"
                raise RuntimeError(f"No ELM327/STN identity response on {self.port}: {detail}")
            for command in ("ATE0", "ATL0", "ATS1", "ATH1", "ATSP0"):
                self._command(command)
            self.connection.reset_input_buffer()
            self.connection.write(b"ATMA\r")
            self.connection.flush()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            try:
                self.connection.write(b"\r")
                self.connection.flush()
            except Exception:
                pass
            self.connection.close()
            self.connection = None

    def receive(self, timeout=0.2):
        if self.connection is None:
            raise RuntimeError("ELM327 adapter is not open")
        self.connection.timeout = timeout
        raw = self.connection.read_until(b"\r")
        if not raw:
            return None
        frame = parse_elm_line(raw, channel=self.port)
        if frame is None:
            self.invalid_lines += 1
            return None
        self.frames_received += 1
        return frame
