from freerov3r.diagnostics.vin_decoder import VinFrameDecoder, validate_vin


VIN = "SALXXXXXXXXXXXX12"


def _frames(payload, can_id=0x7E8):
    payload = bytes(payload)
    first = bytes([0x10 | ((len(payload) >> 8) & 0x0F), len(payload) & 0xFF]) + payload[:6]
    frames = [first]
    remaining = payload[6:]
    sequence = 1
    while remaining:
        frames.append(bytes([0x20 | sequence]) + remaining[:7])
        remaining = remaining[7:]
        sequence = (sequence + 1) & 0x0F
    return [(can_id, frame.ljust(8, b"\x00")) for frame in frames]


def test_validate_vin_rejects_invalid_characters_and_lengths():
    assert validate_vin(VIN) == VIN
    assert validate_vin("SALIOQXXXXXXXXXXX") is None
    assert validate_vin("TOO-SHORT") is None


def test_decode_obd_mode09_vin_from_isotp_frames():
    decoder = VinFrameDecoder()
    payload = b"\x49\x02\x01" + VIN.encode("ascii")
    result = None
    for can_id, frame in _frames(payload):
        result = decoder.feed(can_id, frame) or result
    assert result == VIN


def test_decode_uds_f190_vin_from_isotp_frames():
    decoder = VinFrameDecoder()
    payload = b"\x62\xF1\x90" + VIN.encode("ascii")
    result = None
    for can_id, frame in _frames(payload, 0x7E9):
        result = decoder.feed(can_id, frame) or result
    assert result == VIN


def test_decoder_ignores_non_vin_payloads():
    decoder = VinFrameDecoder()
    assert decoder.feed(0x7E8, b"\x03\x41\x0C\x1A\xF8\x00\x00\x00") is None
