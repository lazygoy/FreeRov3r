"""Passive CAN payload variability analysis.

Reports observed byte/bit variation per CAN ID, format, channel and DLC.
It does not assign signal meaning, scaling, or vehicle-specific semantics.
"""
from __future__ import annotations

from collections import Counter


def analyze_payload_variability(frames):
    """Summarize observed byte and bit variation without decoding signal meaning."""
    records = list(frames or [])
    groups = {}
    invalid_records = 0

    for frame in records:
        try:
            can_id = int(frame["arbitration_id"])
            if can_id < 0 or can_id > 0x1FFFFFFF:
                raise ValueError("CAN identifier out of range")
            extended = bool(frame.get("extended", False))
            channel = frame.get("channel")
            raw = str(frame["data"]).replace(" ", "").replace("\t", "")
            payload = bytes.fromhex(raw)
            if len(payload) > 64:
                raise ValueError("payload exceeds CAN FD maximum")
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_records += 1
            continue

        key = (can_id, extended, channel, len(payload))
        group = groups.setdefault(key, {
            "can_id": can_id, "extended": extended, "channel": channel,
            "dlc": len(payload), "frame_count": 0,
            "byte_values": [Counter() for _ in payload],
            "bit_ones": [[0] * 8 for _ in payload],
            "bit_transitions": [[0] * 8 for _ in payload],
            "previous_payload": None,
        })
        group["frame_count"] += 1
        for index, value in enumerate(payload):
            group["byte_values"][index][value] += 1
            for bit_index in range(8):
                bit = (value >> (7 - bit_index)) & 1
                group["bit_ones"][index][bit_index] += bit
                previous = group["previous_payload"]
                if previous is not None:
                    old_bit = (previous[index] >> (7 - bit_index)) & 1
                    if bit != old_bit:
                        group["bit_transitions"][index][bit_index] += 1
        group["previous_payload"] = payload

    nodes = []
    for group in groups.values():
        byte_stats = []
        for index, counts in enumerate(group["byte_values"]):
            observed = sorted(counts)
            ones = group["bit_ones"][index]
            transitions = group["bit_transitions"][index]
            common = counts.most_common(1)
            byte_stats.append({
                "offset": index,
                "unique_value_count": len(observed),
                "constant": len(observed) == 1,
                "min_value": observed[0] if observed else None,
                "max_value": observed[-1] if observed else None,
                "most_common_value": common[0][0] if common else None,
                "most_common_count": common[0][1] if common else 0,
                "bit_one_counts_msb_first": ones,
                "bit_transition_counts_msb_first": transitions,
                "variable_bit_mask": sum(
                    (1 << (7 - bit_index))
                    for bit_index, count in enumerate(transitions) if count
                ),
            })
        nodes.append({
            "can_id": group["can_id"],
            "extended": group["extended"],
            "channel": group["channel"],
            "dlc": group["dlc"],
            "frame_count": group["frame_count"],
            "variable_byte_offsets": [
                item["offset"] for item in byte_stats if not item["constant"]
            ],
            "constant_byte_offsets": [
                item["offset"] for item in byte_stats if item["constant"]
            ],
            "bytes": byte_stats,
        })

    nodes.sort(key=lambda item: (
        item["channel"] or "", item["extended"], item["can_id"], item["dlc"]
    ))
    return {
        "method": "passive_payload_byte_and_bit_variability",
        "transmission_performed": False,
        "input_frame_count": len(records),
        "invalid_record_count": invalid_records,
        "node_count": len(nodes),
        "nodes": nodes,
        "limitations": [
            "Groups are separated by CAN ID, format, channel, and payload length.",
            "Variation shows only observed values in this capture; it does not identify signal meaning.",
            "Bit transition counts depend on capture order and may be affected by dropped frames.",
            "Counters do not establish byte order, scaling, signedness, multiplexing, or physical units.",
            "A constant byte may still encode a value that changes outside the captured operating conditions.",
            "No CAN traffic is transmitted and no ECU state is changed.",
        ],
    }
