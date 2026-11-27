"""Transport-independent metadata for one CAN capture session."""

from dataclasses import dataclass
from time import time


@dataclass
class CaptureSessionContext:
    """Stable session identity and sequence boundaries shared by app workspaces."""

    interface: str
    channel: str
    bitrate: int
    vin: str | None
    started_at: float
    frame_start_index: int
    sample_start_index: int

    @classmethod
    def begin(
        cls, *, interface, channel, bitrate, vin, frame_start_index,
        sample_start_index, started_at=None,
    ):
        return cls(
            interface=str(interface),
            channel=str(channel),
            bitrate=int(bitrate),
            vin=vin or None,
            started_at=time() if started_at is None else float(started_at),
            frame_start_index=max(0, int(frame_start_index)),
            sample_start_index=max(0, int(sample_start_index)),
        )

    def elapsed_seconds(self, now=None):
        """Return non-negative wall-clock duration for display/archive metadata."""
        current = time() if now is None else float(now)
        return max(0.0, current - self.started_at)

    def event_metadata(self, *, frame_count, sample_count, dropped_samples=0):
        return {
            "interface": self.interface,
            "channel": self.channel or "Unknown",
            "bitrate": self.bitrate or "Unknown",
            "frames": int(frame_count),
            "sensor_samples": int(sample_count),
            "sensor_samples_dropped_from_bounded_buffer": max(0, int(dropped_samples)),
            "duration_seconds": round(self.elapsed_seconds(), 2),
        }
