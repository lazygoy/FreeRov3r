from freerov3r.can_research.protocol_hints import (
    classify_can_payload,
    classify_uds_payload,
)


def test_classify_single_frame_positive_uds_response_conservatively():
    protocol, hint = classify_can_payload(bytes.fromhex("03 7F 22 31"))

    assert protocol == "ISO-TP SF"
    assert hint.startswith("Negative response to ReadDataByIdentifier")


def test_classify_uds_payload_positive_response():
    assert classify_uds_payload(bytes.fromhex("62 F1 90")) == (
        "Positive response to ReadDataByIdentifier"
    )


def test_unknown_payload_is_not_given_a_false_service_identity():
    protocol, hint = classify_can_payload(bytes.fromhex("01 99"))

    assert protocol == "ISO-TP SF"
    assert hint == "Unclassified service"
