"""Deterministic, receive-only dual-channel CAN traffic simulator."""
from __future__ import annotations

import math
import time

from .base import CanAdapter
from ..models import CanFrame


class DualChannelSimulator(CanAdapter):
    """Generate repeatable HS-CAN/MS-CAN traffic without hardware."""

    CHANNELS = (
        {"name": "HS-CAN", "bitrate": 500_000, "period": 0.010,
         "frames": ((0x100, 8), (0x101, 8), (0x120, 4), (0x1A0, 8))},
        {"name": "MS-CAN", "bitrate": 125_000, "period": 0.040,
         "frames": ((0x300, 8), (0x301, 4), (0x320, 8))},
    )

    def __init__(self, *, speed: float = 1.0, channels: tuple[str, ...] | None = None):
        if (isinstance(speed, bool) or not isinstance(speed, (int, float))
                or not math.isfinite(speed) or speed <= 0):
            raise ValueError("Simulation speed must be finite and greater than zero.")
        self.speed = float(speed)
        available = {item["name"] for item in self.CHANNELS}
        selected = tuple(channels) if channels is not None else ("HS-CAN", "MS-CAN")
        if not selected or any(name not in available for name in selected):
            raise ValueError("Select HS-CAN, MS-CAN, or both.")
        self.channels = tuple(item for item in self.CHANNELS if item["name"] in selected)
        self._opened = False
        self._start = 0.0
        self._next_due = []
        self._sequence = {}
        self.frames_generated = 0

    @property
    def description(self):
        names = ", ".join(item["name"] for item in self.channels)
        return f"SIMULATOR: {names} @ {self.speed:g}x (receive-only)"

    @property
    def diagnostics(self):
        return {
            "mode": "virtual dual-channel CAN",
            "opened": self._opened,
            "channels": [{"name": item["name"], "bitrate": item["bitrate"]}
                         for item in self.channels],
            "speed": self.speed,
            "frames_generated": self.frames_generated,
        }

    def open(self):
        if self._opened:
            return
        self._start = time.monotonic()
        self._next_due = [self._start for _ in self.channels]
        self._sequence = {item["name"]: 0 for item in self.channels}
        self.frames_generated = 0
        self._opened = True

    def close(self):
        self._opened = False

    def _make_frame(self, channel, elapsed):
        sequence = self._sequence[channel["name"]]
        ident, length = channel["frames"][sequence % len(channel["frames"])]
        data = bytes(((ident + sequence + index * 17) & 0xFF)
                     for index in range(length))
        self._sequence[channel["name"]] = sequence + 1
        return CanFrame(
            arbitration_id=ident,
            data=data,
            channel=channel["name"],
            timestamp=time.monotonic(),
            timestamp_clock_domain="host_monotonic",
            timestamp_source="simulator",
            source_timestamp=elapsed,
            source_timestamp_clock_domain="simulator_elapsed",
        )

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("CAN simulator is not open")
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            now = time.monotonic()
            ready = [i for i, due in enumerate(self._next_due) if due <= now]
            if ready:
                index = min(ready, key=lambda i: self._next_due[i])
                channel = self.channels[index]
                due = self._next_due[index]
                self._next_due[index] = due + channel["period"] / self.speed
                frame = self._make_frame(channel, due - self._start)
                self.frames_generated += 1
                return frame
            remaining = deadline - now
            if remaining <= 0:
                return None
            time.sleep(min(remaining, max(0.0, min(self._next_due) - now)))
