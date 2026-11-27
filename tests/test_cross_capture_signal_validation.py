from freerov3r.diagnostics.cross_capture_signal_validation import (
    validate_cross_capture_signals,
)


def _capture(name, *, lag=0.02, transform=lambda value: value, start=0.0, clock="host_monotonic"):
    values = [0x10, 0x22, 0x35, 0x41, 0x58, 0x63, 0x79]
    frames = []
    for index, value in enumerate(values):
        timestamp = start + 0.2 + index * 0.35
        frames.append({
            "timestamp": timestamp,
            "timestamp_clock_domain": clock,
            "channel": "HS-CAN",
            "arbitration_id": 0x120,
            "extended": False,
            "data": bytes([value]).hex(),
        })
        frames.append({
            "timestamp": timestamp + lag,
            "timestamp_clock_domain": clock,
            "channel": "MS-CAN",
            "arbitration_id": 0x321,
            "extended": False,
            "data": bytes([transform(value)]).hex(),
        })
    return {"name": name, "frames": frames}


def test_repeats_same_relationship_across_independent_capture_timelines():
    result = validate_cross_capture_signals([
        _capture("baseline", start=0.0),
        _capture("repeat", start=100.0, lag=0.02),
    ])
    assert result["candidate_count"] >= 1
    item = next(
        item for item in result["candidates"]
        if item["signal_type"] == "byte" and item["byte_a"] == 0 and item["byte_b"] == 0
    )
    assert item["capture_count"] == 2
    assert item["capture_agreement"] == 1.0
    assert item["evidence_level"] == "repeatable_candidate"
    assert item["lag_direction_consistent"] is True


def test_rejects_relationship_that_does_not_repeat_in_second_capture():
    result = validate_cross_capture_signals([
        _capture("first"),
        _capture("second", transform=lambda value: value ^ 0xFF),
    ])
    assert result["candidate_count"] == 0


def test_rejects_inconsistent_lag_direction_and_excessive_lag_spread():
    opposite = validate_cross_capture_signals([
        _capture("positive", lag=0.02),
        _capture("negative", lag=-0.02),
    ])
    assert opposite["candidate_count"] == 0

    spread = validate_cross_capture_signals([
        _capture("first", lag=0.01),
        _capture("second", lag=0.09),
    ], maximum_lag_spread_seconds=0.02)
    assert spread["candidate_count"] == 0


def test_requires_shared_clock_domain_in_each_recording():
    result = validate_cross_capture_signals([
        _capture("first", clock="device_uptime"),
        _capture("second", clock="device_uptime"),
    ])
    assert result["analyzed_capture_count"] == 2
    assert result["candidate_count"] == 0
    assert all(
        item["excluded_non_shared_clock_count"] > 0
        for item in result["captures"]
    )


def test_reports_insufficient_captures_and_validates_options():
    import pytest
    result = validate_cross_capture_signals([_capture("only")])
    assert result["status"] == "insufficient independent captures"
    with pytest.raises(ValueError):
        validate_cross_capture_signals([], minimum_captures=1)
    with pytest.raises(ValueError):
        validate_cross_capture_signals([], maximum_lag_spread_seconds=-1)
