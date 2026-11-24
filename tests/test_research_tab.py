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



def test_marker_window_comparison_uses_monotonic_elapsed_time():
    from freerov3r.research_tab import analyze_marker_windows

    frames = [
        {"elapsed_seconds": 7.0, "arbitration_id": 0x100, "data": "0102"},
        {"elapsed_seconds": 8.0, "arbitration_id": 0x100, "data": "0102"},
        {"elapsed_seconds": 8.5, "arbitration_id": 0x100, "data": "0102"},
        {"elapsed_seconds": 10.0, "arbitration_id": 0x700, "data": "0322f190"},
        {"elapsed_seconds": 11.0, "arbitration_id": 0x700, "data": "0322f190"},
        {"timestamp": 9999999999, "arbitration_id": 0x555, "data": "00"},
    ]
    markers = [{"elapsed_seconds": 10.0, "operation": "Read ECU information"}]
    result = analyze_marker_windows(frames, markers)[0]
    assert result["before_frames"] == 2
    assert result["after_frames"] == 2
    change = next(item for item in result["changes"] if item["can_id"] == 0x700)
    assert change["before_count"] == 0
    assert change["after_count"] == 2
    assert change["delta"] == 2
    assert all(item["can_id"] != 0x555 for item in result["changes"])


def test_marker_window_comparison_rejects_negative_windows():
    import pytest
    from freerov3r.research_tab import analyze_marker_windows

    with pytest.raises(ValueError):
        analyze_marker_windows([], [], before_seconds=-1)


def test_marker_window_comparison_handles_missing_timestamps_and_no_change():
    from freerov3r.research_tab import analyze_marker_windows

    result = analyze_marker_windows(
        [{"timestamp": 1.0, "arbitration_id": 0x100, "data": "01"}],
        [{"elapsed_seconds": 2.0, "operation": "Scan"}],
    )[0]
    assert result["timed_frame_count"] == 0
    assert result["changes"] == []
