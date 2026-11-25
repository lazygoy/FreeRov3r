"""Audit passive CAN capture coverage against a loaded DBC."""
from __future__ import annotations

from collections import Counter


def audit_dbc_capture(library, records):
    """Classify DBC coverage without treating unmatched frames as faults."""
    frames = list(records or [])
    counts = Counter()
    messages = Counter()
    unmatched = Counter()
    invalid_records = 0

    if library is None or library.database is None:
        return {
            "dbc_loaded": False,
            "input_frame_count": len(frames),
            "matched_frames": 0,
            "unmatched_frames": len(frames),
            "invalid_records": 0,
            "coverage_percent": 0.0 if frames else None,
            "unmatched_reasons": {"dbc_not_loaded": len(frames)} if frames else {},
            "unmatched_signatures": [],
            "message_frame_counts": {},
            "signal_coverage": {},
            "limitations": [
                "No DBC was loaded; no frame-to-message comparison was performed.",
                "Unmatched traffic is not evidence of a fault or unsupported ECU.",
            ],
        }

    for record in frames:
        try:
            if not isinstance(record, dict):
                raise ValueError("record is not an object")
            can_id = int(record["arbitration_id"])
            if can_id < 0 or can_id > 0x1FFFFFFF:
                raise ValueError("CAN identifier out of range")
            extended = bool(record.get("extended", False))
            channel = record.get("channel")
            payload = bytes.fromhex(str(record["data"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_records += 1
            counts["invalid_record"] += 1
            continue

        message = library.messages_by_key.get((can_id, extended))
        if message is None:
            reason = "no_matching_id_and_format"
        elif len(payload) != int(message.length):
            reason = "payload_length_mismatch"
        else:
            decoded = library.decode(can_id, payload, extended)
            if decoded is None:
                reason = "decode_failed"
            else:
                counts["matched"] += 1
                messages[f"0x{can_id:X} {'EXT' if extended else 'STD'} {decoded.message_name}"] += 1
                continue

        counts[reason] += 1
        signature = (can_id, extended, channel, len(payload), reason)
        unmatched[signature] += 1

    matched = counts["matched"]
    unmatched_count = len(frames) - matched - invalid_records
    denominator = len(frames) - invalid_records
    signal_coverage = library.decode_coverage(frames)
    signatures = [
        {
            "can_id": key[0],
            "extended": key[1],
            "channel": key[2],
            "dlc": key[3],
            "reason": key[4],
            "count": value,
        }
        for key, value in sorted(
            unmatched.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]
    return {
        "dbc_loaded": True,
        "dbc_name": getattr(library.path, "name", None),
        "dbc_verification_status": (library.metadata or {}).get("verification_status", "unverified"),
        "input_frame_count": len(frames),
        "matched_frames": matched,
        "unmatched_frames": unmatched_count,
        "invalid_records": invalid_records,
        "coverage_percent": (matched / denominator * 100.0) if denominator else None,
        "unmatched_reasons": {
            key: value for key, value in counts.items() if key != "matched"
        },
        "unmatched_signatures": signatures,
        "message_frame_counts": dict(sorted(messages.items())),
        "signal_coverage": {
            "signals_with_numeric_samples": len(signal_coverage.get("signals", {})),
            "messages_with_samples": len(signal_coverage.get("messages", {})),
            "signal_statistics": signal_coverage.get("signals", {}),
        },
        "limitations": [
            "Coverage means only that a frame matched a DBC message definition and decoded.",
            "A match does not verify vehicle applicability, bus assignment, signal meaning, or DBC correctness.",
            "Unmatched frames may belong to another network, use another payload length, or be absent from this DBC.",
            "Out-of-range values are reported separately by the underlying DBC coverage statistics.",
            "This audit is passive; it transmits no CAN traffic and changes no ECU state.",
        ],
    }
