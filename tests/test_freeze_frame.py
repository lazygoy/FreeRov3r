import pytest

from freerov3r.diagnostics.freeze_frame import decode_freeze_frame_response


def test_decode_mode02_freeze_frame_reuses_mode01_scaling():
    result = decode_freeze_frame_response(
        bytes.fromhex("42 0C 00 1A F8"),
        arbitration_id=0x7E8,
        channel="COM9",
        frame_number=0,
    )
    assert result["service"] == "02"
    assert result["pid"] == "0C"
    assert result["frame_number"] == 0
    assert result["arbitration_id"] == 0x7E8
    assert result["channel"] == "COM9"
    assert result["measurements"][0]["name"] == "Engine speed"
    assert result["measurements"][0]["value"] == 1726.0


def test_decode_mode02_preserves_extended_ecu_addressing():
    result = decode_freeze_frame_response(
        bytes.fromhex("42 05 00 50"),
        arbitration_id=0x18DAF110,
        is_extended_id=True,
        frame_number=0,
    )
    assert result["is_extended_id"] is True
    assert result["measurements"][0]["value"] == 40.0


@pytest.mark.parametrize("payload", [
    b"",
    bytes.fromhex("41 0C 00 1A F8"),
    bytes.fromhex("42 0C 01 1A F8"),
    bytes.fromhex("42 FE 00 00"),
])
def test_reject_invalid_mode02_freeze_frame_response(payload):
    with pytest.raises(ValueError):
        decode_freeze_frame_response(
            payload, arbitration_id=0x7E8, frame_number=0
        )
