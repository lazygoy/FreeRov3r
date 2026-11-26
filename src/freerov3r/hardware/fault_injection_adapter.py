"""Deterministic receive-side CAN fault injection for testing and replay.

Wraps an existing adapter. It never writes to the wrapped adapter and never
transmits CAN or serial data. Dropped, duplicated, and disconnect events are
deterministic so capture/recovery behavior can be reproduced in tests.
"""
from __future__ import annotations

import time

from .base import CanAdapter


class FaultInjectingCanAdapter(CanAdapter):
    """Apply deterministic receive faults to another CAN adapter.

    drop_every=N discards each Nth source frame.
    duplicate_every=N emits each Nth source frame twice.
    disconnect_after=N raises ConnectionError on the receive call after
    N source frames have been read. Reopening resets all fault counters.
    """

    def __init__(
        self,
        adapter,
        *,
        drop_every: int = 0,
        duplicate_every: int = 0,
        disconnect_after: int | None = None,
    ):
        self._validate_interval("drop_every", drop_every, allow_zero=True)
        self._validate_interval("duplicate_every", duplicate_every, allow_zero=True)
        if disconnect_after is not None:
            self._validate_interval("disconnect_after", disconnect_after, allow_zero=False)
        self.adapter = adapter
        self.drop_every = drop_every
        self.duplicate_every = duplicate_every
        self.disconnect_after = disconnect_after
        self._opened = False
        self._disconnected = False
        self._pending_duplicate = None
        self.frames_seen = 0
        self.frames_dropped = 0
        self.frames_duplicated = 0
        self.frames_emitted = 0

    @staticmethod
    def _validate_interval(name, value, *, allow_zero):
        if (isinstance(value, bool) or not isinstance(value, int)
                or value < (0 if allow_zero else 1)):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"{name} must be a {qualifier} integer")

    @property
    def description(self):
        return (
            f"FAULT-INJECTED: {self.adapter.description} "
            f"(drop every {self.drop_every or 'never'}, "
            f"duplicate every {self.duplicate_every or 'never'}, "
            f"disconnect after {self.disconnect_after or 'never'} frames)"
        )

    @property
    def diagnostics(self):
        return {
            "mode": "deterministic receive-side fault injection",
            "opened": self._opened,
            "disconnected": self._disconnected,
            "frames_seen": self.frames_seen,
            "frames_dropped": self.frames_dropped,
            "frames_duplicated": self.frames_duplicated,
            "frames_emitted": self.frames_emitted,
            "drop_every": self.drop_every,
            "duplicate_every": self.duplicate_every,
            "disconnect_after": self.disconnect_after,
            "transmission_performed": False,
        }

    def open(self):
        if self._opened:
            return
        self.adapter.open()
        self._disconnected = False
        self._pending_duplicate = None
        self.frames_seen = 0
        self.frames_dropped = 0
        self.frames_duplicated = 0
        self.frames_emitted = 0
        self._opened = True

    def close(self):
        try:
            self.adapter.close()
        finally:
            self._opened = False
            self._pending_duplicate = None

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("Fault-injecting CAN adapter is not open")
        if self._disconnected:
            raise ConnectionError("Simulated CAN adapter disconnect")
        if self._pending_duplicate is not None:
            frame = self._pending_duplicate
            self._pending_duplicate = None
            self.frames_emitted += 1
            return frame

        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if (self.disconnect_after is not None
                    and self.frames_seen >= self.disconnect_after):
                self._disconnected = True
                raise ConnectionError("Simulated CAN adapter disconnect")

            remaining = max(0.0, deadline - time.monotonic())
            frame = self.adapter.receive(timeout=remaining)
            if frame is None:
                return None

            self.frames_seen += 1
            if self.drop_every and self.frames_seen % self.drop_every == 0:
                self.frames_dropped += 1
                if time.monotonic() >= deadline:
                    return None
                continue

            if self.duplicate_every and self.frames_seen % self.duplicate_every == 0:
                self._pending_duplicate = frame
                self.frames_duplicated += 1

            self.frames_emitted += 1
            return frame
