"""Read-only SAE J1979 Mode 09 vehicle identification decoders.

Only standardized response formats are decoded. Unknown PIDs and malformed
payloads are rejected rather than being assigned guessed meanings.
"""

PID_NAMES = {
    0x02: "Vehicle identification number",
    0x04: "Calibration identification",
    0x06: "Calibration verification number",
    0x0A: "ECU name",
}

_FIXED_WIDTHS = {0x02: 17, 0x04: 16, 0x06: 4}


def decode_j1979_vehicle_info(payload, *, arbitration_id=None,
                              is_extended_id=False, channel=None):
    """Decode one complete positive Mode 09 response (49 PID count data...)."""
    payload = bytes(payload)
    if len(payload) < 3 or payload[0] != 0x49:
        raise ValueError("Expected a complete positive Mode 09 response")
    pid = payload[1]
    if pid not in PID_NAMES:
        raise ValueError(f"Unsupported Mode 09 PID: 0x{pid:02X}")

    count = payload[2]
    data = payload[3:]
    width = _FIXED_WIDTHS.get(pid)
    if width is not None:
        expected = count * width
        if len(data) != expected:
            raise ValueError(
                f"Mode 09 PID 0x{pid:02X} expected {expected} data bytes, "
                f"received {len(data)}"
            )
        chunks = [data[index:index + width] for index in range(0, len(data), width)]
    else:
        if count == 0 and data:
            raise ValueError("Mode 09 ECU-name response has data but zero count")
        chunks = [data] if count else []

    items = []
    for chunk in chunks:
        if pid == 0x02:
            try:
                value = chunk.decode("ascii").strip("\x00 ")
            except UnicodeDecodeError as exc:
                raise ValueError("VIN response contains non-ASCII data") from exc
            if len(value) != 17:
                raise ValueError(f"VIN response must contain 17 characters, got {len(value)}")
            items.append({"type": "vin", "value": value})
        elif pid == 0x04:
            try:
                value = chunk.decode("ascii").strip("\x00 ")
            except UnicodeDecodeError as exc:
                raise ValueError("Calibration ID contains non-ASCII data") from exc
            items.append({"type": "calibration_id", "value": value})
        elif pid == 0x06:
            items.append({"type": "cvn", "value": chunk.hex().upper()})
        else:
            try:
                value = chunk.decode("ascii").strip("\x00 ")
            except UnicodeDecodeError as exc:
                raise ValueError("ECU name contains non-ASCII data") from exc
            items.append({"type": "ecu_name", "value": value})

    return {
        "service": "09",
        "pid": pid,
        "name": PID_NAMES[pid],
        "count": count,
        "items": items,
        "arbitration_id": arbitration_id,
        "is_extended_id": bool(is_extended_id),
        "channel": channel,
        "raw": payload.hex().upper(),
    }
