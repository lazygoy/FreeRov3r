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


def parse_elm_vin_response(response):
    """Extract a Mode 09 PID 02 VIN from ELM text, including ISO-TP frames."""
    chunks = {}
    unaddressed = []
    for raw_line in str(response).replace(">", "\n").replace("\r", "\n").splitlines():
        tokens = raw_line.strip().split()
        if not tokens or tokens[0].upper() in {"SEARCHING...", "NO", "DATA", "STOPPED", "OK"}:
            continue
        can_id = None
        if len(tokens[0]) in (3, 8):
            try:
                can_id = int(tokens[0], 16)
                tokens = tokens[1:]
            except ValueError:
                pass
        try:
            payload = bytes(int(token, 16) for token in tokens if len(token) == 2)
        except ValueError:
            continue
        if not payload:
            continue
        if can_id is None:
            unaddressed.extend(payload)
            continue
        frames = chunks.setdefault(can_id, [])
        frames.append(payload)

    candidates = [unaddressed]
    for frames in chunks.values():
        assembled = bytearray()
        expected = None
        for frame in frames:
            pci = frame[0] >> 4
            if pci == 0:
                length = frame[0] & 0x0F
                assembled.extend(frame[1:1 + length])
            elif pci == 1 and len(frame) >= 2:
                expected = ((frame[0] & 0x0F) << 8) | frame[1]
                assembled.extend(frame[2:])
            elif pci == 2:
                assembled.extend(frame[1:])
        if expected is not None:
            assembled = assembled[:expected]
        candidates.append(assembled)

    for data in candidates:
        raw = bytes(data)
        for marker in (b"\x49\x02",):
            start = raw.find(marker)
            if start < 0:
                continue
            offset = start + 2
            if len(raw) >= offset + 18 and raw[offset] in (1, 2, 3):
                offset += 1
            vin_bytes = raw[offset:offset + 17]
            try:
                vin = vin_bytes.decode("ascii").upper()
            except UnicodeDecodeError:
                continue
            from ..diagnostics.vin_decoder import validate_vin
            valid = validate_vin(vin)
            if valid:
                return valid
    return None


def query_vin(port, baudrate=38400, timeout=2.5):
    """Perform the read-only OBD-II Mode 09 PID 02 VIN request over ELM327."""
    connection = serial.Serial(
        str(port), int(baudrate), timeout=0.25, write_timeout=1
    )
    try:
        connection.reset_input_buffer()
        for command in ("ATZ", "ATE0", "ATL0", "ATS1", "ATH1", "ATSP0", "ATCAF1"):
            connection.write((command + "\\r").encode("ascii"))
            connection.flush()
            time.sleep(0.2 if command == "ATZ" else 0.08)
            connection.read_until(b">")
        connection.reset_input_buffer()
        connection.write(b"0902\\r")
        connection.flush()
        deadline = time.monotonic() + float(timeout)
        response = bytearray()
        while time.monotonic() < deadline:
            chunk = connection.read_until(b">")
            if chunk:
                response.extend(chunk)
                if b">" in chunk:
                    break
        vin = parse_elm_vin_response(response.decode("ascii", errors="replace"))
        if not vin:
            raise RuntimeError(
                "The adapter did not return a valid VIN. Check ignition state, "
                "OBD connection, protocol support, and adapter compatibility."
            )
        return vin
    finally:
        connection.close()
