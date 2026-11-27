from freerov3r.diagnostics.cross_bus_signal_correlation import (
    analyze_cross_bus_signal_correlation,
)


def _record(timestamp, channel, can_id, payload, *, clock="host_monotonic", dlc=None, **extra):
    record = {
        "timestamp": timestamp,
        "timestamp_clock_domain": clock,
        "channel": channel,
        "arbitration_id": can_id,
        "extended": False,
        "data": bytes(payload).hex(),
    }
    if dlc is not None:
        record["dlc"] = dlc
    record.update(extra)
    return record


def _paired_capture(transform, *, lag=0.02, bit_only=False):
    records = []
    values = [0x10, 0x22, 0x35, 0x41, 0x58, 0x63, 0x79]
    for index, value in enumerate(values):
        timestamp = 0.2 + index * 0.35
        payload_a = bytes([value, 0x00])
        payload_b = bytes([transform(value), 0x00])
        records.append(_record(timestamp, "HS-CAN", 0x120, payload_a))
        records.append(_record(timestamp + lag, "MS-CAN", 0x321, payload_b))
    return records


def _analyze(records):
    return analyze_cross_bus_signal_correlation(
        records, max_lag_seconds=0.1, event_tolerance_seconds=0.01,
        minimum_transitions=3, minimum_agreement=0.8,
    )


def test_finds_repeated_exact_byte_relationship_and_lag_direction():
    result = _analyze(_paired_capture(lambda value: value))
    item = next(
        item for item in result["candidates"]
        if item["signal_type"] == "byte" and item["byte_a"] == 0 and item["byte_b"] == 0
    )
    assert item["match_type"] == "exact byte"
    assert item["transition_count"] >= 3
    assert item["agreement"] >= 0.8
    assert item["lag_seconds"] == 0.02
    assert item["lag_interpretation"] == "MS-CAN follows HS-CAN"
    assert item["evidence_level"] == "candidate"


def test_finds_inverted_byte_and_xor_mask_relationships():
    inverted = _analyze(_paired_capture(lambda value: value ^ 0xFF))
    item = next(
        item for item in inverted["candidates"]
        if item["signal_type"] == "byte" and item["byte_a"] == 0 and item["byte_b"] == 0
    )
    assert item["match_type"] == "inverted byte"
    masked = _analyze(_paired_capture(lambda value: value ^ 0x04))
    item = next(
        item for item in masked["candidates"]
        if item["signal_type"] == "byte" and item["byte_a"] == 0 and item["byte_b"] == 0
    )
    assert item["match_type"] == "XOR mask 0x04"


def test_finds_same_and_inverted_bit_transitions():
    records = []
    states = [0, 1, 0, 1, 1, 0, 1]
    for index, state in enumerate(states):
        timestamp = 0.1 + index * 0.4
        records.append(_record(timestamp, "A", 0x100, [state]))
        records.append(_record(timestamp + 0.01, "B", 0x200, [1 - state]))
    result = _analyze(records)
    assert any(
        item["signal_type"] == "bit" and item["bit_a"] == 0
        and item["bit_b"] == 0 and item["match_type"] == "inverted transition"
        for item in result["candidates"]
    )


def test_static_payload_does_not_create_transition_candidates():
    records = []
    for index in range(30):
        timestamp = index * 0.05
        records.append(_record(timestamp, "A", 0x100, [0x55]))
        records.append(_record(timestamp + 0.005, "B", 0x200, [0x55]))
    result = _analyze(records)
    assert result["candidates"] == []


def test_excludes_independent_clocks_and_rejects_bad_dlc_and_remote_frames():
    records = _paired_capture(lambda value: value)
    for record in records:
        record["timestamp_clock_domain"] = "device_uptime"
    result = _analyze(records)
    assert result["excluded_non_shared_clock_count"] == len(records)
    assert result["candidates"] == []

    bad = _record(1.0, "A", 0x100, [1, 2], dlc=1)
    remote = _record(1.1, "B", 0x200, [1], rtr=True)
    result = _analyze([bad, remote])
    assert result["invalid_frame_count"] == 2


def test_requires_repeated_transitions_and_valid_parameters():
    import pytest
    result = _analyze([
        _record(0.1, "A", 0x100, [0]),
        _record(0.2, "B", 0x200, [0]),
    ])
    assert result["candidates"] == []
    with pytest.raises(ValueError):
        analyze_cross_bus_signal_correlation([], event_tolerance_seconds=0)
    with pytest.raises(ValueError):
        analyze_cross_bus_signal_correlation([], minimum_agreement=1.5)



def test_rejects_low_transition_coverage_even_when_matched_events_agree():
    records = []
    values = [0x10, 0x22, 0x35, 0x41, 0x58, 0x63, 0x79]
    for index, value in enumerate(values):
        timestamp = 0.2 + index * 0.35
        other = value if index < 4 else values[3]
        records.append(_record(timestamp, "HS-CAN", 0x120, [value]))
        records.append(_record(timestamp + 0.02, "MS-CAN", 0x321, [other]))
    result = analyze_cross_bus_signal_correlation(
        records, max_lag_seconds=0.1, event_tolerance_seconds=0.01,
        minimum_transitions=3, minimum_agreement=0.8,
        minimum_transition_coverage=0.8,
    )
    assert result["candidates"] == []
