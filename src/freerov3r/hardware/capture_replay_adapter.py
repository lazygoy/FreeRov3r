"""Timed, receive-only replay of FreeRov3r JSONL capture archives."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from .base import CanAdapter
from ..models import CanFrame


class CaptureReplayError(ValueError):
    """Raised when a capture cannot be replayed safely."""


class CaptureReplayAdapter(CanAdapter):
    """Incrementally replay JSONL frames; never transmits CAN traffic."""

    def __init__(self, path: str | Path, *, speed: float = 1.0, loop: bool = False):
        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            raise ValueError("Replay speed must be a positive number.")
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Replay speed must be finite and greater than zero.")
        self.path = Path(path)
        self.speed = float(speed)
        self.loop = bool(loop)
        self._handle = None
        self._opened = False
        self._pending = None
        self._previous_source_time = None
        self._next_source_time = None
        self._due_monotonic = None
        self._first_frame = True
        self._frames_this_pass = 0
        self.frames_replayed = 0
        self.malformed_records = 0

    @property
    def description(self):
        return f"CAPTURE REPLAY: {self.path.name} @ {self.speed:g}x (receive-only)"

    @property
    def diagnostics(self):
        return {"mode": "offline receive-only replay", "opened": self._opened,
                "frames_replayed": self.frames_replayed,
                "malformed_records": self.malformed_records, "loop": self.loop,
                "speed": self.speed, "path": str(self.path)}

    def open(self):
        if self._opened:
            return
        if not self.path.is_file():
            raise CaptureReplayError(f"Capture file does not exist: {self.path}")
        self._handle = self.path.open("r", encoding="utf-8-sig")
        self._opened = True
        self._pending = None
        self._previous_source_time = self._next_source_time = self._due_monotonic = None
        self._first_frame = True
        self._frames_this_pass = self.frames_replayed = self.malformed_records = 0

    def close(self):
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._opened = False
        self._pending = None
        self._due_monotonic = None

    def _restart(self):
        if not self.loop or self._handle is None or self._frames_this_pass == 0:
            return False
        self._handle.seek(0)
        self._previous_source_time = self._next_source_time = self._due_monotonic = None
        self._first_frame = True
        self._frames_this_pass = 0
        self._pending = None
        return True

    @staticmethod
    def _decode_frame(item):
        try:
            ident = item.get("arbitration_id", item.get("id"))
            ident = int(ident, 16) if isinstance(ident, str) else int(ident)
            extended = bool(item.get("is_extended_id", item.get("extended", False)))
            if not 0 <= ident <= (0x1FFFFFFF if extended else 0x7FF):
                raise ValueError("CAN identifier is out of range")
            raw = item.get("data", "")
            data = bytes(raw) if isinstance(raw, list) else bytes.fromhex(
                str(raw).replace(" ", "").replace(":", ""))
            if len(data) > 64:
                raise ValueError("CAN payload exceeds 64 bytes")
            source_time = item.get("timestamp", item.get("elapsed_seconds"))
            if source_time is not None:
                source_time = float(source_time)
                if not math.isfinite(source_time):
                    source_time = None
            frame = CanFrame(
                arbitration_id=ident, data=data, is_extended_id=extended,
                is_remote_frame=bool(item.get("is_remote_frame", False)),
                is_error_frame=bool(item.get("is_error_frame", False)),
                channel=str(item.get("channel") or "REPLAY"),
                timestamp=None, timestamp_clock_domain="host_monotonic",
                timestamp_source="capture_replay", source_timestamp=source_time,
                source_timestamp_clock_domain=str(item.get("timestamp_clock_domain", "capture")))
            return frame, source_time
        except (TypeError, ValueError, OverflowError) as exc:
            raise CaptureReplayError(f"Invalid captured CAN frame: {exc}") from exc

    def _read_next(self):
        for line in self._handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                self.malformed_records += 1
                continue
            if not isinstance(item, dict):
                self.malformed_records += 1
                continue
            if item.get("record_type") != "frame":
                continue
            try:
                return self._decode_frame(item)
            except CaptureReplayError:
                self.malformed_records += 1
        return None

    def receive(self, timeout=0.2):
        if not self._opened or self._handle is None:
            raise RuntimeError("Capture replay adapter is not open")
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if self._pending is None:
                result = self._read_next()
                if result is None:
                    if not self._restart():
                        return None
                    continue
                frame, source_time = result
                delay = 0.0
                if not self._first_frame and source_time is not None and self._previous_source_time is not None:
                    delay = max(0.0, source_time - self._previous_source_time) / self.speed
                self._due_monotonic = time.monotonic() + delay
                self._pending = frame
                self._next_source_time = source_time

            now = time.monotonic()
            remaining = (self._due_monotonic or now) - now
            if remaining > 0:
                wait = min(remaining, deadline - now)
                if wait <= 0:
                    return None
                time.sleep(wait)
                continue

            src = self._pending
            frame = CanFrame(
                arbitration_id=src.arbitration_id, data=src.data,
                is_extended_id=src.is_extended_id, is_remote_frame=src.is_remote_frame,
                is_error_frame=src.is_error_frame, channel=src.channel,
                timestamp=time.monotonic(), timestamp_clock_domain="host_monotonic",
                timestamp_source="capture_replay", source_timestamp=src.source_timestamp,
                source_timestamp_clock_domain=src.source_timestamp_clock_domain)
            self._previous_source_time = self._next_source_time
            self._pending = self._due_monotonic = None
            self._first_frame = False
            self._frames_this_pass += 1
            self.frames_replayed += 1
            return frame
