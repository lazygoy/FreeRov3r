"""Bounded, passive CAN traffic monitoring and display filtering."""
from collections import Counter, deque
from dataclasses import dataclass
from .models import CanFrame


@dataclass(frozen=True)
class CanIdStats:
    arbitration_id: int
    extended: bool
    count: int
    frames_per_second: float
    last_seen: float


class CanMonitor:
    """Keep a bounded recent-frame window and lightweight traffic statistics."""

    def __init__(self, capacity=20000, rate_window=2.0):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = int(capacity)
        self.rate_window = float(rate_window)
        self.frames = deque(maxlen=self.capacity)
        self.counts = Counter()
        self.last_seen = {}
        self.recent = {}
        self.total_received = 0
        self.dropped_from_buffer = 0
        self._last_format = {}

    def reset(self):
        self.frames.clear()
        self.counts.clear()
        self.last_seen.clear()
        self.recent.clear()
        self.total_received = 0
        self.dropped_from_buffer = 0
        self._last_format.clear()

    def add(self, frame: CanFrame, now=None):
        import time
        now = time.monotonic() if now is None else float(now)
        if len(self.frames) == self.capacity:
            self.dropped_from_buffer += 1
        self.frames.append(frame)
        self.total_received += 1
        key = frame.arbitration_id
        self.counts[key] += 1
        self.last_seen[key] = now
        self._last_format[key] = bool(frame.is_extended_id)
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
        for arbitration_id, samples in self.recent.items():
            while samples and samples[0] < cutoff:
                samples.popleft()
            if samples:
                result.append(CanIdStats(
                    arbitration_id=arbitration_id,
                    extended=self._last_format.get(arbitration_id, False),
                    count=self.counts[arbitration_id],
                    frames_per_second=len(samples) / self.rate_window,
                    last_seen=self.last_seen[arbitration_id],
                ))
        return sorted(result, key=lambda item: (-item.frames_per_second, item.arbitration_id))

    @staticmethod
    def matches(frame, id_filter="", frame_format="All"):
        if frame_format == "Standard" and frame.is_extended_id:
            return False
        if frame_format == "Extended" and not frame.is_extended_id:
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
