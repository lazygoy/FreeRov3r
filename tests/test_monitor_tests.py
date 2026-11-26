import pytest

from freerov3r.diagnostics.monitor_tests import (
    decode_mode06_results,
    decode_supported_monitor_ids,
)


def test_decode_supported_monitor_id_bitmap():
    assert decode_supported_monitor_ids(bytes.fromhex("46 00 80 00 00 01"), 0x00) == {
        0x01, 0x20
    }


def test_decode_mode06_result_record_and_limits():
    result = decode_mode06_results(
        bytes.fromhex("46 21 80 24 00 64 00 00 00 C8"),
        monitor_id=0x21,
        arbitration_id=0x7E8,
        channel="COM9",
    )
    record = result["results"][0]
    assert record["test_id"] == 0x80
    assert record["unit_scaling_id"] == 0x24
    assert record["value_raw"] == 100
    assert record["minimum_raw"] == 0
    assert record["maximum_raw"] == 200
    assert record["status"] == "within_limits"
    assert result["arbitration_id"] == 0x7E8


def test_decode_mode06_out_of_range_result():
    result = decode_mode06_results(
        bytes.fromhex("46 21 80 24 00 C9 00 00 00 C8"),
        monitor_id=0x21,
    )
    assert result["results"][0]["status"] == "outside_limits"


def test_decode_mode06_signed_values_from_uasid():
    result = decode_mode06_results(
        bytes.fromhex("46 21 80 80 FF F6 FF EC 00 00"),
        monitor_id=0x21,
    )
    record = result["results"][0]
    assert record["signed"] is True
    assert record["value_raw"] == -10
    assert record["minimum_raw"] == -20
    assert record["maximum_raw"] == 0
    assert record["status"] == "within_limits"


@pytest.mark.parametrize("payload", [
    bytes.fromhex("41 00 80 00 00 01"),
    bytes.fromhex("46 20 80 00 00 01"),
    bytes.fromhex("46 00 80 00 00"),
])
def test_rejects_invalid_supported_mid_payload(payload):
    with pytest.raises(ValueError):
        decode_supported_monitor_ids(payload, 0x00)


def test_rejects_incomplete_mode06_record():
    with pytest.raises(ValueError, match="9-byte records"):
        decode_mode06_results(bytes.fromhex("46 21 80 24 00 64"), monitor_id=0x21)


def test_rejects_wrong_monitor_id():
    with pytest.raises(ValueError, match="record monitor ID"):
        decode_mode06_results(bytes.fromhex("46 22 80 24 00 64 00 00 00 C8"), monitor_id=0x21)



def test_rejects_record_for_wrong_monitor_id():
    with pytest.raises(ValueError, match="record monitor ID"):
        decode_mode06_results(
            bytes.fromhex("46 22 80 24 00 64 00 00 00 C8"),
            monitor_id=0x21,
        )
