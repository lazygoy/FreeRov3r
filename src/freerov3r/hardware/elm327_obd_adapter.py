"""Active, read-only SAE J1979 Mode 01 polling over ELM327 serial adapters.

This adapter issues standard OBD-II data requests only. It never sends clear-DTC,
coding, actuator, or other ECU write commands.
"""
import time
from collections import deque

import serial

from .base import CanAdapter
from ..models import CanFrame
from ..diagnostics.obd2 import PID_DEFINITIONS


DEFAULT_PIDS = tuple(PID_DEFINITIONS)


class Elm327ObdAdapter(CanAdapter):
    """Round-robin Mode 01 PID poller that exposes replies as normal CAN frames."""

    def __init__(self, port, baudrate=38400, pids=None, request_interval=0.20, timeout=0.35):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.pids = tuple(dict.fromkeys(int(pid) for pid in (DEFAULT_PIDS if pids is None else pids)))
        if not self.pids:
            raise ValueError("Select at least one OBD-II PID to poll.")
        invalid = [pid for pid in self.pids if pid not in PID_DEFINITIONS]
        if invalid:
            raise ValueError(f"Unsupported Mode 01 PID(s): {invalid}")
        self.request_interval = max(0.05, float(request_interval))
        self.timeout = max(0.1, float(timeout))
        self.connection = None
        self._queue = deque()
        self._next_pid = 0
        self._next_request = 0.0
        self.requests_sent = 0
        self.responses_received = 0
        self.no_data_responses = 0

    @property
    def description(self):
        return f"ELM327 OBD-II polling: {self.port} @ {self.baudrate}"

    def _command(self, command, wait_for_prompt=True):
        self.connection.write((command + "\r").encode("ascii"))
        self.connection.flush()
        response = self.connection.read_until(b">") if wait_for_prompt else b""
        return response.decode("ascii", errors="replace")

    def open(self):
        self.connection = serial.Serial(
            self.port, self.baudrate, timeout=self.timeout, write_timeout=1
        )
        try:
            self.connection.reset_input_buffer()
            identity = self._command("ATI").upper()
            if "ELM327" not in identity and "STN" not in identity:
                raise RuntimeError(
                    f"No ELM327/STN identity response on {self.port}: "
                    f"{identity.strip()[:100] or 'no response'}"
                )
            for command in ("ATE0", "ATL0", "ATS1", "ATH1", "ATSP0", "ATCAF1"):
                self._command(command)
            self.connection.reset_input_buffer()
            self._next_request = time.monotonic()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def _poll_one(self):
        pid = self.pids[self._next_pid]
        self._next_pid = (self._next_pid + 1) % len(self.pids)
        response = self._command(f"01{pid:02X}")
        self.requests_sent += 1
        now = time.time()
        for raw_line in response.replace(">", "\n").replace("\r", "\n").splitlines():
            line = raw_line.strip()
            if not line or line.upper() in {"SEARCHING...", "NO DATA", "STOPPED", "OK"}:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                can_id = int(parts[0], 16)
                payload_parts = parts[1:]
                if any(len(part) != 2 for part in payload_parts):
                    continue
                data = bytes(int(part, 16) for part in payload_parts)
            except ValueError:
                continue
            if not 0x7E8 <= can_id <= 0x7EF or len(data) < 4:
                continue
            if data[1] == 0x7F:
                self.no_data_responses += 1
                continue
            if data[1] != 0x41 or data[2] != pid:
                continue
            # ATCAF1 formats responses as [DLC, 41, PID, A, B...], which is
            # exactly the layout consumed by the shared Mode 01 decoder.
            self._queue.append(CanFrame(
                arbitration_id=can_id, data=data, channel=self.port, timestamp=now
            ))
            self.responses_received += 1

    def receive(self, timeout=0.2):
        if self.connection is None:
            raise RuntimeError("ELM327 OBD-II adapter is not open")
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() <= deadline:
            if self._queue:
                return self._queue.popleft()
            now = time.monotonic()
            if now >= self._next_request:
                self._poll_one()
                self._next_request = time.monotonic() + self.request_interval
                if self._queue:
                    return self._queue.popleft()
            else:
                time.sleep(min(0.01, max(0.0, self._next_request - now)))
        return None
