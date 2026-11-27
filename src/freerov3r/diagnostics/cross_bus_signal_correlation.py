"""Conservative signal-level correlation for CAN traffic on separate buses.

The analyzer compares repeated payload transitions only on the shared host
monotonic receive timeline. Results are candidates, never signal definitions,
ECU identities, or proof of causality.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict


def _parse_frame(record):
    if not isinstance(record, dict):
        return None
    if record.get("timestamp_clock_domain", record.get("timestamp_clock")) != "host_monotonic":
        return "clock"
    try:
        remote = record.get("rtr", record.get("remote", False))
        if isinstance(remote, str):
            remote = remote.strip().lower() in ("1", "true", "yes", "rtr", "remote")
        if remote:
            return None
        timestamp = record.get("timestamp")
        if isinstance(timestamp, bool):
            return None
        timestamp = float(timestamp)
        can_id = int(record["arbitration_id"])
        extended_value = record.get("extended", False)
        extended = (
            extended_value.strip().lower() in ("1", "true", "yes", "ext", "extended")
            if isinstance(extended_value, str) else bool(extended_value)
        )
        raw = record.get("data", "")
        payload = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes.fromhex(str(raw).replace(" ", ""))
        if not math.isfinite(timestamp) or timestamp < 0 or can_id < 0 or can_id > 0x1FFFFFFF:
            return None
        if len(payload) > 64:
            return None
        if record.get("dlc") is not None and int(record["dlc"]) != len(payload):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    channel = record.get("channel")
    if channel is None or not str(channel).strip():
        return None
    return timestamp, str(channel), can_id, extended, payload


def _series_events(frames, max_bytes):
    grouped = defaultdict(list)
    for timestamp, channel, can_id, extended, payload in frames:
        if not payload:
            continue
        grouped[(channel, can_id, extended)].append((timestamp, payload[:max_bytes]))

    series = {}
    for key, samples in grouped.items():
        samples.sort(key=lambda item: item[0])
        byte_events = defaultdict(list)
        bit_events = defaultdict(list)
        previous = None
        for timestamp, payload in samples:
            if previous is not None:
                previous_time, previous_payload = previous
                for index in range(min(len(payload), len(previous_payload))):
                    old, new = previous_payload[index], payload[index]
                    if old == new:
                        continue
                    byte_events[index].append((timestamp, old, new))
                    changed = old ^ new
                    for bit in range(8):
                        if changed & (1 << bit):
                            old_bit = (old >> bit) & 1
                            new_bit = (new >> bit) & 1
                            bit_events[(index, bit)].append((timestamp, old_bit, new_bit))
            previous = (timestamp, payload)
        series[key] = {
            "bytes": {index: events for index, events in byte_events.items()},
            "bits": {position: events for position, events in bit_events.items()},
            "frame_count": len(samples),
        }
    return series


def _candidate_lags(events_a, events_b, max_lag, resolution, max_lags=6):
    histogram = Counter()
    # A bounded, evenly spaced sample keeps lag discovery practical on long captures.
    def sample(events, limit=40):
        if len(events) <= limit:
            return events
        last = len(events) - 1
        return [events[round(index * last / (limit - 1))] for index in range(limit)]

    sample_a = sample(events_a)
    sample_b = sample(events_b)
    for time_a, _, _ in sample_a:
        for time_b, _, _ in sample_b:
            delta = time_b - time_a
            if abs(delta) <= max_lag:
                histogram[round(delta / resolution)] += 1
    return [
        bucket * resolution
        for bucket, _ in histogram.most_common(max_lags)
    ]


def _match_events(events_a, events_b, lag, tolerance):
    pairs = []
    used = set()
    times_b = [event[0] for event in events_b]
    for event_a in events_a:
        expected = event_a[0] + lag
        start = bisect_left(times_b, expected - tolerance)
        end = bisect_right(times_b, expected + tolerance)
        best_index = None
        best_error = None
        for index in range(start, end):
            if index in used:
                continue
            error = abs(times_b[index] - expected)
            if best_error is None or error < best_error:
                best_index, best_error = index, error
        if best_index is not None:
            used.add(best_index)
            pairs.append((event_a, events_b[best_index]))
    return pairs


def _evaluate_pairs(pairs, bit_level):
    masks = Counter()
    for event_a, event_b in pairs:
        old_mask = event_a[1] ^ event_b[1]
        new_mask = event_a[2] ^ event_b[2]
        if old_mask == new_mask:
            masks[old_mask] += 1
    if not masks:
        return None
    mask, count = masks.most_common(1)[0]
    agreement = count / len(pairs) if pairs else 0.0
    if bit_level:
        match_type = "same transition" if mask == 0 else "inverted transition"
    elif mask == 0:
        match_type = "exact byte"
    elif mask == 0xFF:
        match_type = "inverted byte"
    else:
        match_type = f"XOR mask 0x{mask:02X}"
    return mask, count, agreement, match_type


def analyze_cross_bus_signal_correlation(
    records, *, max_lag_seconds=0.25, event_tolerance_seconds=0.01,
    minimum_transitions=3, minimum_agreement=0.8, minimum_transition_coverage=0.5,
    max_message_pairs=30,
    max_ids_per_channel=20, max_bytes=8, max_results=250,
):
    """Find repeated byte/bit transitions that align across different CAN buses.

    Message-ID pairs are bounded using the existing activity-correlation
    analysis. Byte relationships use a stable XOR mask across old/new values;
    bit relationships are same or inverted transitions at matching bit offsets.
    Transition coverage is matched transitions divided by the larger event stream,
    so one-sided or sparse matches are penalized. Positive lag means channel B
    follows channel A.
    """
    for name, value in (
        ("max_lag_seconds", max_lag_seconds),
        ("event_tolerance_seconds", event_tolerance_seconds),
        ("minimum_agreement", minimum_agreement),
        ("minimum_transition_coverage", minimum_transition_coverage),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if max_lag_seconds < 0 or event_tolerance_seconds <= 0:
        raise ValueError("Time limits must be non-negative and tolerance positive")
    if not 0 < minimum_agreement <= 1:
        raise ValueError("minimum_agreement must be in (0, 1]")
    if not 0 < minimum_transition_coverage <= 1:
        raise ValueError("minimum_transition_coverage must be in (0, 1]")
    if minimum_transitions < 2 or max_message_pairs < 1 or max_ids_per_channel < 1:
        raise ValueError("Count limits must be positive")
    if not 1 <= max_bytes <= 64 or max_results < 1:
        raise ValueError("Payload and result limits are out of range")

    records = list(records or ())
    parsed = []
    excluded_clock = invalid = 0
    for record in records:
        frame = _parse_frame(record)
        if frame == "clock":
            excluded_clock += 1
        elif frame is None:
            invalid += 1
        else:
            parsed.append(frame)

    channels = sorted({frame[1] for frame in parsed})
    result = {
        "status": "insufficient shared-timeline data",
        "channel_count": len(channels),
        "channels": channels,
        "valid_frame_count": len(parsed),
        "excluded_non_shared_clock_count": excluded_clock,
        "invalid_frame_count": invalid,
        "message_pair_count": 0,
        "candidate_count": 0,
        "candidates": [],
        "limits": {
            "maximum_lag_ms": max_lag_seconds * 1000.0,
            "event_tolerance_ms": event_tolerance_seconds * 1000.0,
            "minimum_transitions": minimum_transitions,
            "minimum_agreement": minimum_agreement,
            "minimum_transition_coverage": minimum_transition_coverage,
            "maximum_message_pairs": max_message_pairs,
            "maximum_ids_per_channel": max_ids_per_channel,
            "maximum_payload_bytes_analyzed": max_bytes,
        },
        "limitations": [
            "Only explicit host_monotonic timestamps are compared; unknown and independent device clocks are excluded.",
            "Host receive timestamps include transport and operating-system scheduling effects.",
            "Candidate message pairs are bounded by CAN-ID activity correlation; signals outside those pairs are not searched.",
            "Only the first configured payload bytes are analyzed. Byte scaling, offsets, endianness and multi-byte signals are not inferred.",
            "A stable XOR relationship across transitions is a pattern, not proof that two fields represent the same physical quantity.",
            "Repeated captures and controlled vehicle experiments are required before promoting any candidate.",
        ],
    }
    if len(channels) < 2 or not parsed:
        return result

    from freerov3r.diagnostics.cross_bus_correlation import analyze_cross_bus_correlation
    activity = analyze_cross_bus_correlation(
        records, max_ids_per_channel=max_ids_per_channel,
        max_results=max_message_pairs,
    )
    message_pairs = activity.get("candidates", [])[:max_message_pairs]
    result["message_pair_count"] = len(message_pairs)
    if not message_pairs:
        result["status"] = "no candidate CAN-ID pairs to inspect"
        return result

    series = _series_events(parsed, max_bytes)
    candidates = []
    resolution = max(event_tolerance_seconds, 0.001)

    def inspect_signal(events_a, events_b, base, bit_level=False):
        if len(events_a) < minimum_transitions or len(events_b) < minimum_transitions:
            return
        lags = _candidate_lags(
            events_a, events_b, max_lag_seconds, resolution
        )
        best = None
        for lag in lags:
            pairs = _match_events(
                events_a, events_b, lag, event_tolerance_seconds
            )
            if len(pairs) < minimum_transitions:
                continue
            evaluated = _evaluate_pairs(pairs, bit_level)
            if evaluated is None:
                continue
            mask, count, agreement, match_type = evaluated
            score = (count, agreement, -abs(lag))
            if best is None or score > best[0]:
                best = (score, lag, count, agreement, match_type, len(pairs), mask)
        if best is None:
            return
        _, lag, count, agreement, match_type, paired_count, mask = best
        coverage = count / max(1, max(len(events_a), len(events_b)))
        if (
            count < minimum_transitions or agreement < minimum_agreement
            or coverage < minimum_transition_coverage
        ):
            return
        item = dict(base)
        item.update({
            "match_type": match_type,
            "xor_mask": mask,
            "transition_count": count,
            "paired_transition_count": paired_count,
            "agreement": agreement,
            "transition_coverage": coverage,
            "lag_seconds": lag,
            "lag_interpretation": (
                f"{item['channel_b']} follows {item['channel_a']}" if lag > 0
                else f"{item['channel_a']} follows {item['channel_b']}" if lag < 0
                else "transitions occur within the same time window"
            ),
            "evidence_level": "candidate",
        })
        candidates.append(item)

    for pair in message_pairs:
        key_a = (pair["channel_a"], pair["can_id_a"], pair["format_a"] == "extended")
        key_b = (pair["channel_b"], pair["can_id_b"], pair["format_b"] == "extended")
        data_a, data_b = series.get(key_a), series.get(key_b)
        if not data_a or not data_b:
            continue
        for index_a, events_a in data_a["bytes"].items():
            for index_b, events_b in data_b["bytes"].items():
                inspect_signal(events_a, events_b, {
                    "signal_type": "byte",
                    "channel_a": key_a[0], "can_id_a": key_a[1],
                    "format_a": "extended" if key_a[2] else "standard",
                    "byte_a": index_a,
                    "channel_b": key_b[0], "can_id_b": key_b[1],
                    "format_b": "extended" if key_b[2] else "standard",
                    "byte_b": index_b,
                    "frames_a": data_a["frame_count"],
                    "frames_b": data_b["frame_count"],
                })
        for (index_a, bit_a), events_a in data_a["bits"].items():
            for (index_b, bit_b), events_b in data_b["bits"].items():
                # Compare like-numbered bit positions across byte offsets. This
                # keeps the search bounded while still detecting relocated bits.
                if bit_a != bit_b:
                    continue
                inspect_signal(events_a, events_b, {
                    "signal_type": "bit",
                    "channel_a": key_a[0], "can_id_a": key_a[1],
                    "format_a": "extended" if key_a[2] else "standard",
                    "byte_a": index_a, "bit_a": bit_a,
                    "channel_b": key_b[0], "can_id_b": key_b[1],
                    "format_b": "extended" if key_b[2] else "standard",
                    "byte_b": index_b, "bit_b": bit_b,
                    "frames_a": data_a["frame_count"],
                    "frames_b": data_b["frame_count"],
                }, bit_level=True)

    candidates.sort(
        key=lambda item: (
            -item["transition_count"], -item["agreement"],
            abs(item["lag_seconds"]), item["can_id_a"], item["can_id_b"],
            item["signal_type"], item["byte_a"], item.get("bit_a", -1),
            item["byte_b"], item.get("bit_b", -1),
        )
    )
    result["candidates"] = candidates[:max_results]
    result["candidate_count"] = len(candidates)
    result["status"] = (
        "candidate signal relationships found" if candidates
        else "no repeated signal transitions above threshold"
    )
    return result
