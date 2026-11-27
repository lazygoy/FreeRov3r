"""Validate cross-bus CAN signal candidates across independent captures.

Each recording is analyzed on its own host-monotonic timeline. Timestamps from
separate files are never compared directly. Repeated structural relationships
are aggregated as candidates, not promoted to verified signal definitions.
"""
from __future__ import annotations

import math
from statistics import median

from freerov3r.diagnostics.cross_bus_signal_correlation import (
    analyze_cross_bus_signal_correlation,
)


def _signature(item):
    return (
        item.get("signal_type"),
        item.get("channel_a"), item.get("can_id_a"), item.get("format_a"),
        item.get("byte_a"), item.get("bit_a"),
        item.get("channel_b"), item.get("can_id_b"), item.get("format_b"),
        item.get("byte_b"), item.get("bit_b"),
        item.get("match_type"), item.get("xor_mask"),
    )


def _valid_capture(item, index):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or f"Capture {index + 1}").strip()
    frames = item.get("frames")
    if not isinstance(frames, (list, tuple)):
        return None
    return {"name": name or f"Capture {index + 1}", "frames": frames}


def validate_cross_capture_signals(
    captures, *, minimum_captures=2, minimum_capture_agreement=0.75,
    maximum_lag_spread_seconds=0.03, per_capture_options=None,
):
    """Aggregate matching signal candidates found independently in captures.

    A candidate must recur in enough captures with the same CAN-ID/field pair,
    relationship type, and XOR mask. Lag direction must remain consistent and
    the median absolute lag spread must stay within the configured limit.
    """
    if isinstance(minimum_captures, bool) or not isinstance(minimum_captures, int) or minimum_captures < 2:
        raise ValueError("minimum_captures must be an integer of at least 2")
    if isinstance(minimum_capture_agreement, bool) or not isinstance(minimum_capture_agreement, (int, float)) or not math.isfinite(minimum_capture_agreement):
        raise ValueError("minimum_capture_agreement must be finite")
    if not 0 < minimum_capture_agreement <= 1:
        raise ValueError("minimum_capture_agreement must be in (0, 1]")
    if isinstance(maximum_lag_spread_seconds, bool) or not isinstance(maximum_lag_spread_seconds, (int, float)) or not math.isfinite(maximum_lag_spread_seconds) or maximum_lag_spread_seconds < 0:
        raise ValueError("maximum_lag_spread_seconds must be finite and non-negative")

    valid = []
    for index, item in enumerate(captures or ()):
        capture = _valid_capture(item, index)
        if capture is not None:
            valid.append(capture)

    result = {
        "status": "insufficient independent captures",
        "capture_count": len(valid),
        "analyzed_capture_count": 0,
        "minimum_captures": minimum_captures,
        "minimum_capture_agreement": float(minimum_capture_agreement),
        "maximum_lag_spread_ms": float(maximum_lag_spread_seconds) * 1000.0,
        "candidate_count": 0,
        "candidates": [],
        "captures": [],
        "limitations": [
            "Each recording is analyzed independently; monotonic timestamps from different files are never compared directly.",
            "Only relationships found by the within-capture shared host_monotonic analyzer are considered.",
            "Capture files must preserve the same bus/channel labels and CAN identifiers for direct structural matching.",
            "A stable relationship across recordings is repeatable evidence, not proof of signal meaning, physical ECU identity, or causality.",
            "Transport latency and host scheduling can change apparent cross-bus lag between recordings.",
            "No candidate is promoted automatically to verified or supported status.",
        ],
    }
    if len(valid) < minimum_captures:
        return result

    options = dict(per_capture_options or {})
    by_signature = {}
    for capture in valid:
        report = analyze_cross_bus_signal_correlation(capture["frames"], **options)
        result["analyzed_capture_count"] += 1
        result["captures"].append({
            "name": capture["name"],
            "frame_count": report["valid_frame_count"],
            "candidate_count": report["candidate_count"],
            "message_pair_count": report["message_pair_count"],
            "excluded_non_shared_clock_count": report["excluded_non_shared_clock_count"],
            "status": report["status"],
        })
        seen = set()
        for candidate in report["candidates"]:
            signature = _signature(candidate)
            if signature in seen:
                continue
            seen.add(signature)
            by_signature.setdefault(signature, []).append({
                "capture_name": capture["name"],
                "transition_count": candidate["transition_count"],
                "agreement": candidate["agreement"],
                "transition_coverage": candidate["transition_coverage"],
                "lag_seconds": candidate["lag_seconds"],
                "frames_a": candidate["frames_a"],
                "frames_b": candidate["frames_b"],
            })

    validated = []
    for signature, observations in by_signature.items():
        if len(observations) < minimum_captures:
            continue
        capture_agreement = len(observations) / max(1, result["analyzed_capture_count"])
        if capture_agreement < minimum_capture_agreement:
            continue
        lags = [item["lag_seconds"] for item in observations]
        directions = {0 if abs(lag) < 1e-9 else (1 if lag > 0 else -1) for lag in lags}
        if len(directions) != 1:
            continue
        median_lag = median(lags)
        lag_spread = max(abs(lag - median_lag) for lag in lags)
        if lag_spread > maximum_lag_spread_seconds:
            continue
        (
            signal_type, channel_a, can_id_a, format_a, byte_a, bit_a,
            channel_b, can_id_b, format_b, byte_b, bit_b, match_type, xor_mask,
        ) = signature
        validated.append({
            "signal_type": signal_type,
            "channel_a": channel_a, "can_id_a": can_id_a, "format_a": format_a,
            "byte_a": byte_a, "bit_a": bit_a,
            "channel_b": channel_b, "can_id_b": can_id_b, "format_b": format_b,
            "byte_b": byte_b, "bit_b": bit_b,
            "match_type": match_type, "xor_mask": xor_mask,
            "capture_count": len(observations),
            "capture_agreement": capture_agreement,
            "total_transitions": sum(item["transition_count"] for item in observations),
            "median_transition_agreement": median(item["agreement"] for item in observations),
            "median_transition_coverage": median(item["transition_coverage"] for item in observations),
            "median_lag_seconds": median_lag,
            "lag_spread_seconds": lag_spread,
            "lag_direction_consistent": True,
            "capture_evidence": observations,
            "evidence_level": "repeatable_candidate",
        })

    validated.sort(key=lambda item: (
        -item["capture_count"], -item["capture_agreement"],
        -item["total_transitions"], item["lag_spread_seconds"],
        item["can_id_a"], item["can_id_b"],
    ))
    result["candidates"] = validated
    result["candidate_count"] = len(validated)
    result["status"] = (
        "repeatable cross-capture candidates found" if validated
        else "no candidates repeated consistently across captures"
    )
    return result
