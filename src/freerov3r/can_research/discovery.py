"""Passive ECU/module discovery from already captured CAN traffic.

This analyzer never sends diagnostic requests. It reports observed CAN IDs and
probable UDS responder relationships without assigning an ECU name from an
address pattern alone.
"""
from collections import defaultdict

from .timing import analyze_message_periodicity
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

    timing_report = analyze_message_periodicity(records)
    timing_by_key = {
        (item["can_id"], item["extended"], item.get("channel")): item
        for item in timing_report["nodes"]
    }

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
        item["timing"] = timing_by_key.get(key)
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
        "timing_analysis": timing_report,
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


def compare_module_discovery(captures):
    """Compare passive module observations across independent captures.

    A node is keyed by CAN ID, CAN format, and channel. Repeated observation
    improves repeatability evidence but never upgrades an ECU identity to
    Documented or Verified. Each capture is analyzed independently so UDS
    requests and responses are never paired across capture boundaries.
    """
    capture_list = [item for item in (captures or []) if isinstance(item, dict)]
    name_totals = {}
    for capture in capture_list:
        name = str(capture.get("name") or "Unnamed capture")
        name_totals[name] = name_totals.get(name, 0) + 1

    aggregates = {}
    capture_reports = []
    for index, capture in enumerate(capture_list):
        base_name = str(capture.get("name") or "Unnamed capture")
        name = (
            f"{base_name} [capture {index + 1}]"
            if name_totals[base_name] > 1 else base_name
        )
        report = discover_modules(capture.get("frames") or [])
        capture_reports.append({
            "name": name,
            "frame_count": report["frame_count"],
            "observed_node_count": report["valid_observed_id_count"],
            "probable_responder_count": sum(
                node["role"] == "candidate_uds_responder"
                for node in report["nodes"]
            ),
        })
        for node in report["nodes"]:
            key = (node["can_id"], node["extended"], node.get("channel"))
            item = aggregates.setdefault(key, {
                "can_id": node["can_id"],
                "extended": node["extended"],
                "channel": node.get("channel"),
                "capture_names": set(),
                "observed_frame_count": 0,
                "probable_capture_names": set(),
                "uds_pair_count": 0,
                "positive_response_count": 0,
                "negative_response_count": 0,
                "request_ids": set(),
                "services": set(),
                "addressing_hints": set(),
            })
            item["capture_names"].add(name)
            item["observed_frame_count"] += node["frame_count"]
            if node["role"] == "candidate_uds_responder":
                item["probable_capture_names"].add(name)
            item["uds_pair_count"] += node["uds_pair_count"]
            item["positive_response_count"] += node["positive_response_count"]
            item["negative_response_count"] += node["negative_response_count"]
            item["request_ids"].update(node["request_ids"])
            item["services"].update(node["services"])
            item["addressing_hints"].update(node["addressing_hints"])

    nodes = []
    for item in aggregates.values():
        names = sorted(item["capture_names"])
        probable_names = sorted(item["probable_capture_names"])
        item["capture_names"] = names
        item["capture_count"] = len(names)
        item["probable_capture_names"] = probable_names
        item["probable_capture_count"] = len(probable_names)
        item["request_ids"] = sorted(item["request_ids"])
        item["services"] = sorted(item["services"])
        item["addressing_hints"] = sorted(item["addressing_hints"])
        item["role"] = (
            "candidate_uds_responder" if probable_names else "observed_can_node"
        )
        item["evidence_level"] = "Probable" if probable_names else "Observed"
        item["repeatability"] = (
            "Seen in multiple captures" if len(names) >= 2
            else "Seen in one capture only"
        )
        item["interpretation"] = (
            "Probable UDS response association in at least one independent capture; "
            "physical ECU identity unknown"
            if probable_names else
            "CAN traffic observed across captures; diagnostic role and ECU identity unknown"
        )
        nodes.append(item)

    nodes.sort(key=lambda item: (
        item["channel"] or "", item["extended"], item["can_id"]
    ))
    return {
        "method": "independent_passive_capture_comparison",
        "transmission_performed": False,
        "capture_count": len(capture_reports),
        "captures": capture_reports,
        "node_count": len(nodes),
        "nodes": nodes,
        "limitations": [
            "Each capture is analyzed independently; transactions are never paired across captures.",
            "Repeated observation establishes repeatability, not physical ECU identity.",
            "Probable responder evidence means a CAN ID appeared as the response side of a probable UDS association in at least one capture.",
            "A node absent from a capture may simply have been inactive or outside the captured bus or time window.",
            "Documented and Verified evidence require independent source-backed validation and are never assigned by this comparison.",
        ],
    }
