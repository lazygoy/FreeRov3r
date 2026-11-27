from freerov3r.diagnostics.cross_bus_correlation import analyze_cross_bus_correlation


def _record(timestamp, channel, can_id, *, clock="host_monotonic"):
    return {
        "timestamp": timestamp,
        "timestamp_clock_domain": clock,
        "channel": channel,
        "arbitration_id": can_id,
        "extended": False,
    }


def test_correlates_repeated_cross_bus_activity_and_reports_lag():
    records = []
    # Distinct repeated bursts, with MS-CAN following HS-CAN by 50 ms.
    for start in (0.2, 0.8, 1.4, 2.0, 2.6):
        for offset in (0.0, 0.01, 0.02, 0.03):
            records.append(_record(start + offset, "HS-CAN", 0x120))
            records.append(_record(start + offset + 0.05, "MS-CAN", 0x321))

    result = analyze_cross_bus_correlation(records)
    assert result["status"] == "candidate relationships found"
    candidate = result["candidates"][0]
    assert candidate["can_id_a"] == 0x120
    assert candidate["can_id_b"] == 0x321
    assert candidate["lag_seconds"] == 0.05
    assert candidate["evidence_level"] == "candidate"
    assert candidate["correlation"] >= 0.65


def test_excludes_independent_or_unknown_clock_domains():
    records = [
        _record(index * 0.1, "HS-CAN", 0x120, clock="device_uptime")
        for index in range(10)
    ] + [
        _record(index * 0.1, "MS-CAN", 0x321, clock="unknown")
        for index in range(10)
    ]
    result = analyze_cross_bus_correlation(records)
    assert result["valid_frame_count"] == 0
    assert result["excluded_non_shared_clock_count"] == 20
    assert result["candidates"] == []


def test_requires_two_channels_and_sufficient_capture_duration():
    result = analyze_cross_bus_correlation([
        _record(index * 0.001, "HS-CAN", 0x120) for index in range(30)
    ])
    assert result["channel_count"] == 1
    assert result["status"] == "insufficient shared-timeline data"


def test_rejects_invalid_analysis_parameters():
    import pytest
    with pytest.raises(ValueError):
        analyze_cross_bus_correlation([], bin_width_seconds=0)
    with pytest.raises(ValueError):
        analyze_cross_bus_correlation([], minimum_correlation=0)
