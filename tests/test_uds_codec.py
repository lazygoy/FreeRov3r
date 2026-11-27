import pytest

from freerov3r.diagnostics.uds import (
    build_read_data_by_identifier_request,
    build_read_dtc_information_request,
    decode_uds_response,
)


def test_build_read_data_by_identifier_request():
    assert build_read_data_by_identifier_request([0xF190]) == bytes.fromhex("22 F1 90")
    assert build_read_data_by_identifier_request([0xF190, 0xF187]) == bytes.fromhex(
        "22 F1 90 F1 87"
    )


@pytest.mark.parametrize("dids", [[], [True], [-1], [0x10000], [0xF190, 0xF190], ["F190"]])
def test_read_data_by_identifier_rejects_invalid_dids(dids):
    with pytest.raises(ValueError):
        build_read_data_by_identifier_request(dids)


def test_read_data_by_identifier_limits_request_size():
    with pytest.raises(ValueError, match="32"):
        build_read_data_by_identifier_request(list(range(33)))


def test_build_read_dtc_information_only_allows_bounded_read_subfunctions():
    assert build_read_dtc_information_request(0x02, 0x8F) == bytes.fromhex("19 02 8F")
    assert build_read_dtc_information_request(0x0A) == bytes.fromhex("19 0A")
    for subfunction in (0x03, 0x04, 0x05, 0x14, 0xFF):
        with pytest.raises(ValueError):
            build_read_dtc_information_request(subfunction)


def test_decode_positive_read_data_by_identifier_response():
    request = bytes.fromhex("22 F1 90")
    result = decode_uds_response(
        bytes.fromhex("62 F1 90 31 32 33 34"),
        request=request,
    )
    assert result["kind"] == "positive"
    assert result["service"] == 0x22
    assert result["did"] == 0xF190
    assert result["record_data"] == "31323334"


def test_decode_rejects_wrong_service_or_wrong_did():
    with pytest.raises(ValueError, match="service"):
        decode_uds_response("59 02 FF", request="22 F1 90")
    with pytest.raises(ValueError, match="DID"):
        decode_uds_response("62 F1 87 31", request="22 F1 90")


def test_decode_negative_response_and_pending_status():
    result = decode_uds_response("7F 22 78", request="22 F1 90")
    assert result["kind"] == "negative"
    assert result["nrc"] == 0x78
    assert result["nrc_name"] == "requestCorrectlyReceivedResponsePending"
    assert result["response_pending"] is True


def test_decode_negative_response_rejects_wrong_original_service():
    with pytest.raises(ValueError, match="service"):
        decode_uds_response("7F 19 31", request="22 F1 90")


def test_decode_read_dtc_information_records():
    result = decode_uds_response("59 02 FF 01 23 45 2F 0A BC DE 08", request="19 02 FF")
    assert result["service"] == 0x19
    assert result["subfunction"] == 0x02
    assert result["dtc_status_availability_mask"] == 0xFF
    assert result["dtcs"] == [
        {"dtc": 0x012345, "status": 0x2F},
        {"dtc": 0x0ABCDE, "status": 0x08},
    ]


def test_decode_rejects_malformed_dtc_record_length():
    with pytest.raises(ValueError, match="four bytes"):
        decode_uds_response("59 02 FF 01 23 45", request="19 02 FF")


def test_codec_does_not_claim_to_transmit_or_identify_ecu():
    # Codec output is an application payload, not a CAN frame or ECU identity.
    request = build_read_data_by_identifier_request([0xF190])
    assert request == b"\x22\xf1\x90"



def test_decode_rejects_wrong_dtc_subfunction():
    with pytest.raises(ValueError, match="subfunction"):
        decode_uds_response("59 0A 00", request="19 02 FF")



def test_decode_rejects_wrong_dtc_subfunction():
    with pytest.raises(ValueError, match="subfunction"):
        decode_uds_response("59 0A 00", request="19 02 FF")


def test_decode_supported_dtcs_subfunction():
    result = decode_uds_response("59 0A FF 01 23 45 2F", request="19 0A")
    assert result["subfunction"] == 0x0A
    assert result["dtcs"] == [{"dtc": 0x012345, "status": 0x2F}]
