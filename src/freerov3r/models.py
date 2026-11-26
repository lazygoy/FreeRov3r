from dataclasses import dataclass


@dataclass(frozen=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False
    is_remote_frame: bool = False
    is_error_frame: bool = False
    channel: str | None = None
    timestamp: float | None = None
    device_timestamp_us: int | None = None
    timestamp_clock_domain: str = "unknown"
    timestamp_source: str = "unknown"
    source_timestamp: float | None = None
    source_timestamp_clock_domain: str | None = None
    device_timestamp_clock_domain: str | None = None
