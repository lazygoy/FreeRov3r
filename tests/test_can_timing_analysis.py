import pytest

from freerov3r.diagnostics.can_timing_analysis import analyze_message_periodicity


def _frame(can_id, timestamp, channel="HS-CAN", extended=False):
    return {
        "arbitration_id": can_id,
        "timestamp": timestamp,
        "channel": channel,
        "extended": extended,
        "data": "010203",
    }


def test_periodicity_reports_median_and_jitter_per_can_node():
    report = analyze_message_periodicity([
        _frame(0x321, 1.00),
        _frame(0x321, 1.10),
        _frame(0x321, 1.21),
        _frame(0x321, 1.30),
    ])
    assert report["transmission_performed"] is False
    node = report["nodes"][0]
    assert node["frame_count"] == 4
    assert node["interval_count"] == 3
    assert node["median_interval_s"] == pytest.approx(0.1)
    assert node["min_interval_s"] == pytest.approx(0.09)
    assert node["max_interval_s"] == pytest.approx(0.11)
    assert node["p95_absolute_deviation_s"] is not None


def test_periodicity_keeps_channel_and_frame_format_separate():
    report = analyze_message_periodicity([
        _frame(0x123, 1.0, "HS-CAN", False),
        _frame(0x123, 1.1, "HS-CAN", False),
        _frame(0x123, 1.0, "MS-CAN", True),
        _frame(0x123, 1.2, "MS-CAN", True),
    ])
    assert len(report["nodes"]) == 2
    assert {(item["channel"], item["extended"]) for item in report["nodes"]} == {
        ("HS-CAN", False), ("MS-CAN", True)
    }


def test_periodicity_counts_duplicate_and_non_monotonic_timestamps():
    report = analyze_message_periodicity([
        _frame(0x100, 1.0),
        _frame(0x100, 1.0),
        _frame(0x100, 0.9),
        _frame(0x100, 1.1),
    ])
    node = report["nodes"][0]
    assert node["duplicate_timestamp_count"] == 1
    assert node["non_monotonic_timestamp_count"] == 1
    assert node["interval_count"] == 1
    assert node["median_interval_s"] == pytest.approx(0.2)


def test_periodicity_ignores_invalid_timestamps_and_payloads():
    report = analyze_message_periodicity([
        _frame(0x100, 1.0),
        {**_frame(0x100, 2.0), "timestamp": float("nan")},
        {**_frame(0x100, 3.0), "data": "not-hex"},
        {"arbitration_id": 0x100, "timestamp": 4.0},
    ])
    assert report["invalid_record_count"] == 3
    assert report["node_count"] == 1
    assert report["nodes"][0]["frame_count"] == 1
    assert report["nodes"][0]["median_interval_s"] is None


def test_module_discovery_embeds_timing_without_changing_identity_evidence():
    from freerov3r.diagnostics.module_discovery import discover_modules

    report = discover_modules([
        _frame(0x321, 1.0),
        _frame(0x321, 1.1),
        _frame(0x321, 1.2),
    ])
    node = report["nodes"][0]
    assert node["timing"]["median_interval_s"] == 0.1
    assert node["evidence_level"] == "Observed"
    assert report["transmission_performed"] is False
