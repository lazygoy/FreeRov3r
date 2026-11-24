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
