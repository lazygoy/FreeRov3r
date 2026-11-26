"""Bounded, passive CAN traffic monitoring and display filtering."""
from collections import Counter, deque
from dataclasses import dataclass
from statistics import median
from .models import CanFrame


@dataclass(frozen=True)
class CanIdStats:
    arbitration_id: int
    extended: bool
    count: int
    frames_per_second: float
    last_seen: float
    payload_changes: int
    median_interval_ms: float | None


class CanMonitor:
    """Keep a bounded recent-frame window and lightweight traffic statistics."""

    def __init__(self, capacity=20000, rate_window=2.0, max_ids=4096):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = int(capacity)
        self.rate_window = float(rate_window)
        self.max_ids = max(1, int(max_ids))
        self.frames = deque(maxlen=self.capacity)
        self.counts = Counter()
        self.last_seen = {}
        self.recent = {}
        self.last_payload = {}
        self.payload_changes = Counter()
        self.intervals = {}
        self.total_received = 0
        self.dropped_from_buffer = 0

    def reset(self):
        self.frames.clear()
        self.counts.clear()
        self.last_seen.clear()
        self.recent.clear()
        self.last_payload.clear()
        self.payload_changes.clear()
        self.intervals.clear()
        self.total_received = 0
        self.dropped_from_buffer = 0

    def add(self, frame: CanFrame, now=None):
        import time
        now = time.monotonic() if now is None else float(now)
        if len(self.frames) == self.capacity:
            self.dropped_from_buffer += 1
        self.frames.append(frame)
        self.total_received += 1
        key = (frame.arbitration_id, bool(frame.is_extended_id))
        if key not in self.recent and len(self.recent) >= self.max_ids:
            oldest = min(self.last_seen, key=self.last_seen.get)
            self.recent.pop(oldest, None)
            self.counts.pop(oldest, None)
            self.last_payload.pop(oldest, None)
            self.payload_changes.pop(oldest, None)
            self.intervals.pop(oldest, None)
            self.last_seen.pop(oldest, None)
        previous_seen = self.last_seen.get(key)
        payload = bytes(frame.data)
        if previous_seen is not None:
            interval = now - previous_seen
            if interval > 0:
                self.intervals.setdefault(key, deque(maxlen=64)).append(interval)
            if self.last_payload.get(key) != payload:
                self.payload_changes[key] += 1
        self.last_payload[key] = payload
        self.counts[key] += 1
        self.last_seen[key] = now
        samples = self.recent.setdefault(key, deque())
        samples.append(now)
        cutoff = now - self.rate_window
        while samples and samples[0] < cutoff:
            samples.popleft()

    def rate(self, now=None):
        import time
        now = time.monotonic() if now is None else float(now)
        cutoff = now - self.rate_window
        total = 0
        for samples in self.recent.values():
            while samples and samples[0] < cutoff:
                samples.popleft()
            total += len(samples)
        return total / self.rate_window

    def id_stats(self, now=None):
        import time
        now = time.monotonic() if now is None else float(now)
        cutoff = now - self.rate_window
        result = []
        for (arbitration_id, extended), samples in self.recent.items():
            while samples and samples[0] < cutoff:
                samples.popleft()
            if samples:
                result.append(CanIdStats(
                    arbitration_id=arbitration_id,
                    extended=extended,
                    count=self.counts[(arbitration_id, extended)],
                    frames_per_second=len(samples) / self.rate_window,
                    last_seen=self.last_seen[(arbitration_id, extended)],
                    payload_changes=self.payload_changes[(arbitration_id, extended)],
                    median_interval_ms=(
                        median(self.intervals[(arbitration_id, extended)]) * 1000.0
                        if self.intervals.get((arbitration_id, extended)) else None
                    ),
                ))
        return sorted(result, key=lambda item: (-item.frames_per_second, item.arbitration_id))

    @staticmethod
    def matches(frame, id_filter="", frame_format="All", data_filter=""):
        """Return whether a frame matches display-only ID, format, and payload filters.

        Payload filters are hexadecimal byte sequences. Whitespace is optional;
        a sequence matches anywhere within the frame payload.
        """
        if frame_format == "Standard" and frame.is_extended_id:
            return False
        if frame_format == "Extended" and not frame.is_extended_id:
            return False
        payload_value = (data_filter or "").strip()
        if payload_value:
            try:
                payload = bytes.fromhex(payload_value)
            except ValueError:
                return False
            if not payload or payload not in bytes(frame.data):
                return False
        value = (id_filter or "").strip().replace("0x", "").replace("0X", "")
        if not value:
            return True
        try:
            if "-" in value:
                start, end = value.split("-", 1)
                low, high = int(start.strip(), 16), int(end.strip(), 16)
                if low > high:
                    low, high = high, low
                return low <= frame.arbitration_id <= high
            return frame.arbitration_id == int(value, 16)
        except ValueError:
            return False
