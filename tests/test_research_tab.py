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



def test_operation_uds_transactions_are_correlated_per_capture():
    from freerov3r.research_tab import summarize_operation_uds_transactions

    def capture(name, response_data):
        return {
            "name": name,
            "markers": [{"elapsed_seconds": 10.0, "operation": "Read ECU info"}],
            "frames": [
                {"elapsed_seconds": 10.10, "arbitration_id": 0x7E0,
                 "data": "03 22 F1 90", "channel": "can0"},
                {"elapsed_seconds": 10.15, "arbitration_id": 0x7E8,
                 "data": response_data, "channel": "can0"},
                # This wall-clock-only frame must not be mixed into monotonic analysis.
                {"timestamp": 10.16, "arbitration_id": 0x7E8,
                 "data": "03 62 F1 90", "channel": "can0"},
            ],
        }

    result = summarize_operation_uds_transactions([
        capture("positive one", "03 62 F1 90"),
        capture("positive two", "03 62 F1 90"),
        capture("negative", "03 7F 22 31"),
    ])

    assert len(result) == 1
    operation = result[0]
    assert operation["operation"] == "Read ECU info"
    assert operation["capture_count"] == 3
    positive = next(item for item in operation["transactions"]
                    if item["response_kind"] == "positive")
    negative = next(item for item in operation["transactions"]
                    if item["response_kind"] == "negative")
    assert positive["capture_count"] == 2
    assert positive["repeatability"] == "Seen in multiple captures"
    assert abs(positive["median_latency_seconds"] - 0.05) < 1e-9
    assert positive["request_payload"] == "22f190"
    assert positive["response_payload"] == "62f190"
    assert negative["capture_count"] == 1
    assert negative["response_payload"] == "7f2231"


def test_operation_uds_transaction_summary_ignores_unmarked_or_incomplete_data():
    from freerov3r.research_tab import summarize_operation_uds_transactions

    capture = {
        "name": "unmarked",
        "markers": [],
        "frames": [
            {"elapsed_seconds": 1.0, "arbitration_id": 0x7E0,
             "data": "03 22 F1 90"},
            {"elapsed_seconds": 1.1, "arbitration_id": 0x7E8,
             "data": "03 62 F1 90"},
        ],
    }
    assert summarize_operation_uds_transactions([capture]) == []



def test_operation_uds_summary_counts_capture_with_no_transaction():
    from freerov3r.research_tab import summarize_operation_uds_transactions

    result = summarize_operation_uds_transactions([
        {
            "name": "responding",
            "markers": [{"elapsed_seconds": 1, "operation": "Module scan"}],
            "frames": [
                {"elapsed_seconds": 1.1, "arbitration_id": 0x7E0, "data": "03 22 F1 90"},
                {"elapsed_seconds": 1.2, "arbitration_id": 0x7E8, "data": "03 62 F1 90"},
            ],
        },
        {
            "name": "silent",
            "markers": [{"elapsed_seconds": 1, "operation": "Module scan"}],
            "frames": [],
        },
    ])
    assert result[0]["capture_count"] == 2
    assert result[0]["transactions"][0]["capture_count"] == 1



def test_load_json_preserves_monotonic_elapsed_seconds(tmp_path):
    import json

    path = tmp_path / "marked-session.json"
    path.write_text(json.dumps({
        "metadata": {"session_name": "marked"},
        "markers": [{"elapsed_seconds": 5.0, "operation": "Scan"}],
        "frames": [{
            "timestamp": 1730000000.0,
            "elapsed_seconds": 5.25,
            "arbitration_id": 0x7E0,
            "extended": False,
            "data": "0322f190",
            "channel": "can0",
        }],
    }), encoding="utf-8")

    metadata, frames = load_capture_file(path)
    assert metadata["markers"][0]["operation"] == "Scan"
    assert frames[0]["timestamp"] == 1730000000.0
    assert frames[0]["elapsed_seconds"] == 5.25



def test_load_json_keeps_can_frame_when_elapsed_time_is_invalid(tmp_path):
    import json

    path = tmp_path / "bad-elapsed.json"
    path.write_text(json.dumps({
        "frames": [{
            "timestamp": 12.0,
            "elapsed_seconds": "not-a-clock",
            "arbitration_id": 0x700,
            "data": "0102",
        }]
    }), encoding="utf-8")

    _, frames = load_capture_file(path)
    assert len(frames) == 1
    assert frames[0]["arbitration_id"] == 0x700
    assert "elapsed_seconds" not in frames[0]



def test_operation_uds_identifier_summary_extracts_multiple_dids():
    from freerov3r.research_tab import summarize_operation_uds_identifiers

    summaries = [{
        "operation": "Read vehicle identity",
        "transactions": [
            {
                "service": 0x22,
                "request_payload": "22f190f187",
                "response_payload": "62f19012345662f187abcd",
                "response_kind": "positive",
                "capture_names": ["run 1", "run 2"],
                "count": 2,
            },
            {
                "service": 0x22,
                "request_payload": "22f190",
                "response_payload": "7f2231",
                "response_kind": "negative",
                "capture_names": ["run 3"],
                "count": 1,
            },
        ],
    }]

    result = summarize_operation_uds_identifiers(summaries)
    vin_did = next(item for item in result if item["identifier"] == 0xF190)
    other_did = next(item for item in result if item["identifier"] == 0xF187)

    assert vin_did["kind"] == "DID"
    assert vin_did["capture_count"] == 3
    assert vin_did["request_count"] == 3
    assert vin_did["positive_count"] == 2
    assert vin_did["negative_count"] == 1
    assert vin_did["repeatability"] == "Seen in multiple captures"
    assert other_did["capture_count"] == 2
    assert other_did["positive_count"] == 2


def test_operation_uds_identifier_summary_extracts_routine_control():
    from freerov3r.research_tab import summarize_operation_uds_identifiers

    result = summarize_operation_uds_identifiers([{
        "operation": "Run scanner routine",
        "transactions": [
            {
                "service": 0x31,
                "request_payload": "3101a201",
                "response_payload": "7101a201",
                "response_kind": "positive",
                "capture_names": ["routine A", "routine B"],
                "count": 2,
            },
            {
                "service": 0x31,
                "request_payload": "3102a201",
                "response_payload": "7f3178",
                "response_kind": "negative",
                "capture_names": ["routine C"],
                "count": 1,
            },
        ],
    }])

    start = next(item for item in result if item["subfunction"] == 0x01)
    stop = next(item for item in result if item["subfunction"] == 0x02)
    assert start["identifier"] == 0xA201
    assert start["routine_control_type"] == 0x01
    assert start["capture_count"] == 2
    assert start["positive_count"] == 2
    assert stop["identifier"] == 0xA201
    assert stop["negative_count"] == 1



def test_operation_uds_identifier_summary_distinguishes_did_access_modes():
    from freerov3r.research_tab import summarize_operation_uds_identifiers

    result = summarize_operation_uds_identifiers([{
        "operation": "Inspect configuration",
        "transactions": [
            {
                "service": 0x22,
                "request_payload": "22f1a0",
                "response_payload": "62f1a0aa",
                "response_kind": "positive",
                "capture_names": ["read"],
            },
            {
                "service": 0x2E,
                "request_payload": "2ef1a001",
                "response_payload": "6ef1a0",
                "response_kind": "positive",
                "capture_names": ["write"],
            },
            {
                "service": 0x2F,
                "request_payload": "2ff1a00301",
                "response_payload": "6ff1a0",
                "response_kind": "positive",
                "capture_names": ["io"],
            },
        ],
    }])
    modes = {item["access"] for item in result}
    assert modes == {"Read", "Write", "I/O control"}
    assert len(result) == 3



def test_operation_did_response_variation_reports_raw_variable_byte_offsets():
    from freerov3r.research_tab import summarize_operation_did_response_variation

    result = summarize_operation_did_response_variation([{
        "operation": "Read module identity",
        "transactions": [
            {
                "service": 0x22,
                "request_payload": "22f190",
                "response_payload": "62f190123456",
                "response_kind": "positive",
                "capture_names": ["baseline", "repeat"],
                "count": 2,
            },
            {
                "service": 0x22,
                "request_payload": "22f190",
                "response_payload": "62f190123499",
                "response_kind": "positive",
                "capture_names": ["changed"],
                "count": 1,
            },
        ],
    }])

    assert len(result) == 1
    item = result[0]
    assert item["did"] == 0xF190
    assert item["capture_count"] == 3
    assert item["total_count"] == 3
    assert item["distinct_value_count"] == 2
    assert item["value_lengths"] == [3]
    assert item["variable_byte_offsets"] == [2]
    assert item["data_pattern"] == "Byte values vary"


def test_operation_did_response_variation_skips_multidid_and_unmatched_responses():
    from freerov3r.research_tab import summarize_operation_did_response_variation

    result = summarize_operation_did_response_variation([{
        "operation": "Read several identifiers",
        "transactions": [
            {
                "service": 0x22,
                "request_payload": "22f190f187",
                "response_payload": "62f1900102f1870304",
                "response_kind": "positive",
                "capture_names": ["multi"],
            },
            {
                "service": 0x22,
                "request_payload": "22f190",
                "response_payload": "7f2231",
                "response_kind": "negative",
                "capture_names": ["negative"],
            },
            {
                "service": 0x22,
                "request_payload": "22f190",
                "response_payload": "62f1870102",
                "response_kind": "positive",
                "capture_names": ["wrong-did"],
            },
        ],
    }])
    assert result == []


def test_operation_did_response_variation_reports_length_variants():
    from freerov3r.research_tab import summarize_operation_did_response_variation

    result = summarize_operation_did_response_variation([{
        "operation": "Read variable record",
        "transactions": [
            {
                "service": 0x22,
                "request_payload": "22f1a0",
                "response_payload": "62f1a00102",
                "response_kind": "positive",
                "capture_names": ["short"],
            },
            {
                "service": 0x22,
                "request_payload": "22f1a0",
                "response_payload": "62f1a0010203",
                "response_kind": "positive",
                "capture_names": ["long"],
            },
        ],
    }])
    assert result[0]["value_lengths"] == [2, 3]
    assert result[0]["data_pattern"] == "Variable-length data"
    assert result[0]["variable_byte_offsets"] == []



def test_operation_did_response_variation_distinguishes_repeated_stable_data():
    from freerov3r.research_tab import summarize_operation_did_response_variation

    result = summarize_operation_did_response_variation([{
        "operation": "Read stable identifier",
        "transactions": [{
            "service": 0x22,
            "request_payload": "22f1a1",
            "response_payload": "62f1a1deadbeef",
            "response_kind": "positive",
            "capture_names": ["capture 1", "capture 2"],
            "count": 2,
        }],
    }])
    assert result[0]["distinct_value_count"] == 1
    assert result[0]["data_pattern"] == "Same data in all observed responses"
    assert result[0]["variable_byte_offsets"] == []



def test_research_tab_receiver_health_panel_displays_adapter_diagnostics(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from freerov3r.research_tab import ResearchTab

    app = QApplication.instance() or QApplication([])
    tab = ResearchTab()
    tab.set_receiver_diagnostics({
        "connected": True,
        "port": "COM7",
        "mode": "receive-only",
        "frames_received": 125,
        "invalid_lines": 2,
        "last_frame_age_seconds": 0.4,
        "alert_count": 1,
        "firmware_error_count": 0,
        "last_status": "MODE,LISTEN_ONLY",
    })

    assert "connected" in tab.receiver_connection_label.text()
    assert "COM7" in tab.receiver_connection_label.text()
    assert "125" in tab.receiver_frame_label.text()
    assert "2" in tab.receiver_frame_label.text()
    assert "0.4s ago" in tab.receiver_activity_label.text()
    assert "1 / 0" in tab.receiver_alert_label.text()
    assert "MODE,LISTEN_ONLY" in tab.receiver_status_label.text()
    tab.set_receiver_diagnostics({
        "connected": False,
        "port": "COM7",
        "mode": "receive-only",
        "last_error": "Port access denied",
    })
    assert "ERROR: Port access denied" in tab.receiver_status_label.text()
    assert "disconnected" in tab.receiver_connection_label.text()
    tab.refresh_timer.stop()
    tab.close()
    app.processEvents()



def test_research_tab_receiver_health_displays_explicit_receiver_state(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from freerov3r.research_tab import ResearchTab

    app = QApplication.instance() or QApplication([])
    tab = ResearchTab()
    tab.set_receiver_diagnostics({
        "connected": True,
        "receiver_state": "connected/silent",
        "port": "COM7",
        "mode": "receive-only",
        "frames_received": 0,
    })
    assert "connected/silent" in tab.receiver_connection_label.text()
    tab.set_receiver_diagnostics({
        "connected": True,
        "receiver_state": "receiving",
        "port": "COM7",
        "mode": "receive-only",
        "frames_received": 12,
    })
    assert "receiving" in tab.receiver_connection_label.text()
    tab.refresh_timer.stop()
    tab.close()
    app.processEvents()


def test_capture_retention_reports_pending_and_buffer_overflow(monkeypatch):
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from freerov3r.models import CanFrame
    from freerov3r.research_tab import ResearchTab

    app = QApplication.instance() or QApplication([])
    tab = ResearchTab()
    tab.refresh_timer.stop()
    tab.recording = True
    tab._recording_started_monotonic = time.monotonic()
    tab.MAX_PENDING_RECORDS = 2
    tab.MAX_CAPTURE_FRAMES = 1
    tab.refresh_table = lambda: None

    for can_id in (0x100, 0x101, 0x102, 0x103):
        tab.observe_frame(CanFrame(
            can_id, bytes([can_id & 0xFF]), channel="HS-CAN",
            timestamp=time.monotonic(),
            timestamp_clock_domain="host_monotonic",
            timestamp_source="esp32_serial_receive",
            device_timestamp_us=can_id * 1000,
            device_timestamp_clock_domain="device_uptime",
        ))

    assert tab.total_recorded_frames == 4
    assert len(tab._pending_records) == 2
    assert tab.dropped_pending_frames == 2
    assert tab.dropped_recorded_frames == 2

    tab._flush_pending_frames()

    assert len(tab.frames) == 1
    assert tab.frames[0]["arbitration_id"] == 0x103
    assert tab.dropped_recorded_frames == 3
    assert tab.dropped_pending_frames == 2
    tab._update_summary()
    summary = tab.summary.toPlainText()
    assert "Recorded frames observed: 4" in summary
    assert "Recorded frames retained: 1" in summary
    assert "Recorded frames dropped: 3" in summary
    assert "pending overflow: 2" in summary
    assert tab.frames[0]["timestamp_clock_domain"] == "host_monotonic"
    assert tab.frames[0]["timestamp_source"] == "esp32_serial_receive"
    assert tab.frames[0]["device_timestamp_clock_domain"] == "device_uptime"
    tab.close()
    app.processEvents()


def test_load_capture_file_preserves_timestamp_provenance(tmp_path):
    import json
    from freerov3r.research_tab import load_capture_file

    path = tmp_path / "provenance.json"
    path.write_text(json.dumps({
        "frames": [{
            "timestamp": 12.5,
            "timestamp_clock_domain": "host_monotonic",
            "timestamp_source": "python_can_receive",
            "source_timestamp": 1700000000.25,
            "source_timestamp_clock_domain": "unix_epoch",
            "device_timestamp_us": 123456,
            "device_timestamp_clock_domain": "device_uptime",
            "arbitration_id": 0x123,
            "extended": False,
            "data": "0102",
            "channel": "vcan0",
        }]
    }), encoding="utf-8")

    _, frames = load_capture_file(path)
    assert len(frames) == 1
    frame = frames[0]
    assert frame["timestamp_clock_domain"] == "host_monotonic"
    assert frame["timestamp_source"] == "python_can_receive"
    assert frame["source_timestamp"] == 1700000000.25
    assert frame["source_timestamp_clock_domain"] == "unix_epoch"
    assert frame["device_timestamp_us"] == 123456
    assert frame["device_timestamp_clock_domain"] == "device_uptime"




def test_load_jsonl_reports_malformed_and_truncated_records(tmp_path):
    path = tmp_path / "damaged.jsonl"
    path.write_text(
        '{"record_type":"metadata","metadata":{"session_name":"recovered"}}\n'
        '{"timestamp":1.0,"arbitration_id":291,"data":"0102"}\n'
        '{"timestamp":2.0,"arbitration_id":292,"data":"not-hex"}\n'
        '{"timestamp":3.0,"arbitration_id":',
        encoding="utf-8",
    )

    metadata, frames = load_capture_file(path)

    assert metadata["session_name"] == "recovered"
    assert len(frames) == 1
    assert frames[0]["arbitration_id"] == 291
    assert metadata["import_error_counts"] == {
        "invalid_records": 1,
        "malformed_lines": 1,
        "possible_truncated_final_line": True,
    }
    assert any("invalid frame" in warning for warning in metadata["import_warnings"])
    assert any("truncated" in warning for warning in metadata["import_warnings"])


def test_load_json_capture_reports_invalid_frame_records(tmp_path):
    import json

    path = tmp_path / "damaged.json"
    path.write_text(json.dumps({
        "format": "freerov3r-research-v1",
        "metadata": {"session_name": "partial recovery"},
        "frames": [
            {"timestamp": 1.0, "arbitration_id": 291, "data": "0102"},
            {"timestamp": 2.0, "arbitration_id": 292, "data": "not-hex"},
        ],
    }), encoding="utf-8")

    metadata, frames = load_capture_file(path)

    assert len(frames) == 1
    assert metadata["session_name"] == "partial recovery"
    assert metadata["import_error_counts"]["invalid_records"] == 1
    assert metadata["import_error_counts"]["malformed_lines"] == 0
    assert metadata["import_error_counts"]["possible_truncated_final_line"] is False


def test_load_json_capture_rejects_invalid_archive_structure(tmp_path):
    import json
    import pytest

    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({
        "format": "freerov3r-research-v1",
        "metadata": [],
        "frames": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata"):
        load_capture_file(path)



def test_format_import_warnings_includes_filename_and_each_warning():
    from freerov3r.research_tab import format_import_warnings

    report = format_import_warnings({
        "import_warnings": [
            "2 invalid frame record(s) were skipped",
            "The final non-empty JSONL line may be truncated",
        ],
    }, "/captures/damaged.jsonl")

    assert "damaged.jsonl" in report
    assert "2 invalid frame record(s) were skipped" in report
    assert "final non-empty JSONL line may be truncated" in report


def test_format_import_warnings_is_empty_for_clean_import():
    from freerov3r.research_tab import format_import_warnings

    assert format_import_warnings({}, "clean.json") == ""





def test_load_jsonl_streams_lines_without_reading_entire_file(tmp_path, monkeypatch):
    from pathlib import Path
    from freerov3r.research_tab import load_capture_file

    path = tmp_path / "streamed.jsonl"
    path.write_text(
        '{"record_type":"metadata","metadata":{"session_name":"streamed"}}\n'
        '{"timestamp":1.0,"arbitration_id":291,"data":"0102"}\n'
        '{"timestamp":2.0,"arbitration_id":292,"data":',
        encoding="utf-8",
    )

    def reject_read_text(self, *args, **kwargs):
        raise AssertionError("JSONL import must not read the entire file")

    monkeypatch.setattr(Path, "read_text", reject_read_text)
    metadata, frames = load_capture_file(path)

    assert metadata["session_name"] == "streamed"
    assert len(frames) == 1
    assert metadata["import_error_counts"]["malformed_lines"] == 1
    assert metadata["import_error_counts"]["possible_truncated_final_line"] is True


def test_load_jsonl_does_not_flag_nonfinal_malformed_line_as_truncated(tmp_path):
    from freerov3r.research_tab import load_capture_file

    path = tmp_path / "middle-damage.jsonl"
    path.write_text(
        '{"timestamp":1.0,"arbitration_id":291,"data":"0102"}\n'
        '{broken json}\n'
        '{"timestamp":2.0,"arbitration_id":292,"data":"0304"}\n',
        encoding="utf-8",
    )

    metadata, frames = load_capture_file(path)

    assert len(frames) == 2
    assert metadata["import_error_counts"]["malformed_lines"] == 1
    assert metadata["import_error_counts"]["possible_truncated_final_line"] is False


def test_load_streaming_capture_verifies_integrity(tmp_path):
    from freerov3r.capture_storage import StreamingCaptureWriter

    path = tmp_path / "complete.jsonl"
    writer = StreamingCaptureWriter(path)
    writer.start({"session_name": "verified"})
    writer.append_frame({"timestamp": 1.0, "arbitration_id": 291, "data": "0102"})
    writer.append_frame({"timestamp": 2.0, "arbitration_id": 292, "data": "AABB"})
    writer.finish({"notes": "test"})

    metadata, frames = load_capture_file(path)

    assert metadata["session_name"] == "verified"
    assert metadata["notes"] == "test"
    assert metadata["streaming_capture"]["status"] == "complete"
    assert metadata["streaming_capture"]["frame_count"] == 2
    assert len(frames) == 2
    assert "import_warnings" not in metadata


def test_load_interrupted_streaming_capture_recovers_frames_with_warning(tmp_path):
    from freerov3r.capture_storage import StreamingCaptureWriter

    path = tmp_path / "interrupted.jsonl"
    writer = StreamingCaptureWriter(path)
    writer.start({"session_name": "interrupted"})
    writer.append_frame({"timestamp": 1.0, "arbitration_id": 291, "data": "0102"})
    writer.close_incomplete()

    metadata, frames = load_capture_file(path)

    assert len(frames) == 1
    assert metadata["streaming_capture"]["status"] == "recording"
    assert any("not cleanly finalized" in warning for warning in metadata["import_warnings"])


def test_load_streaming_capture_detects_modified_frame(tmp_path):
    import json
    from freerov3r.capture_storage import StreamingCaptureWriter

    path = tmp_path / "modified.jsonl"
    writer = StreamingCaptureWriter(path)
    writer.start({"session_name": "modified"})
    writer.append_frame({"timestamp": 1.0, "arbitration_id": 291, "data": "0102"})
    writer.finish()

    lines = path.read_text(encoding="utf-8").splitlines()
    frame = json.loads(lines[1])
    frame["data"] = "FFFF"
    lines[1] = json.dumps(frame, separators=(",", ":"), sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    metadata, frames = load_capture_file(path)

    assert len(frames) == 1
    assert frames[0]["data"] == "ffff"
    assert any("integrity check failed" in warning for warning in metadata["import_warnings"])
