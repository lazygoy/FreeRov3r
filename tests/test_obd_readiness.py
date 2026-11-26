import pytest

from freerov3r.diagnostics.readiness import decode_obd_readiness


def test_decode_spark_ignition_readiness_and_mil_state():
    result = decode_obd_readiness(bytes.fromhex("83 00 FF 28"))
    assert result["mil_on"] is True
    assert result["dtc_count"] == 3
    assert result["ignition_type"] == "spark"
    monitors = {item["name"]: item for item in result["monitors"]}
    assert monitors["misfire"] == {
        "name": "misfire", "supported": True, "complete": True
    }
    assert monitors["catalyst"]["supported"] is True
    assert monitors["catalyst"]["complete"] is False
    assert monitors["ac_refrigerant"]["supported"] is True


def test_decode_pid_01_positive_response_prefix():
    result = decode_obd_readiness(bytes.fromhex("41 01 00 00 07 00"))
    assert result["mil_on"] is False
    assert result["dtc_count"] == 0
    assert result["monitors"][0]["complete"] is True


def test_unsupported_monitor_has_no_completion_claim():
    result = decode_obd_readiness(bytes.fromhex("00 00 01 00"))
    assert result["monitors"][0]["supported"] is True
    assert result["monitors"][0]["complete"] is True
    assert result["monitors"][1]["supported"] is False
    assert result["monitors"][1]["complete"] is None


def test_compression_ignition_does_not_apply_spark_monitor_names():
    result = decode_obd_readiness(bytes.fromhex("00 08 07 02"))
    assert result["ignition_type"] == "compression"
    assert [item["name"] for item in result["monitors"]] == [
        "misfire", "fuel_system", "comprehensive_components"
    ]
    assert result["monitors"][1]["complete"] is False


@pytest.mark.parametrize("payload", [b"", b"\x41\x01", bytes.fromhex("00 00 00")])
def test_reject_malformed_readiness_payload(payload):
    with pytest.raises(ValueError, match="exactly four data bytes"):
        decode_obd_readiness(payload)
