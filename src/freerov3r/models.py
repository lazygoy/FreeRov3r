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



@dataclass(frozen=True)
class DiagnosticEvent:
    """Protocol-level diagnostic event, deliberately distinct from raw CAN frames."""

    source: str
    item_type: int
    timestamp_us: int
    timestamp_clock_domain: str
    module_handle: int
    logical_link_handle: int
    cop_handle: int | None = None
    cop_tag: int = 0
    payload: bytes = b""
    start_message_timestamp_us: int | None = None
    transmit_done_timestamp_us: int | None = None
    acceptance_id: int | None = None
    unique_response_identifier: int | None = None
    status_code: int | None = None
    error_code: int | None = None
    extra_error_info_id: int | None = None
    info_code: int | None = None
    extra_info_data: int | None = None

    def to_dict(self):
        """Return a JSON-safe record while retaining exact payload bytes as hex."""
        return {
            "source": self.source,
            "item_type": self.item_type,
            "timestamp_us": self.timestamp_us,
            "timestamp_clock_domain": self.timestamp_clock_domain,
            "module_handle": self.module_handle,
            "logical_link_handle": self.logical_link_handle,
            "cop_handle": self.cop_handle,
            "cop_tag": self.cop_tag,
            "payload_hex": self.payload.hex(),
            "payload_length": len(self.payload),
            "start_message_timestamp_us": self.start_message_timestamp_us,
            "transmit_done_timestamp_us": self.transmit_done_timestamp_us,
            "acceptance_id": self.acceptance_id,
            "unique_response_identifier": self.unique_response_identifier,
            "status_code": self.status_code,
            "error_code": self.error_code,
            "extra_error_info_id": self.extra_error_info_id,
            "info_code": self.info_code,
            "extra_info_data": self.extra_info_data,
        }
