"""Passive ECU/module discovery from already captured CAN traffic.

This analyzer never sends diagnostic requests. It reports observed CAN IDs and
probable UDS responder relationships without assigning an ECU name from an
address pattern alone.
"""
from collections import defaultdict

from ..isotp import pair_uds_transactions, reassemble_isotp, summarize_ecu_address_pairs


def discover_modules(frames, *, response_window=2.0):
    """Summarize observed CAN nodes and candidate UDS responders.

    Args:
        frames: Capture records accepted by :func:`reassemble_isotp`.
        response_window: Maximum request/response pairing interval in seconds.

    Returns:
        A JSON-serializable report. Each observed CAN ID is kept separate by
        channel and extended/standard format. Only IDs appearing as the
        response side of a probable UDS pair are labelled candidate responders.
        No module names or verified ECU identities are inferred.
    """
    records = list(frames or [])
    observed = {}
    for frame in records:
        try:
            can_id = int(frame["arbitration_id"])
            extended = bool(frame.get("extended", False))
            channel = frame.get("channel")
            timestamp = float(frame.get("timestamp", 0.0) or 0.0)
            data = str(frame["data"]).replace(" ", "").upper()
            bytes.fromhex(data)
        except (KeyError, TypeError, ValueError):
            continue
        key = (can_id, extended, channel)
        item = observed.setdefault(key, {
            "can_id": can_id,
            "extended": extended,
            "channel": channel,
            "frame_count": 0,
            "first_timestamp": timestamp,
            "last_timestamp": timestamp,
            "sample_payloads": [],
        })
        item["frame_count"] += 1
        item["first_timestamp"] = min(item["first_timestamp"], timestamp)
        item["last_timestamp"] = max(item["last_timestamp"], timestamp)
        if data and data not in item["sample_payloads"] and len(item["sample_payloads"]) < 5:
            item["sample_payloads"].append(data)

    messages = reassemble_isotp(records)
    complete_messages = [item for item in messages if item.get("status") == "complete"]
    transactions = pair_uds_transactions(
        complete_messages, response_window=response_window
    )
    address_pairs = summarize_ecu_address_pairs(transactions)

    responders = defaultdict(lambda: {
        "pair_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "services": set(),
        "request_ids": set(),
        "addressing_hints": set(),
    })
    for pair in address_pairs:
        key = (pair["response_id"], pair["extended"], pair.get("channel"))
        candidate = responders[key]
        candidate["pair_count"] += pair["pair_count"]
        candidate["positive_count"] += pair["positive_count"]
        candidate["negative_count"] += pair["negative_count"]
        candidate["services"].update(pair["services"])
        candidate["request_ids"].add(pair["request_id"])
        candidate["addressing_hints"].add(pair["addressing_hint"])

    nodes = []
    for key, item in observed.items():
        candidate = responders.get(key)
        if candidate:
            item.update({
                "role": "candidate_uds_responder",
                "evidence_level": "Probable",
                "interpretation": (
                    "Observed as the response CAN ID in probable UDS "
                    "request/response associations; physical ECU identity unknown"
                ),
                "uds_pair_count": candidate["pair_count"],
                "positive_response_count": candidate["positive_count"],
                "negative_response_count": candidate["negative_count"],
                "request_ids": sorted(candidate["request_ids"]),
                "services": sorted(candidate["services"]),
                "addressing_hints": sorted(candidate["addressing_hints"]),
            })
        else:
            item.update({
                "role": "observed_can_node",
                "evidence_level": "Observed",
                "interpretation": (
                    "CAN traffic observed; diagnostic role and ECU identity unknown"
                ),
                "uds_pair_count": 0,
                "positive_response_count": 0,
                "negative_response_count": 0,
                "request_ids": [],
                "services": [],
                "addressing_hints": [],
            })
        nodes.append(item)

    nodes.sort(key=lambda item: (
        item["channel"] or "", item["extended"], item["can_id"]
    ))
    return {
        "method": "passive_capture_analysis",
        "transmission_performed": False,
        "frame_count": len(records),
        "valid_observed_id_count": len(observed),
        "isotp_message_count": len(messages),
        "complete_isotp_message_count": len(complete_messages),
        "probable_uds_transaction_count": len(transactions),
        "nodes": nodes,
        "address_pairs": address_pairs,
        "limitations": [
            "CAN IDs are observations, not ECU identities.",
            "A probable UDS response association does not prove physical addressing or module identity.",
            "Absence from a capture does not prove that a module is absent or unsupported.",
            "Observed traffic depends on vehicle state, network gateway behavior, capture channel, and capture duration.",
            "Evidence levels Documented and Verified require independent source-backed validation and are never assigned by this passive analyzer.",
        ],
    }
