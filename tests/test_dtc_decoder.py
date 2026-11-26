import pytest

from freerov3r.diagnostics.dtc import decode_dtc_code, decode_j1979_dtcs


def test_decode_standard_dtc_categories_and_digits():
    assert decode_dtc_code(0x01, 0x33) == "P0133"
    assert decode_dtc_code(0x43, 0x21) == "C0321"
    assert decode_dtc_code(0x82, 0x10) == "B0210"
    assert decode_dtc_code(0xC1, 0x23) == "U0123"


@pytest.mark.parametrize(
    ("response", "status", "request_service"),
    [
        (bytes.fromhex("43 01 33 00 00"), "Stored", 0x03),
        (bytes.fromhex("47 01 33"), "Pending", 0x07),
        (bytes.fromhex("4A 01 33"), "Permanent", 0x0A),
    ],
)
def test_decode_j1979_dtc_services(response, status, request_service):
    codes = decode_j1979_dtcs(response)
    assert len(codes) == 1
    assert codes[0].code == "P0133"
    assert codes[0].status == status
    assert codes[0].request_service == request_service


def test_decode_iso_tp_single_frame_and_ignore_zero_padding():
    # PCI declares five payload bytes; the final 00 is CAN-frame padding.
    codes = decode_j1979_dtcs(bytes.fromhex("05 43 01 33 00 00 00"))
    assert [item.code for item in codes] == ["P0133"]


def test_expected_service_filters_other_dtc_statuses():
    assert decode_j1979_dtcs(bytes.fromhex("47 01 33"), expected_service=0x03) == []
    assert decode_j1979_dtcs(bytes.fromhex("43 01 33"), expected_service=0x03)[0].code == "P0133"


def test_unknown_service_and_malformed_records_are_ignored():
    assert decode_j1979_dtcs(bytes.fromhex("41 0C 1A F8")) == []
    assert decode_j1979_dtcs(bytes.fromhex("43 01")) == []
    assert decode_j1979_dtcs(b"") == []


def test_dtc_byte_range_is_validated():
    with pytest.raises(ValueError):
        decode_dtc_code(0x100, 0)
