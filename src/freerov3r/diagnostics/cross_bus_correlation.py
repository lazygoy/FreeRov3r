"""Conservative cross-bus CAN activity correlation.

Only records explicitly timestamped in the shared host_monotonic clock domain
are compared. Results are temporal candidates, never ECU identity or causality.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict


def _pearson(left, right):
    count = len(left)
    if count < 2:
        return None
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    sum_left = sum(value * value for value in centered_left)
    sum_right = sum(value * value for value in centered_right)
    if sum_left <= 0 or sum_right <= 0:
        return None
    covariance = sum(a * b for a, b in zip(centered_left, centered_right))
    return covariance / math.sqrt(sum_left * sum_right)


def analyze_cross_bus_correlation(
    records, *, bin_width_seconds=0.01, max_lag_seconds=0.25,
    minimum_frames=4, minimum_correlation=0.65, max_ids_per_channel=40,
    max_results=100,
):
    """Find CAN ID activity patterns that correlate across distinct channels.

    A positive lag means channel B's activity follows channel A. The analysis
    bins frame counts on the shared host monotonic receive timeline. It does not
    infer physical causality, ECU identity, or true on-wire propagation delay.
    """
    for name, value in (
        ("bin_width_seconds", bin_width_seconds),
        ("max_lag_seconds", max_lag_seconds),
        ("minimum_correlation", minimum_correlation),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if bin_width_seconds <= 0 or max_lag_seconds < 0:
        raise ValueError("Time window values are out of range")
    if not 0 < minimum_correlation <= 1:
        raise ValueError("minimum_correlation must be in (0, 1]")
    if minimum_frames < 2 or max_ids_per_channel < 1 or max_results < 1:
        raise ValueError("Count limits must be positive")

    valid = []
    excluded_clock = 0
    invalid = 0
    for record in records or ():
        if not isinstance(record, dict):
            invalid += 1
            continue
        if record.get("timestamp_clock_domain", record.get("timestamp_clock")) != "host_monotonic":
            excluded_clock += 1
            continue
        channel = record.get("channel")
        if channel is None or not str(channel).strip():
            invalid += 1
            continue
        try:
            timestamp = float(record.get("timestamp"))
            can_id = int(record.get("arbitration_id"))
            extended = bool(record.get("extended", False))
            if not math.isfinite(timestamp) or timestamp < 0 or can_id < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            invalid += 1
            continue
        valid.append((timestamp, str(channel), can_id, extended))

    channels = sorted({item[1] for item in valid})
    result = {
        "status": "insufficient shared-timeline data",
        "channel_count": len(channels),
        "channels": channels,
        "valid_frame_count": len(valid),
        "excluded_non_shared_clock_count": excluded_clock,
        "invalid_frame_count": invalid,
        "bin_width_seconds": float(bin_width_seconds),
        "maximum_lag_seconds": float(max_lag_seconds),
        "minimum_correlation": float(minimum_correlation),
        "candidate_count": 0,
        "candidates": [],
        "limitations": [
            "Only explicit host_monotonic timestamps are compared; unknown or independent device clocks are excluded.",
            "Host receive timestamps include transport and operating-system scheduling effects.",
            "Correlation is temporal association, not proof of causality, ECU identity, or message meaning.",
            "Repeated captures and controlled experiments are needed before promoting a candidate to verified.",
        ],
    }
    if len(channels) < 2 or len(valid) < minimum_frames * 2:
        return result

    origin = min(item[0] for item in valid)
    last_bin = max(int((item[0] - origin) / bin_width_seconds) for item in valid)
    bin_count = last_bin + 1
    if bin_count < 20:
        result["status"] = "capture too short for correlation"
        return result

    grouped = defaultdict(lambda: defaultdict(Counter))
    for timestamp, channel, can_id, extended in valid:
        bin_index = int((timestamp - origin) / bin_width_seconds)
        key = (can_id, extended)
        grouped[channel][key][bin_index] += 1

    # Limit the pair search to the most frequently observed IDs on each bus.
    id_sets = {}
    for channel in channels:
        ranked = sorted(
            grouped[channel].items(),
            key=lambda item: (-sum(item[1].values()), item[0][0], item[0][1]),
        )
        id_sets[channel] = [
            (key, counts) for key, counts in ranked
            if sum(counts.values()) >= minimum_frames
        ][:max_ids_per_channel]

    max_lag_bins = int(max_lag_seconds / bin_width_seconds)
    candidates = []
    for channel_index, channel_a in enumerate(channels):
        for channel_b in channels[channel_index + 1:]:
            for (id_a, ext_a), counts_a in id_sets[channel_a]:
                vector_a = [counts_a.get(i, 0) for i in range(bin_count)]
                for (id_b, ext_b), counts_b in id_sets[channel_b]:
                    vector_b = [counts_b.get(i, 0) for i in range(bin_count)]
                    best = None
                    for lag in range(-max_lag_bins, max_lag_bins + 1):
                        if lag >= 0:
                            left = vector_a[:bin_count - lag] if lag else vector_a
                            right = vector_b[lag:] if lag else vector_b
                        else:
                            left = vector_a[-lag:]
                            right = vector_b[:bin_count + lag]
                        if len(left) < 20:
                            continue
                        correlation = _pearson(left, right)
                        if correlation is None:
                            continue
                        candidate = (correlation, -abs(lag), -lag, lag)
                        if best is None or candidate > best:
                            best = candidate
                    if best is None:
                        continue
                    correlation, _, _, lag = best
                    if correlation < minimum_correlation:
                        continue
                    candidates.append({
                        "channel_a": channel_a,
                        "can_id_a": id_a,
                        "format_a": "extended" if ext_a else "standard",
                        "frames_a": sum(counts_a.values()),
                        "channel_b": channel_b,
                        "can_id_b": id_b,
                        "format_b": "extended" if ext_b else "standard",
                        "frames_b": sum(counts_b.values()),
                        "correlation": correlation,
                        "lag_seconds": lag * bin_width_seconds,
                        "lag_interpretation": (
                            f"{channel_b} follows {channel_a}" if lag > 0
                            else f"{channel_a} follows {channel_b}" if lag < 0
                            else "activity peaks in the same time bins"
                        ),
                        "evidence_level": "candidate",
                    })

    candidates.sort(
        key=lambda item: (-item["correlation"], abs(item["lag_seconds"]),
                          item["can_id_a"], item["can_id_b"])
    )
    result["candidates"] = candidates[:max_results]
    result["candidate_count"] = len(candidates)
    result["status"] = "candidate relationships found" if candidates else "no candidates above threshold"
    result["search_limits"] = {
        "max_ids_per_channel": max_ids_per_channel,
        "max_results_displayed": max_results,
        "bin_count": bin_count,
    }
    return result
