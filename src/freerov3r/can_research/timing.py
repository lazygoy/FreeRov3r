"""Passive CAN message timing analysis.

Estimates observed inter-frame intervals per CAN ID, format, and channel.
These are capture-derived timing observations, not proof of ECU scheduling or
signal meaning. No frames are transmitted.
"""
from __future__ import annotations

import math
from statistics import median


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def analyze_message_periodicity(frames):
    """Summarize positive inter-frame intervals for each observed CAN node.

    Timestamps are used as supplied by the capture. Their clock domain and
    synchronization quality are not inferred here.
    """
    groups = {}
    invalid_records = 0
    for frame in list(frames or []):
        try:
            can_id = int(frame["arbitration_id"])
            extended = bool(frame.get("extended", False))
            channel = frame.get("channel")
            timestamp = float(frame["timestamp"])
            if not math.isfinite(timestamp):
                raise ValueError("non-finite timestamp")
            bytes.fromhex(str(frame["data"]).replace(" ", ""))
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_records += 1
            continue
        key = (can_id, extended, channel)
        item = groups.setdefault(key, {
            "can_id": can_id,
            "extended": extended,
            "channel": channel,
            "frame_count": 0,
            "timestamps": [],
            "duplicate_timestamp_count": 0,
            "non_monotonic_timestamp_count": 0,
        })
        timestamps = item["timestamps"]
        if timestamps:
            delta = timestamp - timestamps[-1]
            if delta == 0:
                item["duplicate_timestamp_count"] += 1
            elif delta < 0:
                item["non_monotonic_timestamp_count"] += 1
        timestamps.append(timestamp)
        item["frame_count"] += 1

    nodes = []
    for item in groups.values():
        timestamps = item.pop("timestamps")
        intervals = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
            if current > previous
        ]
        typical = median(intervals) if intervals else None
        deviations = [abs(value - typical) for value in intervals] if typical is not None else []
        item.update({
            "interval_count": len(intervals),
            "median_interval_s": typical,
            "mean_interval_s": sum(intervals) / len(intervals) if intervals else None,
            "min_interval_s": min(intervals) if intervals else None,
            "max_interval_s": max(intervals) if intervals else None,
            "p95_absolute_deviation_s": _percentile(deviations, 0.95) if deviations else None,
            "timing_evidence": "Observed capture timestamp intervals",
        })
        nodes.append(item)

    nodes.sort(key=lambda item: (
        item["channel"] or "", item["extended"], item["can_id"]
    ))
    return {
        "method": "passive_capture_timestamp_intervals",
        "transmission_performed": False,
        "invalid_record_count": invalid_records,
        "node_count": len(nodes),
        "nodes": nodes,
        "limitations": [
            "Intervals describe timestamps in the supplied capture clock domain.",
            "Host/device clock quality, buffering, dropped frames, and timestamp resolution can affect estimates.",
            "A median interval is not proof of a configured ECU transmit cycle.",
            "Event-driven traffic can produce irregular intervals even when a message is valid.",
            "CAN IDs, channels, and timing do not establish physical ECU identity.",
        ],
    }
