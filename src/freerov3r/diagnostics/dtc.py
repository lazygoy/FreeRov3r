"""Conservative SAE J1979 diagnostic trouble-code decoding.

This module decodes standard two-byte DTC identifiers from already-received
Mode 03 (stored), Mode 07 (pending), and Mode 0A (permanent) responses.
It does not assign OEM-specific descriptions or infer which ECU reported a code.
"""
from dataclasses import dataclass


SERVICE_STATUS = {
    0x43: ("Stored", 0x03),
    0x47: ("Pending", 0x07),
    0x4A: ("Permanent", 0x0A),
}


@dataclass(frozen=True)
class DiagnosticTroubleCode:
    """A decoded J1979 DTC with its originating response service."""

    code: str
    status: str
    request_service: int
    response_service: int
    raw: bytes

    def to_dict(self):
        return {
            "code": self.code,
            "status": self.status,
            "request_service": f"{self.request_service:02X}",
            "response_service": f"{self.response_service:02X}",
            "raw": self.raw.hex().upper(),
        }


def decode_dtc_code(high: int, low: int) -> str:
    """Decode one standard two-byte SAE J2012/J1979 DTC."""
    high = int(high)
    low = int(low)
    if not 0 <= high <= 0xFF or not 0 <= low <= 0xFF:
        raise ValueError("DTC bytes must be in the range 0x00..0xFF")
    system = "PCBU"[(high >> 6) & 0x03]
    first_digit = (high >> 4) & 0x03
    return f"{system}{first_digit:X}{high & 0x0F:X}{low:02X}"


def decode_j1979_dtcs(payload, *, expected_service=None):
    """Decode DTCs from a complete J1979 positive-response payload.

    Accepts application payloads such as 43 01 33 00 00 and ISO-TP
    Single-Frame data such as 06 43 01 33 00 00 00. Padding zero pairs
    are ignored. Multi-frame payloads must be reassembled before calling.
    """
    data = bytes(payload or b"")
    if not data:
        return []

    # Strip a classic ISO-TP Single-Frame PCI length when it encloses a
    # recognized positive response. Do not mistake service bytes for PCI.
    if (data[0] >> 4) == 0 and len(data) >= 2:
        declared = data[0] & 0x0F
        if declared and declared <= len(data) - 1 and data[1] in SERVICE_STATUS:
            data = data[1:1 + declared]

    response_service = data[0]
    service_info = SERVICE_STATUS.get(response_service)
    if service_info is None:
        return []
    status, request_service = service_info
    if expected_service is not None and int(expected_service) != request_service:
        return []
    records = data[1:]
    if len(records) % 2:
        return []

    decoded = []
    for offset in range(0, len(records), 2):
        raw = records[offset:offset + 2]
        if raw == b"\x00\x00":
            continue
        decoded.append(DiagnosticTroubleCode(
            code=decode_dtc_code(raw[0], raw[1]),
            status=status,
            request_service=request_service,
            response_service=response_service,
            raw=raw,
        ))
    return decoded
