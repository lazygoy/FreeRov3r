"""VIN extraction from observed ISO-TP diagnostic response frames."""
import re


VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def validate_vin(value: str) -> str | None:
    value = value.strip().upper()
    return value if VIN_RE.fullmatch(value) else None


def _vin_from_payload(payload: bytes) -> str | None:
    # OBD-II Mode 09 PID 02: 49 02 [record] [17 ASCII VIN bytes]
    # UDS ReadDataByIdentifier F190: 62 F1 90 [17 ASCII VIN bytes]
    offset = None
    if payload.startswith(b"\x49\x02"):
        offset = 3 if len(payload) >= 20 and payload[2] in (1, 2, 3) else 2
    elif payload.startswith(b"\x62\xF1\x90"):
        offset = 3
    if offset is None or len(payload) < offset + 17:
        return None
    try:
        text = payload[offset:offset + 17].decode("ascii")
    except UnicodeDecodeError:
        return None
    return validate_vin(text)


class VinFrameDecoder:
    """Reassembles ISO-TP single/first/consecutive frames by CAN response ID."""

    def __init__(self):
        self._pending = {}

    def reset(self):
        self._pending.clear()

    def feed(self, arbitration_id: int, data: bytes) -> str | None:
        if not data:
            return None
        pci_type = data[0] >> 4
        if pci_type == 0:
            length = data[0] & 0x0F
            return _vin_from_payload(data[1:1 + length])
        if pci_type == 1 and len(data) >= 2:
            total = ((data[0] & 0x0F) << 8) | data[1]
            self._pending[arbitration_id] = {
                "total": total,
                "buffer": bytearray(data[2:]),
            }
            return None
        if pci_type == 2 and arbitration_id in self._pending:
            pending = self._pending[arbitration_id]
            pending["buffer"].extend(data[1:])
            if len(pending["buffer"]) >= pending["total"]:
                payload = bytes(pending["buffer"][:pending["total"]])
                self._pending.pop(arbitration_id, None)
                return _vin_from_payload(payload)
        return None
