"""Timed, receive-only replay of FreeRov3r JSONL capture archives."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Iterator

from .base import CanAdapter
from ..models import CanFrame


class CaptureReplayError(ValueError):
    """Raised when a capture cannot be replayed safely."""


class CaptureReplayAdapter(CanAdapter):
    """Replay JSONL capture frames through the standard CAN receive interface.

    The file is read incrementally. Recorded timestamps determine inter-frame
    delays; emitted timestamps use the current host monotonic clock, while the
    original timestamp is retained as source_timestamp. Replay never transmits.
    """

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
        self._pending: CanFrame | None = None
        self._previous_source_time: float | None = None
        self._due_monotonic: float | None = None
        self._first_frame = True
        self.frames_replayed = 0
        self.malformed_records = 0
        self._source_clock_domain = "capture"

    @property
    def description(self) -> str:
        return f"CAPTURE REPLAY: {self.path.name} @ {self.speed:g}x (receive-only)"

    @property
    def diagnostics(self) -> dict:
        return {
            "mode": "offline receive-only replay",
            "opened": self._opened,
            "frames_replayed": self.frames_replayed,
            "malformed_records": self.malformed_records,
            "loop": self.loop,
            "speed": self.speed,
            "path": str(self.path),
        }

    def open(self) -> None:
        if self._opened:
            return
        if not self.path.is_file():
            raise CaptureReplayError(f"Capture file does not exist: {self.path}")
        self._handle = self.path.open("r", encoding="utf-8-sig")
        self._opened = True
        self._pending = None
        self._previous_source_time = None
        self._due_monotonic = None
        self._first_frame = True
        self.frames_replayed = 0
        self.malformed_records = 0
        self._source_clock_domain = "capture"

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._opened = False
        self._pending = None
        self._due_monotonic = None

    def _restart(self) -> bool:
        if not self.loop or self._handle is None:
            return False
        self._handle.seek(0)
        self._previous_source_time = None
        self._due_monotonic = None
        self._first_frame = True
        self._pending = None
        return True

    @staticmethod
    def _decode_frame(item: dict) -> tuple[CanFrame, float | None]:
        try:
            arbitration_id = item.get("arbitration_id", item.get("id"))
            if isinstance(arbitration_id, str):
                arbitration_id = int(arbitration_id, 16)
            arbitration_id = int(arbitration_id)
            extended = bool(item.get("is_extended_id", item.get("extended", False)))
            maximum_id = 0x1FFFFFFF if extended else 0x7FF
            if not 0 <= arbitration_id <= maximum_id:
                raise ValueError("CAN identifier is out of range")

            raw_data = item.get("data", "")
            if isinstance(raw_data, list):
                data = bytes(raw_data)
            elif isinstance(raw_data, bytes):
                data = raw_data
            else:
                data = bytes.fromhex(str(raw_data).replace(" ", "").replace(":", ""))
            if len(data) > 64:
                raise ValueError("CAN payload exceeds 64 bytes")

            source_time = item.get("timestamp")
            if source_time is None:
                source_time = item.get("elapsed_seconds")
            if source_time is not None:
                source_time = float(source_time)
                if not math.isfinite(source_time):
                    source_time = None

            channel = item.get("channel")
            frame = CanFrame(
                arbitration_id=arbitration_id,
                data=data,
                is_extended_id=extended,
                is_remote_frame=bool(item.get("is_remote_frame", False)),
                is_error_frame=bool(item.get("is_error_frame", False)),
                channel=str(channel) if channel is not None else "REPLAY",
                timestamp=None,
                timestamp_clock_domain="host_monotonic",
                timestamp_source="capture_replay",
                source_timestamp=source_time,
                source_timestamp_clock_domain=str(
                    item.get("timestamp_clock_domain", "capture")
                ),
            )
            return frame, source_time
        except (TypeError, ValueError, OverflowError) as exc:
            raise CaptureReplayError(f"Invalid captured CAN frame: {exc}") from exc

    def _read_next(self) -> tuple[CanFrame, float | None] | None:
        if self._handle is None:
            return None
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

    def receive(self, timeout: float = 0.2) -> CanFrame | None:
        if not self._opened or self._handle is None:
            raise RuntimeError("Capture replay adapter is not open")
        timeout = max(0.0, float(timeout))
        deadline = time.monotonic() + timeout

        while True:
            if self._pending is None:
                next_frame = self._read_next()
                if next_frame is None:
                    if not self._restart():
                        return None
                    continue
                frame, source_time = next_frame
                now = time.monotonic()
                if self._first_frame or source_time is None or self._previous_source_time is None:
                    delay = 0.0
                else:
                    delay = max(0.0, source_time - self._previous_source_time) / self.speed
                self._due_monotonic = now + delay
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

            frame = self._pending
            emitted_at = time.monotonic()
            frame = CanFrame(
                arbitration_id=frame.arbitration_id,
                data=frame.data,
                is_extended_id=frame.is_extended_id,
                is_remote_frame=frame.is_remote_frame,
                is_error_frame=frame.is_error_frame,
                channel=frame.channel,
                timestamp=emitted_at,
                timestamp_clock_domain="host_monotonic",
                timestamp_source="capture_replay",
                source_timestamp=frame.source_timestamp,
                source_timestamp_clock_domain=frame.source_timestamp_clock_domain,
            )
            self._previous_source_time = self._next_source_time
            self._pending = None
            self._due_monotonic = None
            self._first_frame = False
            self.frames_replayed += 1
            return frame
