"""Passive temporal behavior analysis for signals decoded through a loaded DBC.

Only capture-relative elapsed_seconds values are used for rate calculations.
No signal semantics or expected operating ranges are inferred.
"""
from __future__ import annotations

import math


def analyze_dbc_signal_behavior(library, records):
    """Summarize observed numeric signal behavior across one passive capture."""
    frames = list(records or [])
    if library is None or library.database is None:
        return {
            "dbc_loaded": False,
            "input_frame_count": len(frames),
            "matched_frames": 0,
            "unmatched_frames": len(frames),
            "invalid_records": 0,
            "signals": [],
            "limitations": [
                "No DBC was loaded; no signal decoding was performed.",
                "No CAN traffic is transmitted and no ECU state is changed.",
            ],
        }

    groups = {}
    matched_frames = 0
    unmatched_frames = 0
    invalid_records = 0

    for record in frames:
        try:
            if not isinstance(record, dict):
                raise ValueError("record is not an object")
            can_id = int(record["arbitration_id"])
            if can_id < 0 or can_id > 0x1FFFFFFF:
                raise ValueError("CAN identifier out of range")
            extended = bool(record.get("extended", False))
            payload = bytes.fromhex(str(record["data"]))
            if len(payload) > 64:
                raise ValueError("payload exceeds CAN FD maximum")
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_records += 1
            continue

        message = library.messages_by_key.get((can_id, extended))
        if message is None or len(payload) != int(message.length):
            unmatched_frames += 1
            continue
        try:
            decoded = library.decode(can_id, payload, extended)
        except Exception:
            decoded = None
        if decoded is None:
            unmatched_frames += 1
            continue

        matched_frames += 1
        channel = record.get("channel")
        elapsed = None
        try:
            candidate = float(record["elapsed_seconds"])
            if math.isfinite(candidate):
                elapsed = candidate
        except (KeyError, TypeError, ValueError, OverflowError):
            pass

        for name, raw_value in decoded.decoded.items():
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                continue
            value = float(raw_value)
            if not math.isfinite(value):
                continue
            key = (can_id, extended, channel, decoded.message_name, str(name))
            item = groups.setdefault(key, {
                "can_id": can_id,
                "extended": extended,
                "channel": channel,
                "message": decoded.message_name,
                "signal": str(name),
                "unit": decoded.units.get(name, ""),
                "values": [],
                "timed_samples": [],
            })
            item["values"].append(value)
            if elapsed is not None:
                item["timed_samples"].append((elapsed, value))

    results = []
    for item in groups.values():
        values = item["values"]
        timed = item["timed_samples"]
        deltas = []
        rates = []
        duplicate_timestamps = 0
        out_of_order_timestamps = 0
        for (previous_time, previous_value), (current_time, current_value) in zip(timed, timed[1:]):
            delta_time = current_time - previous_time
            if delta_time == 0:
                duplicate_timestamps += 1
                continue
            if delta_time < 0:
                out_of_order_timestamps += 1
                continue
            delta_value = current_value - previous_value
            deltas.append(delta_value)
            rates.append(delta_value / delta_time)

        duration = (
            timed[-1][0] - timed[0][0]
            if len(timed) >= 2 and timed[-1][0] > timed[0][0]
            else None
        )
        results.append({
            "can_id": item["can_id"],
            "format": "EXT" if item["extended"] else "STD",
            "channel": item["channel"],
            "message": item["message"],
            "signal": item["signal"],
            "unit": item["unit"],
            "sample_count": len(values),
            "timed_sample_count": len(timed),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "first": values[0],
            "last": values[-1],
            "net_change": values[-1] - values[0],
            "distinct_values": len(set(values)),
            "value_change_count": sum(
                current != previous for previous, current in zip(values, values[1:])
            ),
            "mean_step_change": sum(deltas) / len(deltas) if deltas else None,
            "max_absolute_rate_per_second": max(
                (abs(rate) for rate in rates), default=None
            ),
            "observed_duration_seconds": duration,
            "average_sample_rate_hz": (
                len(deltas) / duration
                if duration is not None and len(timed) > 1
                else None
            ),
            "duplicate_timestamps": duplicate_timestamps,
            "out_of_order_timestamps": out_of_order_timestamps,
        })

    results.sort(key=lambda item: (
        item["channel"] or "", item["can_id"], item["format"],
        item["message"], item["signal"],
    ))
    return {
        "dbc_loaded": True,
        "dbc_name": getattr(library.path, "name", None),
        "dbc_verification_status": (library.metadata or {}).get(
            "verification_status", "unverified"
        ),
        "input_frame_count": len(frames),
        "matched_frames": matched_frames,
        "unmatched_frames": unmatched_frames,
        "invalid_records": invalid_records,
        "signal_count": len(results),
        "signals": results,
        "limitations": [
            "Only numeric values decoded by the currently loaded DBC are analyzed.",
            "Rate calculations use elapsed_seconds only; frames without it remain in value statistics.",
            "Rates and changes describe this capture and do not establish causation or expected behavior.",
            "DBC scaling, signal meaning, vehicle applicability, and physical bus assignment are not independently verified.",
            "Multiplexed or conditional signals appear only when the decoder returns a numeric value.",
            "No CAN traffic is transmitted and no ECU state is changed.",
        ],
    }
