"""SAE J1979 Mode 06 on-board monitor test result decoding.

The CAN format is decoded into raw values and limits. Unit/scaling conversion
is intentionally not guessed: it requires a verified UASID definition.
"""

def decode_supported_monitor_ids(payload, base_mid):
    """Decode one complete Mode 06 supported-MID bitmap response (46 base A-D)."""
    payload = bytes(payload)
    base_mid = int(base_mid)
    if base_mid < 0 or base_mid > 0xE0 or base_mid % 0x20:
        raise ValueError("base_mid must be a Mode 06 bitmap base (00, 20, ... E0)")
    if len(payload) != 6 or payload[:2] != bytes((0x46, base_mid)):
        raise ValueError("Expected Mode 06 supported-monitor response 46 base A B C D")
    bitmap = int.from_bytes(payload[2:6], "big")
    return {
        base_mid + bit + 1
        for bit in range(32)
        if bitmap & (1 << (31 - bit))
    }


def decode_mode06_results(payload, *, monitor_id, arbitration_id=None,
                          is_extended_id=False, channel=None):
    """Decode complete Mode 06 response 46 MID followed by 9-byte records."""
    payload = bytes(payload)
    monitor_id = int(monitor_id)
    if not 0 <= monitor_id <= 0xFF:
        raise ValueError("monitor_id must be in the range 0..255")
    if len(payload) < 2 or payload[:2] != bytes((0x46, monitor_id)):
        raise ValueError("Mode 06 response does not match requested monitor ID")
    records = payload[2:]
    if len(records) % 9:
        raise ValueError(
            f"Mode 06 result data must contain complete 9-byte records; got {len(records)} bytes"
        )

    results = []
    for offset in range(0, len(records), 9):
        tid, uasid = records[offset:offset + 2]
        raw_value = int.from_bytes(records[offset + 2:offset + 4], "big")
        raw_min = int.from_bytes(records[offset + 4:offset + 6], "big")
        raw_max = int.from_bytes(records[offset + 6:offset + 8], "big")
        signed = bool(uasid & 0x80)

        def interpret(raw):
            return raw - 0x10000 if signed and raw & 0x8000 else raw

        value, minimum, maximum = map(interpret, (raw_value, raw_min, raw_max))
        results.append({
            "monitor_id": monitor_id,
            "test_id": tid,
            "unit_scaling_id": uasid,
            "signed": signed,
            "value_raw": value,
            "minimum_raw": minimum,
            "maximum_raw": maximum,
            "status": "within_limits" if minimum <= value <= maximum else "outside_limits",
            "raw": records[offset:offset + 9].hex().upper(),
        })

    return {
        "service": "06",
        "monitor_id": monitor_id,
        "results": results,
        "arbitration_id": arbitration_id,
        "is_extended_id": bool(is_extended_id),
        "channel": channel,
        "raw": payload.hex().upper(),
    }
