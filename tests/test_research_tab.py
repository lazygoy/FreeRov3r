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



def test_operation_sequence_comparison_aggregates_capture_evidence():
    from freerov3r.research_tab import compare_operation_sequences

    common_frames = [
        {"elapsed_seconds": 8.0, "arbitration_id": 0x700, "data": "0102"},
        {"elapsed_seconds": 9.0, "arbitration_id": 0x700, "data": "0102"},
        {"elapsed_seconds": 10.5, "arbitration_id": 0x700, "data": "0102"},
        {"elapsed_seconds": 11.5, "arbitration_id": 0x700, "data": "0102"},
    ]
    captures = [
        {
            "name": "successful scan",
            "frames": common_frames + [
                {"elapsed_seconds": 12.0, "arbitration_id": 0x701, "data": "03 7F 22 31"}
            ],
            "markers": [
                {"elapsed_seconds": 10.0, "operation": "Full module scan"},
                {"elapsed_seconds": 20.0, "operation": "Read DTCs"},
            ],
        },
        {
            "name": "failed scan",
            "frames": common_frames,
            "markers": [
                {"elapsed_seconds": 10.0, "operation": "Full module scan"},
            ],
        },
    ]

    result = compare_operation_sequences(captures)
    assert result["capture_count"] == 2
    assert result["capture_sequences"][0]["operations"] == [
        "Full module scan", "Read DTCs"
    ]
    scan = next(item for item in result["operations"]
                if item["operation"] == "Full module scan")
    repeated = next(item for item in scan["signals"] if item["can_id"] == 0x700)
    assert repeated["capture_count"] == 2
    assert repeated["repeatability"] == "Seen in multiple captures"
    assert repeated["average_before_frames_per_second"] == 1.0
    assert repeated["average_after_frames_per_second"] == 0.4
    assert repeated["median_response_delay_seconds"] == 0.5

    one_off = next(item for item in scan["signals"] if item["can_id"] == 0x701)
    assert one_off["capture_count"] == 1
    assert one_off["repeatability"] == "Seen in one capture only"


def test_operation_sequence_comparison_rejects_nonpositive_windows():
    import pytest
    from freerov3r.research_tab import compare_operation_sequences

    with pytest.raises(ValueError):
        compare_operation_sequences([], after_seconds=0)



def test_operation_sequence_comparison_reports_order_differences():
    from freerov3r.research_tab import compare_operation_sequences

    captures = [
        {
            "name": "reference",
            "frames": [],
            "markers": [
                {"elapsed_seconds": 1, "operation": "Connect"},
                {"elapsed_seconds": 2, "operation": "Scan"},
                {"elapsed_seconds": 3, "operation": "Read DTCs"},
            ],
        },
        {
            "name": "missing step",
            "frames": [],
            "markers": [
                {"elapsed_seconds": 1, "operation": "Connect"},
                {"elapsed_seconds": 2, "operation": "Read DTCs"},
            ],
        },
        {
            "name": "extra step",
            "frames": [],
            "markers": [
                {"elapsed_seconds": 1, "operation": "Connect"},
                {"elapsed_seconds": 2, "operation": "Scan"},
                {"elapsed_seconds": 3, "operation": "Clear filters"},
                {"elapsed_seconds": 4, "operation": "Read DTCs"},
            ],
        },
    ]

    result = compare_operation_sequences(captures)
    comparisons = {item["capture_name"]: item
                   for item in result["sequence_comparisons"]}

    missing = comparisons["missing step"]
    assert not missing["matches_reference"]
    assert missing["changes"] == [{
        "change_type": "delete",
        "reference_index": 1,
        "capture_index": 1,
        "reference_operations": ["Scan"],
        "capture_operations": [],
    }]

    extra = comparisons["extra step"]
    assert not extra["matches_reference"]
    assert extra["changes"] == [{
        "change_type": "insert",
        "reference_index": 2,
        "capture_index": 2,
        "reference_operations": [],
        "capture_operations": ["Clear filters"],
    }]


def test_operation_sequence_comparison_identical_order_has_no_changes():
    from freerov3r.research_tab import compare_operation_sequences

    captures = [
        {"name": "one", "frames": [], "markers": [
            {"elapsed_seconds": 1, "operation": "Connect"},
            {"elapsed_seconds": 2, "operation": "Scan"},
        ]},
        {"name": "two", "frames": [], "markers": [
            {"elapsed_seconds": 1, "operation": "Connect"},
            {"elapsed_seconds": 2, "operation": "Scan"},
        ]},
    ]
    result = compare_operation_sequences(captures)
    assert result["sequence_comparisons"][0]["matches_reference"] is True
    assert result["sequence_comparisons"][0]["changes"] == []
