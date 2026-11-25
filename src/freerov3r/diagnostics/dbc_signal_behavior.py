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


def build_dbc_signal_series(library, records, markers=None):
    """Build timestamped numeric DBC series and operator markers for plotting.

    Series are separated by CAN ID, frame format, channel, message and signal.
    Only finite capture-relative elapsed_seconds values are plotted. Samples are
    sorted by that timestamp, while duplicate timestamps are retained.
    """
    if library is None or library.database is None:
        return {"signals": [], "markers": []}

    groups = {}
    for record in records or []:
        try:
            if not isinstance(record, dict):
                continue
            can_id = int(record["arbitration_id"])
            if not 0 <= can_id <= 0x1FFFFFFF:
                continue
            extended = bool(record.get("extended", False))
            payload = bytes.fromhex(str(record["data"]))
            elapsed = float(record["elapsed_seconds"])
            if not math.isfinite(elapsed) or len(payload) > 64:
                continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

        message = library.messages_by_key.get((can_id, extended))
        if message is None or len(payload) != int(message.length):
            continue
        try:
            decoded = library.decode(can_id, payload, extended)
        except Exception:
            continue
        if decoded is None:
            continue

        channel = record.get("channel")
        for name, raw_value in decoded.decoded.items():
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                continue
            value = float(raw_value)
            if not math.isfinite(value):
                continue
            key = (can_id, extended, channel, decoded.message_name, str(name))
            item = groups.setdefault(key, {
                "can_id": can_id,
                "format": "EXT" if extended else "STD",
                "channel": channel,
                "message": decoded.message_name,
                "signal": str(name),
                "unit": decoded.units.get(name, "") or "",
                "samples": [],
            })
            item["samples"].append((elapsed, value))

    signals = []
    for key, item in groups.items():
        item["samples"].sort(key=lambda sample: sample[0])
        item["sample_count"] = len(item["samples"])
        item["minimum"] = min(value for _, value in item["samples"])
        item["maximum"] = max(value for _, value in item["samples"])
        item["key"] = "|".join((
            str(item["channel"] or "Unknown"),
            f"{item['can_id']:X}", item["format"], item["message"], item["signal"],
        ))
        signals.append(item)
    signals.sort(key=lambda item: (
        item["channel"] or "", item["can_id"], item["format"],
        item["message"], item["signal"],
    ))

    plotted_markers = []
    for index, marker in enumerate(markers or [], start=1):
        if not isinstance(marker, dict):
            continue
        try:
            elapsed = float(marker["elapsed_seconds"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(elapsed):
            continue
        operation = str(marker.get("operation") or "Unspecified")
        note = str(marker.get("note") or "").strip()
        plotted_markers.append({
            "elapsed_seconds": elapsed,
            "label": f"{index}. {operation}" + (f" ({note})" if note else ""),
        })
    plotted_markers.sort(key=lambda item: item["elapsed_seconds"])
    return {"signals": signals, "markers": plotted_markers}


def format_dbc_marker_signal_summary_table(marker_results):
    """Render marker signal summaries as a compact, human-readable Markdown table."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    def number(value):
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError, OverflowError):
            return "n/a"

    lines = [
        "| Marker | Operation | Channel | CAN ID | Message | Signal | Unit | Before n | Before mean | Before min | Before max | After n | After mean | After min | After max | Mean Δ | First after (s) |",
        "|---:|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for marker_result in marker_results or []:
        marker = marker_result.get("marker") or {}
        marker_index = marker_result.get("marker_index", "")
        operation = cell(marker.get("operation") or "Unspecified")
        for signal in marker_result.get("signals", []):
            can_id = signal.get("can_id")
            can_id_text = f"0x{int(can_id):X}" if can_id is not None else "n/a"
            lines.append("| " + " | ".join((
                cell(marker_index), operation, cell(signal.get("channel") or "unspecified"),
                can_id_text, cell(signal.get("message") or ""), cell(signal.get("signal") or ""),
                cell(signal.get("unit") or ""), str(signal.get("before_sample_count", 0)),
                number(signal.get("before_mean")), number(signal.get("before_min")),
                number(signal.get("before_max")), str(signal.get("after_sample_count", 0)),
                number(signal.get("after_mean")), number(signal.get("after_min")),
                number(signal.get("after_max")), number(signal.get("mean_delta")),
                number(signal.get("first_after_marker_seconds")),
            )) + " |")
    if len(lines) == 2:
        lines.append("| No decoded numeric signal samples in the selected marker windows. |" + " |" * 16)
    return "\n".join(lines)


def summarize_dbc_marker_signal_changes(series_data, markers, *, before_seconds=2.0, after_seconds=5.0):
    """Summarize decoded numeric signal changes around each scanner marker.

    Samples are grouped by the full DBC series identity (channel, CAN ID,
    frame format, message and signal). A mean shift is reported only when
    both windows contain samples. This is temporal correlation, not proof
    that the marked operation caused a signal change.
    """
    import math

    if before_seconds < 0 or after_seconds < 0:
        raise ValueError("Marker windows must be non-negative")

    signals = (series_data or {}).get("signals", [])
    results = []
    for marker_index, marker in enumerate(markers or [], start=1):
        if not isinstance(marker, dict):
            continue
        try:
            center = float(marker["elapsed_seconds"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(center):
            continue

        changes = []
        for signal in signals:
            before = []
            after = []
            for sample in signal.get("samples", []):
                try:
                    elapsed, value = float(sample[0]), float(sample[1])
                except (TypeError, ValueError, IndexError, OverflowError):
                    continue
                if not math.isfinite(elapsed) or not math.isfinite(value):
                    continue
                if center - before_seconds <= elapsed < center:
                    before.append((elapsed, value))
                elif center <= elapsed <= center + after_seconds:
                    after.append((elapsed, value))

            if not before and not after:
                continue
            before_values = [value for _, value in before]
            after_values = [value for _, value in after]
            before_mean = sum(before_values) / len(before_values) if before_values else None
            after_mean = sum(after_values) / len(after_values) if after_values else None
            changes.append({
                "can_id": signal.get("can_id"),
                "format": signal.get("format"),
                "channel": signal.get("channel"),
                "message": signal.get("message"),
                "signal": signal.get("signal"),
                "unit": signal.get("unit", ""),
                "before_sample_count": len(before_values),
                "after_sample_count": len(after_values),
                "before_mean": before_mean,
                "after_mean": after_mean,
                "mean_delta": (after_mean - before_mean
                               if before_mean is not None and after_mean is not None
                               else None),
                "before_min": min(before_values) if before_values else None,
                "before_max": max(before_values) if before_values else None,
                "after_min": min(after_values) if after_values else None,
                "after_max": max(after_values) if after_values else None,
                "first_after_marker_seconds": (
                    min(elapsed for elapsed, _ in after) - center if after else None
                ),
            })

        changes.sort(key=lambda item: (
            item["mean_delta"] is None,
            -abs(item["mean_delta"]) if item["mean_delta"] is not None else 0,
            str(item["channel"] or ""), item["can_id"] or 0,
            str(item["message"] or ""), str(item["signal"] or ""),
        ))
        results.append({
            "marker_index": marker_index,
            "marker": dict(marker),
            "before_seconds": before_seconds,
            "after_seconds": after_seconds,
            "signal_count": len(changes),
            "signals": changes,
            "interpretation": "Temporal association only; this does not establish causation.",
        })
    return results
