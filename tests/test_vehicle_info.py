import pytest

from freerov3r.diagnostics.vehicle_info import decode_j1979_vehicle_info


def test_decode_mode09_vin():
    vin = b"1GNEK13Z54R123456"
    result = decode_j1979_vehicle_info(
        bytes((0x49, 0x02, 0x01)) + vin,
        arbitration_id=0x7E8,
        channel="COM9",
    )
    assert result["items"] == [{"type": "vin", "value": vin.decode("ascii")}]
    assert result["arbitration_id"] == 0x7E8
    assert result["channel"] == "COM9"


def test_decode_mode09_multiple_calibration_ids():
    ids = b"CALIBRATION-ID01" + b"CALIBRATION-ID02"
    result = decode_j1979_vehicle_info(bytes((0x49, 0x04, 0x02)) + ids)
    assert [item["value"] for item in result["items"]] == [
        "CALIBRATION-ID01", "CALIBRATION-ID02"
    ]


def test_decode_mode09_cvns_as_hex():
    result = decode_j1979_vehicle_info(bytes.fromhex("49 06 02 01 02 03 04 A0 B0 C0 D0"))
    assert [item["value"] for item in result["items"]] == ["01020304", "A0B0C0D0"]


def test_decode_mode09_ecu_name():
    result = decode_j1979_vehicle_info(bytes((0x49, 0x0A, 0x01)) + b"ENGINE ECU".ljust(20, b" "))
    assert result["items"] == [{"type": "ecu_name", "value": "ENGINE ECU"}]


@pytest.mark.parametrize("payload", [
    bytes.fromhex("41 02 01") + b"1GNEK13Z54R123456",
    bytes.fromhex("49 03 01 00"),
    bytes.fromhex("49 02 01") + b"SHORT",
    bytes.fromhex("49 04 02") + b"TOO-SHORT",
])
def test_rejects_malformed_or_unsupported_mode09_payloads(payload):
    with pytest.raises(ValueError):
        decode_j1979_vehicle_info(payload)



def test_mode09_ecu_name_requires_twenty_byte_record():
    with pytest.raises(ValueError, match="expected 20 data bytes"):
        decode_j1979_vehicle_info(bytes((0x49, 0x0A, 0x01)) + b"ENGINE ECU")
