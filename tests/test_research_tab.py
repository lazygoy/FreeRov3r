import csv

from freerov3r.research_tab import (
    classify_can_payload,
    classify_uds_payload,
    load_capture_file,
)


def test_classify_isotp_uds_request_and_response():
    assert classify_can_payload(bytes.fromhex("03 22 F1 90")) == (
        "ISO-TP SF", "ReadDataByIdentifier"
    )
    assert classify_can_payload(bytes.fromhex("03 62 F1 90")) == (
        "ISO-TP SF", "Positive response to ReadDataByIdentifier (0x62)"
    )


def test_classify_negative_response():
    iso, hint = classify_can_payload(bytes.fromhex("03 7F 22 31"))
    assert iso == "ISO-TP SF"
    assert hint == "Negative response to ReadDataByIdentifier (NRC 0x31)"


def test_classify_isotp_transport_frames():
    assert classify_can_payload(bytes.fromhex("10 14 62 F1 F0 01 02 03"))[0] == "ISO-TP FF"
    assert classify_can_payload(bytes.fromhex("21 04 05 06 07 08 09 0A"))[0] == "ISO-TP CF"
    assert classify_can_payload(bytes.fromhex("30 00 00"))[0] == "ISO-TP FC"


def test_load_free_rover_csv_hex_id_and_boolean_extended(tmp_path):
    path = tmp_path / "capture.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "id", "extended", "dlc", "data"])
        writer.writerow(["12.5", "7E8", "0", "4", "03 41 0C 1A"])
    metadata, frames = load_capture_file(path)
    assert metadata == {}
    assert len(frames) == 1
    assert frames[0]["arbitration_id"] == 0x7E8
    assert frames[0]["extended"] is False
    assert frames[0]["data"] == "03410c1a"


def test_load_candump_with_channel_prefix(tmp_path):
    path = tmp_path / "capture.log"
    path.write_text("(12.500000) can0 7E8#03410C1A\n", encoding="utf-8")
    _, frames = load_capture_file(path)
    assert len(frames) == 1
    assert frames[0]["timestamp"] == 12.5
    assert frames[0]["arbitration_id"] == 0x7E8
    assert frames[0]["data"] == "03410c1a"



def test_classify_reassembled_uds_payloads():
    assert classify_uds_payload(bytes.fromhex("22 F1 90")) == "ReadDataByIdentifier"
    assert classify_uds_payload(bytes.fromhex("62 F1 90")) == (
        "Positive response to ReadDataByIdentifier"
    )
    assert classify_uds_payload(bytes.fromhex("7F 22 31")) == (
        "Negative response to ReadDataByIdentifier (NRC 0x31)"
    )
