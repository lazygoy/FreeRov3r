"""Private protocol research workspace for FreeRov3r.

This module is intentionally separate from the standard diagnostic workflows.
It records and analyzes traffic already delivered by the selected CAN adapter;
it never transmits diagnostic requests or replays captured frames.
"""
import csv
import difflib
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QGridLayout, QWidget,
)

from freerov3r.did_definitions import DIDDefinitionRegistry, decode_uds_did_transactions
from freerov3r.dbc_support import DBCLibrary, DBCUnavailableError
from freerov3r.timestamp_analysis import analyze_channel_timestamps
from freerov3r.diagnostics.can_timing_analysis import analyze_message_periodicity
from freerov3r.diagnostics.payload_variability import analyze_payload_variability
from freerov3r.diagnostics.dbc_capture_audit import audit_dbc_capture
from freerov3r.diagnostics.dbc_signal_behavior import (
    analyze_dbc_signal_behavior, build_dbc_signal_series,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    from PySide6.QtGui import QPen
    from PySide6.QtWidgets import QListWidget, QListWidgetItem
    HAS_RESEARCH_CHARTS = True
except ImportError:
    QChart = QChartView = QLineSeries = QValueAxis = QPen = None
    QListWidget = QListWidgetItem = None
    HAS_RESEARCH_CHARTS = False
from freerov3r.diagnostics.module_discovery import (
    compare_module_discovery, discover_modules,
)

from freerov3r.isotp import (
    pair_uds_transactions, reassemble_isotp, summarize_ecu_address_pairs,
    summarize_cross_capture_address_pairs,
)


UDS_SERVICES = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
}


def classify_can_payload(payload):
    """Return conservative ISO-TP/UDS hints; never claims to identify intent."""
    data = bytes(payload or b"")
    if not data:
        return "—", "—"

    pci_type = data[0] >> 4
    if pci_type == 0 and len(data) > 1:
        if data[0] & 0x0F:
            service_index = 1
        elif len(data) > 2:
            service_index = 2
        else:
            return "ISO-TP SF", "Extended-length single frame"
        service = data[service_index]
        name = UDS_SERVICES.get(service)
        if service == 0x7F and len(data) >= 3:
            original = UDS_SERVICES.get(data[2], f"0x{data[2]:02X}")
            return "ISO-TP SF", f"Negative response to {original} (NRC 0x{data[3]:02X})" if len(data) > 3 else f"Negative response to {original}"
        if name:
            return "ISO-TP SF", name
        if 0x40 <= service <= 0x7E:
            request_name = UDS_SERVICES.get(service - 0x40)
            if request_name:
                return "ISO-TP SF", f"Positive response to {request_name} (0x{service:02X})"
            return "ISO-TP SF", f"Possible positive response 0x{service:02X}"
        return "ISO-TP SF", "Unclassified service"

    if pci_type == 1:
        return "ISO-TP FF", "First frame"
    if pci_type == 2:
        return "ISO-TP CF", f"Consecutive frame (sequence {data[0] & 0x0F})"
    if pci_type == 3:
        flow = {0: "Continue", 1: "Wait", 2: "Overflow"}.get(data[0] & 0x0F, "Unknown")
        return "ISO-TP FC", f"Flow control: {flow}"

    # Reassembled ISO-TP payloads no longer contain a PCI byte.
    service = data[0]
    if service == 0x7F and len(data) >= 3:
        original = UDS_SERVICES.get(data[1], f"0x{data[1]:02X}")
        return "UDS payload", f"Negative response to {original} (NRC 0x{data[2]:02X})"
    if 0x40 <= service <= 0x7E:
        request_name = UDS_SERVICES.get(service - 0x40)
        if request_name:
            return "UDS payload", f"Positive response to {request_name} (0x{service:02X})"
    if service in UDS_SERVICES:
        return "UDS payload", f"Possible raw UDS: {UDS_SERVICES[service]}"
    return "Unclassified", "No reliable UDS classification"



def classify_uds_payload(payload):
    """Name a UDS service in a reassembled application payload."""
    data = bytes(payload or b"")
    if not data:
        return "Empty payload"
    service = data[0]
    if service == 0x7F:
        if len(data) < 3:
            return "Malformed negative response"
        original = UDS_SERVICES.get(data[1], f"0x{data[1]:02X}")
        return f"Negative response to {original} (NRC 0x{data[2]:02X})"
    if service in UDS_SERVICES:
        return UDS_SERVICES[service]
    if 0x40 <= service <= 0x7E:
        original = UDS_SERVICES.get(service - 0x40)
        if original:
            return f"Positive response to {original}"
    return f"Unclassified service 0x{service:02X}"



def analyze_marker_windows(frames, markers, *, before_seconds=2.0, after_seconds=5.0):
    """Compare CAN traffic immediately before and after each monotonic action marker.

    Frames without elapsed_seconds are deliberately excluded: wall-clock and bus
    timestamps are not assumed to share a clock with the operator's monotonic timer.
    """
    if before_seconds < 0 or after_seconds < 0:
        raise ValueError("Marker windows must be non-negative")
    timed = []
    for frame in frames:
        try:
            elapsed = float(frame["elapsed_seconds"])
            can_id = int(frame["arbitration_id"])
            payload = bytes.fromhex(str(frame.get("data", ""))).hex()
        except (KeyError, TypeError, ValueError):
            continue
        timed.append((elapsed, can_id, bool(frame.get("extended", False)),
                      frame.get("channel"), payload))

    results = []
    for index, marker in enumerate(markers):
        try:
            center = float(marker["elapsed_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        before = [item for item in timed if center - before_seconds <= item[0] < center]
        after = [item for item in timed if center <= item[0] <= center + after_seconds]
        def counts(items):
            result = Counter()
            for _, can_id, extended, channel, payload in items:
                result[(can_id, extended, channel, payload)] += 1
            return result
        pre_counts, post_counts = counts(before), counts(after)
        keys = set(pre_counts) | set(post_counts)
        changes = []
        for key in keys:
            delta = post_counts[key] - pre_counts[key]
            if delta:
                can_id, extended, channel, payload = key
                changes.append({
                    "can_id": can_id, "extended": extended, "channel": channel,
                    "payload": payload, "before_count": pre_counts[key],
                    "after_count": post_counts[key], "delta": delta,
                })
        changes.sort(key=lambda item: (-abs(item["delta"]), item["can_id"], item["payload"]))
        results.append({
            "marker_index": index + 1,
            "marker": marker,
            "before_frames": len(before),
            "after_frames": len(after),
            "changes": changes,
            "timed_frame_count": len(before) + len(after),
        })
    return results


def compare_operation_sequences(captures, *, before_seconds=2.0, after_seconds=5.0):
    """Aggregate marker-window CAN evidence for the same operations across captures.

    Counts are normalized to frames/second because the baseline and response
    windows have different durations. Each capture is analyzed independently;
    missing monotonic timestamps are ignored rather than guessed.
    """
    if before_seconds <= 0 or after_seconds <= 0:
        raise ValueError("Comparison windows must be positive")

    capture_list = [item for item in (captures or []) if isinstance(item, dict)]
    name_totals = {}
    for item in capture_list:
        base_name = str(item.get("name") or "Unnamed capture")
        name_totals[base_name] = name_totals.get(base_name, 0) + 1

    operation_groups = {}
    capture_sequences = []
    for capture_index, capture in enumerate(capture_list):
        if not isinstance(capture, dict):
            continue
        base_name = str(capture.get("name") or "Unnamed capture")
        name = (
            f"{base_name} [capture {capture_index + 1}]"
            if name_totals[base_name] > 1 else base_name
        )
        frames = capture.get("frames") or []
        markers = capture.get("markers") or []
        valid_markers = []
        for marker in markers:
            if not isinstance(marker, dict):
                continue
            try:
                float(marker["elapsed_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            valid_markers.append(marker)

        capture_sequences.append({
            "name": name,
            "operations": [str(m.get("operation") or "Unspecified") for m in valid_markers],
            "marker_count": len(valid_markers),
        })

        windows = analyze_marker_windows(
            frames, valid_markers,
            before_seconds=before_seconds,
            after_seconds=after_seconds,
        )
        for window in windows:
            marker = window["marker"]
            operation = str(marker.get("operation") or "Unspecified")
            group = operation_groups.setdefault(operation, {
                "operation": operation,
                "marker_count": 0,
                "capture_names": set(),
                "signals": {},
            })
            group["marker_count"] += 1
            group["capture_names"].add(name)

            try:
                center = float(marker["elapsed_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            matching_frames = {}
            for frame in frames:
                try:
                    elapsed = float(frame["elapsed_seconds"])
                    can_id = int(frame["arbitration_id"])
                    payload = bytes.fromhex(str(frame.get("data", ""))).hex()
                except (KeyError, TypeError, ValueError):
                    continue
                if center <= elapsed <= center + after_seconds:
                    key = (can_id, bool(frame.get("extended", False)),
                           frame.get("channel"), payload)
                    matching_frames.setdefault(key, []).append(elapsed)

            before_counts = Counter()
            after_counts = Counter()
            # Count each frame exactly once, including unchanged background signatures.
            for frame in frames:
                try:
                    elapsed = float(frame["elapsed_seconds"])
                    can_id = int(frame["arbitration_id"])
                    payload = bytes.fromhex(str(frame.get("data", ""))).hex()
                except (KeyError, TypeError, ValueError):
                    continue
                if center - before_seconds <= elapsed <= center + after_seconds:
                    key = (can_id, bool(frame.get("extended", False)),
                           frame.get("channel"), payload)
                    if elapsed < center:
                        before_counts[key] += 1
                    else:
                        after_counts[key] += 1

            for key in set(before_counts) | set(after_counts):
                can_id, extended, channel, payload = key
                signal = group["signals"].setdefault(key, {
                    "can_id": can_id,
                    "extended": extended,
                    "channel": channel,
                    "payload": payload,
                    "observations": 0,
                    "capture_names": set(),
                    "before_rates": [],
                    "after_rates": [],
                    "response_delays": [],
                })
                signal["observations"] += 1
                signal["capture_names"].add(name)
                signal["before_rates"].append(before_counts[key] / before_seconds)
                signal["after_rates"].append(after_counts[key] / after_seconds)
                offsets = matching_frames.get(key, [])
                if offsets:
                    signal["response_delays"].append(min(offsets) - center)

    operations = []
    for group in operation_groups.values():
        signals = []
        for signal in group["signals"].values():
            before_rates = signal.pop("before_rates")
            after_rates = signal.pop("after_rates")
            delays = sorted(signal.pop("response_delays"))
            signal["capture_names"] = sorted(signal["capture_names"])
            signal["capture_count"] = len(signal["capture_names"])
            signal["average_before_frames_per_second"] = (
                sum(before_rates) / len(before_rates) if before_rates else 0.0
            )
            signal["average_after_frames_per_second"] = (
                sum(after_rates) / len(after_rates) if after_rates else 0.0
            )
            signal["median_response_delay_seconds"] = (
                ((delays[(len(delays) - 1) // 2] + delays[len(delays) // 2]) / 2) if delays else None
            )
            signal["repeatability"] = (
                "Seen in multiple captures" if signal["capture_count"] >= 2
                else "Seen in one capture only"
            )
            signals.append(signal)
        signals.sort(key=lambda item: (
            -item["capture_count"], -item["observations"],
            item["can_id"], item["payload"],
        ))
        operations.append({
            "operation": group["operation"],
            "marker_count": group["marker_count"],
            "capture_names": sorted(group["capture_names"]),
            "capture_count": len(group["capture_names"]),
            "signals": signals,
        })

    operations.sort(key=lambda item: item["operation"].casefold())

    sequence_comparisons = []
    if capture_sequences:
        reference = capture_sequences[0]
        reference_ops = reference["operations"]
        for capture in capture_sequences[1:]:
            candidate_ops = capture["operations"]
            changes = []
            matcher = difflib.SequenceMatcher(
                a=reference_ops, b=candidate_ops, autojunk=False
            )
            for tag, ref_start, ref_end, cur_start, cur_end in matcher.get_opcodes():
                if tag == "equal":
                    continue
                changes.append({
                    "change_type": tag,
                    "reference_index": ref_start,
                    "capture_index": cur_start,
                    "reference_operations": reference_ops[ref_start:ref_end],
                    "capture_operations": candidate_ops[cur_start:cur_end],
                })
            sequence_comparisons.append({
                "reference_name": reference["name"],
                "capture_name": capture["name"],
                "matches_reference": not changes,
                "changes": changes,
            })

    return {
        "capture_sequences": capture_sequences,
        "sequence_reference": capture_sequences[0]["name"] if capture_sequences else None,
        "sequence_comparisons": sequence_comparisons,
        "operations": operations,
        "capture_count": len(capture_sequences),
        "before_seconds": before_seconds,
        "after_seconds": after_seconds,
    }



def summarize_operation_uds_transactions(captures, *, after_seconds=5.0,
                                          response_window=2.0):
    """Correlate probable UDS transactions with marked operations across captures.

    Frame monotonic elapsed_seconds are copied into the timestamp field for
    per-capture ISO-TP reassembly. Wall-clock timestamps are never mixed in.
    Only complete, probable request/response pairs are included.
    """
    if after_seconds <= 0:
        raise ValueError("Operation window must be positive")
    if response_window < 0:
        raise ValueError("Response window must be non-negative")

    capture_list = [item for item in (captures or []) if isinstance(item, dict)]
    name_totals = {}
    for item in capture_list:
        base_name = str(item.get("name") or "Unnamed capture")
        name_totals[base_name] = name_totals.get(base_name, 0) + 1

    groups = {}
    for capture_index, capture in enumerate(capture_list):
        base_name = str(capture.get("name") or "Unnamed capture")
        capture_name = (
            f"{base_name} [capture {capture_index + 1}]"
            if name_totals[base_name] > 1 else base_name
        )
        frames = []
        for frame in capture.get("frames") or []:
            if not isinstance(frame, dict):
                continue
            try:
                elapsed = float(frame["elapsed_seconds"])
                int(frame["arbitration_id"])
                bytes.fromhex(str(frame.get("data", "")).replace(" ", ""))
            except (KeyError, TypeError, ValueError):
                continue
            normalized = dict(frame)
            normalized["timestamp"] = elapsed
            frames.append(normalized)

        messages = reassemble_isotp(frames)
        transactions = pair_uds_transactions(
            messages, response_window=response_window
        )
        markers = []
        for marker in capture.get("markers") or []:
            if not isinstance(marker, dict):
                continue
            try:
                center = float(marker["elapsed_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            operation = str(marker.get("operation") or "Unspecified")
            markers.append((center, operation))
            group = groups.setdefault(operation, {
                "operation": operation,
                "capture_names": set(),
                "transactions": {},
            })
            group["capture_names"].add(capture_name)

        for transaction in transactions:
            if transaction.get("confidence") != "probable":
                continue
            request = transaction.get("request") or {}
            response = transaction.get("response") or {}
            try:
                request_time = float(request["started_at"])
                service = int(transaction["request_service"])
                request_id = int(request["arbitration_id"])
                response_id = int(response["arbitration_id"])
                latency = float(transaction["latency_seconds"])
                request_payload = bytes.fromhex(request.get("payload", "")).hex()
                response_payload = bytes.fromhex(response.get("payload", "")).hex()
            except (KeyError, TypeError, ValueError):
                continue

            matching_markers = [
                (center, operation) for center, operation in markers
                if center <= request_time <= center + after_seconds
            ]
            if not matching_markers:
                continue
            # If windows overlap, associate with the most recent preceding marker.
            _, operation = max(matching_markers, key=lambda item: item[0])
            response_kind = str(transaction.get("response_kind") or "unknown")
            key = (
                request_id, response_id, bool(request.get("extended", False)),
                request.get("channel"), service, request_payload,
                response_kind, response_payload,
            )
            group = groups.setdefault(operation, {
                "operation": operation,
                "capture_names": set(),
                "transactions": {},
            })
            item = group["transactions"].setdefault(key, {
                "request_id": request_id,
                "response_id": response_id,
                "extended": bool(request.get("extended", False)),
                "channel": request.get("channel"),
                "service": service,
                "request_payload": request_payload,
                "response_kind": response_kind,
                "response_payload": response_payload,
                "capture_names": set(),
                "latencies": [],
                "count": 0,
            })
            item["capture_names"].add(capture_name)
            item["latencies"].append(latency)
            item["count"] += 1

    results = []
    for group in groups.values():
        items = []
        for item in group["transactions"].values():
            latencies = sorted(item.pop("latencies"))
            item["capture_names"] = sorted(item["capture_names"])
            item["capture_count"] = len(item["capture_names"])
            item["median_latency_seconds"] = (
                (latencies[(len(latencies) - 1) // 2] +
                 latencies[len(latencies) // 2]) / 2
            )
            item["repeatability"] = (
                "Seen in multiple captures" if item["capture_count"] >= 2
                else "Seen in one capture only"
            )
            items.append(item)
        items.sort(key=lambda item: (
            -item["capture_count"], item["request_id"], item["service"],
            item["response_kind"], item["request_payload"],
        ))
        names = sorted(group["capture_names"])
        results.append({
            "operation": group["operation"],
            "capture_names": names,
            "capture_count": len(names),
            "transactions": items,
        })
    results.sort(key=lambda item: item["operation"].casefold())
    return results



def summarize_operation_uds_identifiers(operation_summaries):
    """Aggregate observed UDS DIDs and routine IDs without guessing their meaning.

    DID requests can contain multiple two-byte identifiers. Positive DID
    responses are only decoded for their first identifier because subsequent
    record boundaries depend on ECU-specific data lengths.
    """
    aggregates = {}
    for operation in operation_summaries or []:
        operation_name = str(operation.get("operation") or "Unspecified")
        for transaction in operation.get("transactions") or []:
            try:
                service = int(transaction["service"])
                request = bytes.fromhex(transaction.get("request_payload", ""))
                response = bytes.fromhex(transaction.get("response_payload", ""))
            except (KeyError, TypeError, ValueError):
                continue
            if not request or request[0] != service:
                continue

            identifiers = []
            if service in (0x22, 0x2E, 0x2F):
                access = {
                    0x22: "Read",
                    0x2E: "Write",
                    0x2F: "I/O control",
                }[service]
                tail = request[1:]
                if len(tail) < 2:
                    continue
                # ReadDataByIdentifier can request several DIDs in one message.
                # Write and I/O-control requests have one DID followed by data.
                offsets = range(0, len(tail) - 1, 2) if service == 0x22 else (0,)
                for offset in offsets:
                    did = int.from_bytes(tail[offset:offset + 2], "big")
                    identifiers.append({
                        "kind": "DID",
                        "identifier": did,
                        "label": f"DID 0x{did:04X}",
                        "access": access,
                        "subfunction": None,
                        "routine_control_type": None,
                        "routine_control_name": None,
                    })
            elif service == 0x31 and len(request) >= 4:
                raw_subfunction = request[1]
                routine_id = int.from_bytes(request[2:4], "big")
                control_type = raw_subfunction & 0x7F
                identifiers.append({
                    "kind": "Routine ID",
                    "identifier": routine_id,
                    "label": f"Routine 0x{routine_id:04X}",
                    "access": "Routine control",
                    "subfunction": raw_subfunction,
                    "routine_control_type": control_type,
                    "routine_control_name": {
                        0x01: "StartRoutine",
                        0x02: "StopRoutine",
                        0x03: "RequestRoutineResults",
                    }.get(control_type, "Unrecognized routine-control type"),
                })
            else:
                continue

            capture_names = set(transaction.get("capture_names") or [])
            response_kind = str(transaction.get("response_kind") or "unknown")
            for identifier in identifiers:
                key = (
                    operation_name, identifier["kind"], identifier["identifier"],
                    identifier["access"], identifier["subfunction"],
                )
                item = aggregates.setdefault(key, {
                    "operation": operation_name,
                    **identifier,
                    "capture_names": set(),
                    "positive_count": 0,
                    "negative_count": 0,
                    "unknown_count": 0,
                    "request_count": 0,
                    "response_examples": set(),
                })
                item["capture_names"].update(capture_names)
                item["request_count"] += int(transaction.get("count", 1))
                if response_kind == "positive":
                    item["positive_count"] += int(transaction.get("count", 1))
                elif response_kind == "negative":
                    item["negative_count"] += int(transaction.get("count", 1))
                else:
                    item["unknown_count"] += int(transaction.get("count", 1))
                if response:
                    item["response_examples"].add(response.hex())

    results = []
    for item in aggregates.values():
        item["capture_names"] = sorted(item["capture_names"])
        item["capture_count"] = len(item["capture_names"])
        item["response_examples"] = sorted(item["response_examples"])
        item["repeatability"] = (
            "Seen in multiple captures" if item["capture_count"] >= 2
            else "Seen in one capture only"
        )
        results.append(item)
    results.sort(key=lambda item: (
        item["operation"].casefold(), item["kind"], item["identifier"],
        item["access"],
        item["subfunction"] if item["subfunction"] is not None else -1,
    ))
    return results


def summarize_operation_did_response_variation(operation_summaries):
    """Compare raw positive 0x22 DID data across captures without decoding it.

    Multi-DID responses are intentionally skipped because variable-length DID
    records cannot be split reliably without a vehicle-specific data definition.
    """
    aggregates = {}
    for operation in operation_summaries or []:
        operation_name = str(operation.get("operation") or "Unspecified")
        for transaction in operation.get("transactions") or []:
            try:
                service = int(transaction["service"])
                request = bytes.fromhex(transaction.get("request_payload", ""))
                response = bytes.fromhex(transaction.get("response_payload", ""))
            except (KeyError, TypeError, ValueError):
                continue
            if service != 0x22 or len(request) != 3 or request[0] != 0x22:
                continue
            if transaction.get("response_kind") != "positive":
                continue
            did = int.from_bytes(request[1:3], "big")
            if len(response) < 3 or response[:3] != bytes((0x62,)) + request[1:3]:
                continue
            value = response[3:]
            key = (operation_name, did)
            item = aggregates.setdefault(key, {
                "operation": operation_name,
                "did": did,
                "label": f"DID 0x{did:04X}",
                "capture_names": set(),
                "value_counts": {},
                "value_lengths": set(),
                "total_count": 0,
            })
            count = int(transaction.get("count", 1))
            item["capture_names"].update(transaction.get("capture_names") or [])
            item["value_counts"][value.hex()] = (
                item["value_counts"].get(value.hex(), 0) + count
            )
            item["value_lengths"].add(len(value))
            item["total_count"] += count

    results = []
    for item in aggregates.values():
        values = sorted(item["value_counts"])
        decoded = [bytes.fromhex(value) for value in values]
        common_lengths = {len(value) for value in decoded}
        variable_offsets = []
        if len(common_lengths) == 1 and decoded:
            width = len(decoded[0])
            variable_offsets = [
                offset for offset in range(width)
                if len({value[offset] for value in decoded}) > 1
            ]
        item["capture_names"] = sorted(item["capture_names"])
        item["capture_count"] = len(item["capture_names"])
        item["distinct_value_count"] = len(values)
        item["value_lengths"] = sorted(item["value_lengths"])
        item["value_examples"] = values[:8]
        item["variable_byte_offsets"] = variable_offsets
        item["data_pattern"] = (
            "Same data in all observed responses"
            if len(values) == 1 and item["total_count"] > 1
            else "Single observed value"
            if len(values) == 1
            else "Variable-length data"
            if len(common_lengths) > 1
            else "Byte values vary"
            if variable_offsets
            else "Distinct values; comparison unavailable"
        )
        results.append(item)
    results.sort(key=lambda item: (item["operation"].casefold(), item["did"]))
    return results

def _frame_record(frame):
    return {
        "timestamp": float(getattr(frame, "timestamp", 0.0) or 0.0),
        "timestamp_clock": "host_monotonic",
        "device_timestamp_us": getattr(frame, "device_timestamp_us", None),
        "arbitration_id": int(frame.arbitration_id),
        "extended": bool(frame.is_extended_id),
        "data": bytes(frame.data).hex(),
        "channel": getattr(frame, "channel", None),
    }


def _normalize_record(record):
    if not isinstance(record, dict):
        return None
    try:
        arbitration_id = record.get("arbitration_id", record.get("can_id", record.get("id")))
        if isinstance(arbitration_id, str):
            arbitration_id = int(arbitration_id.strip().lower().replace("0x", ""), 16)
        else:
            arbitration_id = int(arbitration_id)
        raw = record.get("data", record.get("payload", ""))
        if isinstance(raw, list):
            payload = bytes(int(x) for x in raw)
        elif isinstance(raw, bytes):
            payload = raw
        else:
            text = str(raw).replace(" ", "").replace("-", "")
            if text.lower().startswith("0x"):
                text = text[2:]
            payload = bytes.fromhex(text)
        extended_value = record.get("extended", record.get("is_extended_id", arbitration_id > 0x7FF))
        if isinstance(extended_value, str):
            extended = extended_value.strip().lower() in ("1", "true", "yes", "ext", "extended")
        else:
            extended = bool(extended_value)
        normalized = {
            "timestamp": float(record.get("timestamp", record.get("time", 0.0)) or 0.0),
            "arbitration_id": arbitration_id,
            "extended": extended,
            "data": payload.hex(),
            "channel": record.get("channel"),
            "timestamp_clock": record.get("timestamp_clock", "unknown"),
        }
        if record.get("device_timestamp_us") is not None:
            try:
                device_timestamp_us = int(record["device_timestamp_us"])
                if device_timestamp_us >= 0:
                    normalized["device_timestamp_us"] = device_timestamp_us
            except (TypeError, ValueError):
                pass
        if record.get("elapsed_seconds") is not None:
            try:
                normalized["elapsed_seconds"] = float(record["elapsed_seconds"])
            except (TypeError, ValueError):
                # Preserve the valid CAN frame even if optional timing metadata is bad.
                pass
        return normalized
    except (TypeError, ValueError):
        return None


def load_capture_file(path):
    """Load FreeRov3r JSON, JSONL, CSV, or common candump text captures."""
    path = Path(path)
    suffix = path.suffix.lower()
    metadata = {}
    records = []

    if suffix in (".json", ".jsonl", ".ndjson"):
        text = path.read_text(encoding="utf-8-sig")
        if suffix == ".json":
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                metadata = dict(parsed.get("metadata", {}))
                metadata["bookmarks"] = parsed.get("bookmarks", {})
                metadata["markers"] = parsed.get("markers", [])
                source = parsed.get("frames", [])
            else:
                source = parsed
            records = [_normalize_record(x) for x in source]
        else:
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("record_type") == "metadata":
                    metadata = item.get("metadata", {})
                else:
                    records.append(_normalize_record(item))
    elif suffix == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                records.append(_normalize_record(row))
    else:
        # candump: (channel timestamp) CAN_ID#DATA or CAN_ID##FLAGS+DATA
        pattern = re.compile(r"^\s*(?:\((?P<time>\d+(?:\.\d+)?)\)\s+)?(?:\S+\s+)?(?P<id>[0-9A-Fa-f]+)(?P<sep>##|#)(?P<data>[0-9A-Fa-f]*)")
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            match = pattern.match(line)
            if not match:
                continue
            can_id = int(match.group("id"), 16)
            data = match.group("data")
            if match.group("sep") == "##":
                data = data[1:] if data else ""
            try:
                records.append(_normalize_record({
                    "timestamp": match.group("time") or 0,
                    "arbitration_id": can_id,
                    "extended": can_id > 0x7FF,
                    "data": data,
                }))
            except ValueError:
                continue

    return metadata, [x for x in records if x is not None]


class ResearchTab(QWidget):
    """Local-only protocol capture, annotation, comparison and REA handoff."""

    MAX_DISPLAY_ROWS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.live_preview = []
        self.reference_frames = []
        self.reference_metadata = {}
        self.sequence_captures = []
        self.bookmarks = {}
        self.markers = []
        self.metadata = {}
        self._recording_started_monotonic = None
        self.recording = False
        self.live_enabled = True
        self._pending_records = []
        self._pending_preview = []
        self.dbc_library = DBCLibrary()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._flush_pending_frames)
        self.refresh_timer.start()

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 6, 7, 6)
        root.setSpacing(5)
        self.setStyleSheet(self.styleSheet() + """
            ResearchTab { font-size: 8pt; }
            ResearchTab QGroupBox { font-size: 8pt; font-weight: 700; margin-top: 5px; padding-top: 4px; }
            ResearchTab QGroupBox::title { subcontrol-origin: margin; left: 7px; padding: 0 3px; }
            ResearchTab QLabel, ResearchTab QCheckBox { font-size: 8pt; }
            ResearchTab QPushButton, ResearchTab QLineEdit, ResearchTab QComboBox {
                font-size: 8pt; min-height: 23px; padding: 2px 6px;
            }
            ResearchTab QPlainTextEdit { font-size: 8pt; padding: 3px; }
            ResearchTab QTableWidget { font-size: 8pt; }
            ResearchTab QHeaderView::section { font-size: 8pt; padding: 3px 4px; }
        """)

        self.status_label = QLabel(
            "PASSIVE RESEARCH: incoming frames only. This workspace does not transmit or replay CAN traffic."
        )
        self.status_label.setWordWrap(False)
        root.addWidget(self.status_label)

        health_layout = QGridLayout()
        health_layout.setContentsMargins(0, 0, 0, 0)
        health_layout.setHorizontalSpacing(8)
        health_layout.setVerticalSpacing(2)
        self.receiver_connection_label = QLabel("Connection: not selected")
        self.receiver_frame_label = QLabel("Frames: 0")
        self.receiver_activity_label = QLabel("Last frame: never")
        self.receiver_alert_label = QLabel("Alerts / errors: 0 / 0")
        self.receiver_status_label = QLabel("Firmware: no status received")
        self.timestamp_health_label = QLabel(
            "Timing: no device timestamps yet; ESP32 clocks are independent."
        )
        for column, label in enumerate((
            self.receiver_connection_label, self.receiver_frame_label,
            self.receiver_activity_label, self.receiver_alert_label,
            self.receiver_status_label,
        )):
            label.setMinimumWidth(0)
            health_layout.addWidget(label, 0, column)
        self.timestamp_health_label.setWordWrap(True)
        health_layout.addWidget(self.timestamp_health_label, 1, 0, 1, 5)
        root.addLayout(health_layout)

        session_box = QGroupBox("SESSION")
        session_form = QGridLayout(session_box)
        session_form.setContentsMargins(6, 8, 6, 5)
        session_form.setHorizontalSpacing(6)
        session_form.setVerticalSpacing(3)
        self.session_name = QLineEdit("LAUNCH Creader Elite V2.0 capture")
        self.operation = QComboBox()
        self.operation.addItems([
            "Vehicle connection / identification",
            "Full module scan",
            "Read ECU information",
            "Read DTCs",
            "Clear DTCs",
            "Live data",
            "Read configuration / CCF",
            "Service routine / active test",
            "Coding / configuration inspection",
            "Other / unknown",
        ])
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("What are you doing on the LAUNCH scanner?")
        self.vin_label = QLabel("VIN: not set")
        self.did_vehicle_key = QLineEdit("Land Rover L319 5.0 petrol")
        self.did_vehicle_key.setPlaceholderText("Exact vehicle key from the DID definition file")
        session_form.addWidget(QLabel("Session"), 0, 0)
        session_form.addWidget(self.session_name, 0, 1)
        session_form.addWidget(QLabel("Operation"), 0, 2)
        session_form.addWidget(self.operation, 0, 3)
        session_form.addWidget(QLabel("Notes"), 1, 0)
        session_form.addWidget(self.notes, 1, 1)
        session_form.addWidget(QLabel("VIN"), 1, 2)
        session_form.addWidget(self.vin_label, 1, 3)
        session_form.addWidget(QLabel("DID vehicle key"), 2, 0)
        session_form.addWidget(self.did_vehicle_key, 2, 1, 1, 3)
        session_form.setColumnStretch(1, 2)
        session_form.setColumnStretch(3, 2)
        root.addWidget(session_box)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(5)
        controls.setVerticalSpacing(3)
        self.live_check = QCheckBox("Show incoming live frames")
        self.live_check.setChecked(True)
        self.live_check.toggled.connect(self._set_live_enabled)
        controls.addWidget(self.live_check, 0, 0)
        self.record_button = QPushButton("Start recording")
        self.record_button.clicked.connect(self.toggle_recording)
        controls.addWidget(self.record_button, 0, 1)
        self.marker_button = QPushButton("Mark action")
        self.marker_button.clicked.connect(self.mark_action)
        controls.addWidget(self.marker_button, 0, 2)
        self.import_button = QPushButton("Import capture")
        self.import_button.clicked.connect(self.import_capture)
        controls.addWidget(self.import_button, 0, 3)
        self.reference_button = QPushButton("Load comparison")
        self.reference_button.clicked.connect(self.load_reference)
        controls.addWidget(self.reference_button, 0, 4)
        self.sequence_load_button = QPushButton("Load sequences")
        self.sequence_load_button.clicked.connect(self.load_sequence_captures)
        controls.addWidget(self.sequence_load_button, 0, 5)
        self.save_button = QPushButton("Save session")
        self.save_button.clicked.connect(self.save_session)
        controls.addWidget(self.save_button, 0, 6)
        for column in range(1, 7):
            controls.setColumnStretch(column, 1)
        root.addLayout(controls)

        dbc_controls = QHBoxLayout()
        self.load_dbc_button = QPushButton("Load DBC")
        self.load_dbc_button.setToolTip("Import a local DBC for passive CAN signal decoding. No frames are transmitted.")
        self.load_dbc_button.clicked.connect(self.load_dbc)
        dbc_controls.addWidget(self.load_dbc_button)
        self.dbc_evidence_button = QPushButton("DBC Evidence")
        self.dbc_evidence_button.setToolTip("Record the source, target vehicle, physical bus and evidence grade for the loaded DBC.")
        self.dbc_evidence_button.clicked.connect(self.edit_dbc_evidence)
        dbc_controls.addWidget(self.dbc_evidence_button)
        self.inspect_dbc_button = QPushButton("Inspect DBC")
        self.inspect_dbc_button.clicked.connect(self.inspect_dbc)
        dbc_controls.addWidget(self.inspect_dbc_button)
        self.compare_dbc_button = QPushButton("Compare DBCs")
        self.compare_dbc_button.clicked.connect(self.compare_dbcs)
        dbc_controls.addWidget(self.compare_dbc_button)
        self.dbc_audit_button = QPushButton("Audit capture vs DBC")
        self.dbc_audit_button.setToolTip("Measure passive capture coverage against the loaded DBC; unmatched frames are not automatically faults.")
        self.dbc_audit_button.clicked.connect(self.audit_capture_against_dbc)
        dbc_controls.addWidget(self.dbc_audit_button)
        self.dbc_signal_behavior_button = QPushButton("Analyze DBC signals")
        self.dbc_signal_behavior_button.setToolTip("Summarize decoded signal values and capture-relative behavior. Passive only.")
        self.dbc_signal_behavior_button.clicked.connect(self.analyze_dbc_signal_behavior)
        dbc_controls.addWidget(self.dbc_signal_behavior_button)
        self.dbc_signal_graph_button = QPushButton("Graph DBC signals")
        self.dbc_signal_graph_button.setToolTip(
            "Plot selected decoded signals against capture-relative time and overlay scanner action markers. Passive only."
        )
        self.dbc_signal_graph_button.clicked.connect(self.graph_dbc_signals)
        dbc_controls.addWidget(self.dbc_signal_graph_button)
        dbc_controls.setContentsMargins(0, 0, 0, 0)
        dbc_controls.setSpacing(5)
        root.addLayout(dbc_controls)
        self.dbc_status = QLabel("DBC: none loaded. Install optional protocols support to decode imported DBC files.")
        self.dbc_status.setWordWrap(False)
        if self.dbc_library.path is not None:
            self.dbc_status.setText(
                f"DBC: {self.dbc_library.path.name} | {self.dbc_library.message_count} messages | "
                f"{self.dbc_library.signal_count} signals | restored from local library | "
                f"Status: {self.dbc_library.metadata.get('verification_status', 'unverified')}"
            )
        root.addWidget(self.dbc_status)

        filters = QHBoxLayout()
        self.id_filter = QLineEdit()
        self.id_filter.setPlaceholderText("CAN ID filter (e.g. 7E0 or 7E0-7E8)")
        self.id_filter.textChanged.connect(self.refresh_table)
        self.payload_filter = QLineEdit()
        self.payload_filter.setPlaceholderText("Payload hex filter")
        self.payload_filter.textChanged.connect(self.refresh_table)
        self.protocol_filter = QComboBox()
        self.protocol_filter.addItems(["All frames", "ISO-TP", "UDS classified"])
        self.protocol_filter.currentTextChanged.connect(self.refresh_table)
        filters.addWidget(self.id_filter, 2)
        filters.addWidget(self.payload_filter, 2)
        filters.addWidget(self.protocol_filter, 1)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        self.frame_table = QTableWidget(0, 8)
        self.frame_table.setHorizontalHeaderLabels([
            "Timestamp", "CAN ID", "Format", "DLC", "Payload", "ISO-TP", "UDS hint", "DBC signals"
        ])
        self.frame_table.setAlternatingRowColors(True)
        self.frame_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.frame_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.frame_table.horizontalHeader().setStretchLastSection(True)
        self.frame_table.itemSelectionChanged.connect(self.show_selected_frame)
        splitter.addWidget(self.frame_table)

        lower = QWidget()
        lower_layout = QHBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        details_box = QGroupBox("SELECTED FRAME / ANNOTATION")
        details_layout = QVBoxLayout(details_box)
        self.frame_detail = QPlainTextEdit()
        self.frame_detail.setReadOnly(True)
        self.frame_detail.setMaximumHeight(75)
        self.annotation = QLineEdit()
        self.annotation.setPlaceholderText("Annotation: e.g. immediately after selecting Read ECU Information")
        self.bookmark_button = QPushButton("Bookmark selected frame")
        self.bookmark_button.clicked.connect(self.bookmark_selected)
        details_layout.addWidget(self.frame_detail)
        details_layout.addWidget(self.annotation)
        details_layout.addWidget(self.bookmark_button)
        lower_layout.addWidget(details_box, 1)

        analysis_box = QGroupBox("TRAFFIC SUMMARY / COMPARISON")
        analysis_layout = QVBoxLayout(analysis_box)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(65)
        self.summary.setPlaceholderText("Frame counts, frequent IDs, protocol hints and comparison results appear here.")
        analysis_layout.addWidget(self.summary)
        lower_layout.addWidget(analysis_box, 1)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        footer = QGridLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setHorizontalSpacing(5)
        footer.setVerticalSpacing(3)
        self.isotp_button = QPushButton("Reassemble ISO-TP")
        self.isotp_button.clicked.connect(self.analyze_isotp)
        self.pair_button = QPushButton("Pair UDS transactions")
        self.pair_button.clicked.connect(self.analyze_uds_pairs)
        self.address_map_button = QPushButton("Build CAN address map")
        self.address_map_button.clicked.connect(self.analyze_address_map)
        self.marker_analysis_button = QPushButton("Compare around markers")
        self.marker_analysis_button.clicked.connect(self.analyze_marker_windows)
        self.sequence_analysis_button = QPushButton("Compare operation sequences")
        self.sequence_analysis_button.clicked.connect(self.analyze_operation_sequences)
        self.did_decode_button = QPushButton("Decode DID responses")
        self.did_decode_button.clicked.connect(self.decode_did_responses)
        self.module_inventory_button = QPushButton("Compare module inventory")
        self.module_inventory_button.clicked.connect(self.analyze_module_inventory)
        self.can_timing_button = QPushButton("Analyze CAN timing")
        self.can_timing_button.setToolTip("Measure observed inter-frame intervals from captured timestamps; no CAN traffic is transmitted.")
        self.can_timing_button.clicked.connect(self.analyze_can_timing)
        self.payload_variability_button = QPushButton("Analyze payload bits")
        self.payload_variability_button.setToolTip("Show observed byte and bit changes by CAN ID; no signal meanings are guessed.")
        self.payload_variability_button.clicked.connect(self.analyze_payload_variability)
        self.packet_button = QPushButton("Copy REA analysis packet")
        self.packet_button.clicked.connect(self.copy_analysis_packet)
        self.clear_button = QPushButton("Clear research data")
        self.clear_button.clicked.connect(self.clear_data)
        footer_buttons = (
            self.isotp_button, self.pair_button, self.address_map_button,
            self.marker_analysis_button, self.sequence_analysis_button,
            self.did_decode_button, self.module_inventory_button,
            self.can_timing_button, self.payload_variability_button,
            self.packet_button, self.clear_button,
        )
        for index, button in enumerate(footer_buttons):
            button.setToolTip(button.text())
            footer.addWidget(button, index // 4, index % 4)
            footer.setColumnStretch(index % 4, 1)
        self.count_label = QLabel("0 displayed · 0 recorded")
        footer.addWidget(self.count_label, 3, 0, 1, 4)
        root.addLayout(footer)

    def set_receiver_diagnostics(self, diagnostics=None):
        """Refresh the receiver-health strip from an adapter diagnostics snapshot."""
        data = diagnostics or {}
        channels = data.get("channels") or []
        if channels:
            channel_states = " | ".join(
                f"{item.get('channel', 'CAN')}: {item.get('receiver_state', 'unknown')} "
                f"({item.get('port') or 'no port'})"
                for item in channels
            )
            self.receiver_connection_label.setText(
                f"Receivers: {channel_states} · {data.get('mode', 'dual receive-only')}"
            )
            self.receiver_frame_label.setText(
                f"Combined frames: {int(data.get('frames_received', 0)):,} · "
                f"invalid lines: {int(data.get('invalid_lines', 0)):,}"
            )
            activity = []
            for item in channels:
                age = item.get("last_frame_age_seconds")
                label = "never" if age is None else f"{float(age):.1f}s ago"
                activity.append(f"{item.get('channel', 'CAN')}: {label}")
            self.receiver_activity_label.setText("Last frames: " + " | ".join(activity))
            self.receiver_alert_label.setText(
                f"Alerts / firmware errors: {int(data.get('alert_count', 0)):,} / "
                f"{int(data.get('firmware_error_count', 0)):,}"
            )
            errors = [
                f"{item.get('channel', 'CAN')}: {item['last_error']}"
                for item in channels if item.get("last_error")
            ]
            self.receiver_status_label.setText(
                "Receiver errors: " + " | ".join(errors) if errors
                else "Firmware: per-channel status available"
            )
            return

        connected = bool(data.get("connected", False))
        port = data.get("port") or "not selected"
        mode = data.get("mode") or "unknown mode"
        receiver_state = data.get("receiver_state")
        if not receiver_state:
            receiver_state = "connected" if connected else "disconnected"
        self.receiver_connection_label.setText(
            f"Receiver: {receiver_state} · {port} · {mode}"
        )
        self.receiver_frame_label.setText(
            f"Frames: {int(data.get('frames_received', 0)):,} · invalid lines: "
            f"{int(data.get('invalid_lines', 0)):,}"
        )
        age = data.get("last_frame_age_seconds")
        activity = "never" if age is None else f"{float(age):.1f}s ago"
        self.receiver_activity_label.setText(f"Last frame: {activity}")
        self.receiver_alert_label.setText(
            f"Alerts / firmware errors: {int(data.get('alert_count', 0)):,} / "
            f"{int(data.get('firmware_error_count', 0)):,}"
        )
        status = data.get("last_status") or "no status received"
        error = data.get("last_error")
        if error:
            status = f"ERROR: {error}"
        self.receiver_status_label.setText(f"Firmware: {status}")

    def set_context(self, vin=None, interface=None):
        self.vin_label.setText(f"VIN: {vin or 'not set'}  |  Interface: {interface or 'not connected'}")
        self.metadata.update({
            "vin": vin,
            "interface": interface,
            "scanner": "LAUNCH Creader Elite V2.0 for Land Rover/Jaguar",
        })

    def _set_live_enabled(self, enabled):
        self.live_enabled = bool(enabled)

    def toggle_recording(self):
        if not self.recording:
            self.recording = True
            self.markers.clear()
            self._recording_started_monotonic = time.monotonic()
            self.metadata.update({
                "session_name": self.session_name.text().strip() or "Unnamed research session",
                "operation": self.operation.currentText(),
                "notes": self.notes.text().strip(),
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "vin": self.metadata.get("vin"),
                "interface": self.metadata.get("interface"),
            })
            self.record_button.setText("Stop research recording")
            self.status_label.setText("RECORDING · Stores frames delivered by the main listener. This tab does not transmit or replay frames.")
        else:
            self.recording = False
            self.metadata["stopped_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self.record_button.setText("Start research recording")
            self.status_label.setText("Recording stopped. Save the session or copy its REA analysis packet.")


    def mark_action(self):
        if not self.recording or self._recording_started_monotonic is None:
            QMessageBox.information(
                self, "Operation marker", "Start research recording before marking a scanner action."
            )
            return
        marker = {
            "elapsed_seconds": round(time.monotonic() - self._recording_started_monotonic, 3),
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "operation": self.operation.currentText(),
            "note": self.notes.text().strip(),
        }
        self.markers.append(marker)
        self.status_label.setText(
            f'Marker {len(self.markers)} added at {marker["elapsed_seconds"]:.3f}s: {marker["operation"]}'
        )
        self._update_summary()

    def observe_frame(self, frame):
        record = _frame_record(frame)
        if self.recording:
            if self._recording_started_monotonic is not None:
                record["elapsed_seconds"] = round(time.monotonic() - self._recording_started_monotonic, 6)
            self._pending_records.append(record)
        elif self.live_enabled:
            self._pending_preview.append(record)

    def _flush_pending_frames(self):
        changed = False
        if self._pending_records:
            self.frames.extend(self._pending_records)
            self._pending_records.clear()
            if len(self.frames) > 100000:
                self.frames = self.frames[-100000:]
            changed = True
        if self._pending_preview:
            self.live_preview.extend(self._pending_preview)
            self._pending_preview.clear()
            if len(self.live_preview) > 5000:
                self.live_preview = self.live_preview[-5000:]
            changed = True
        if changed:
            self.refresh_table()

    def _visible_records(self):
        return self.frames if self.frames else self.live_preview

    def _filtered_records(self):
        id_text = self.id_filter.text().strip().lower().replace("0x", "")
        payload_text = self.payload_filter.text().strip().lower().replace(" ", "").replace("0x", "")
        protocol = self.protocol_filter.currentText()
        output = []
        for record in self._visible_records():
            can_id = int(record["arbitration_id"])
            payload = bytes.fromhex(record["data"])
            iso, uds = classify_can_payload(payload)
            if id_text:
                try:
                    if "-" in id_text:
                        low, high = (int(x.strip(), 16) for x in id_text.split("-", 1))
                        if not min(low, high) <= can_id <= max(low, high):
                            continue
                    elif can_id != int(id_text, 16):
                        continue
                except ValueError:
                    continue
            if payload_text and payload_text not in payload.hex():
                continue
            if protocol == "ISO-TP" and not iso.startswith("ISO-TP"):
                continue
            if protocol == "UDS classified" and not (
                "UDS" in uds or uds in UDS_SERVICES.values()
                or uds.startswith("Negative response") or uds.startswith("Positive response")
            ):
                continue
            output.append((record, iso, uds))
        return output

    def refresh_table(self):
        if not hasattr(self, "frame_table"):
            return
        rows = self._filtered_records()
        rows = rows[-self.MAX_DISPLAY_ROWS:]
        self.frame_table.setUpdatesEnabled(False)
        self.frame_table.setRowCount(len(rows))
        for row, (record, iso, uds) in enumerate(rows):
            payload = bytes.fromhex(record["data"])
            values = [
                f'{record["timestamp"]:.6f}',
                f'{record["arbitration_id"]:08X}',
                "EXT" if record["extended"] else "STD",
                str(len(payload)),
                payload.hex(" ").upper(),
                iso,
                uds,
                self._decode_dbc_record(record),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (0, 1, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.frame_table.setItem(row, col, item)
        self.frame_table.setUpdatesEnabled(True)
        source_count = len(self.frames) if self.frames else len(self.live_preview)
        source_label = "recorded/imported" if self.frames else "live preview"
        self.count_label.setText(f"{len(rows):,} displayed · {source_count:,} {source_label}")
        self._update_summary()
        self._update_timestamp_health()

    def _update_timestamp_health(self):
        if not hasattr(self, "timestamp_health_label"):
            return
        records = (self.frames if self.frames else self.live_preview)[-10000:]
        if not records:
            self.timestamp_health_label.setText(
                "No device timestamps observed yet. Host monotonic time remains the shared timeline."
            )
            return
        report = analyze_channel_timestamps(records)
        if not report["channels"] or not any(
            item["timed_frame_count"] for item in report["channels"]
        ):
            self.timestamp_health_label.setText(
                f"{report['frame_count']:,} frames; no valid ESP32 device timestamps. "
                "Older firmware/capture formats remain supported. Live health uses the most recent 10,000 frames."
            )
            return
        summaries = []
        for item in report["channels"]:
            fit = item["clock_fit"]
            drift = f"{fit['drift_ppm']:+.1f} ppm" if fit else "drift unavailable"
            jitter = f"{fit['residual_p95_ms']:.3f} ms p95 residual" if fit else "jitter unavailable"
            summaries.append(
                f"{item['channel']}: {item['timed_frame_count']}/{item['frame_count']} timed, "
                f"{drift}, {jitter}, non-monotonic {item['non_monotonic_device_steps']}, "
                f"gaps {item['suspicious_device_gaps']}"
            )
        self.timestamp_health_label.setText(
            " | ".join(summaries)
            + " | ESP32 clocks are independent; residuals are timing consistency estimates, "
              "not absolute transport latency. Live health uses the most recent 10,000 frames."
        )

    def show_selected_frame(self):
        row = self.frame_table.currentRow()
        if row < 0:
            self.frame_detail.clear()
            return
        visible = self._filtered_records()[-self.MAX_DISPLAY_ROWS:]
        if row >= len(visible):
            return
        record, iso, uds = visible[row]
        self.frame_detail.setPlainText(
            f'CAN ID: 0x{record["arbitration_id"]:X}  |  '
            f'{"Extended" if record["extended"] else "Standard"}  |  '
            f'Timestamp: {record["timestamp"]:.6f}\n'
            f'Payload: {record["data"].upper()}\nISO-TP: {iso}\nUDS hint: {uds}\n'
            f'Channel: {record.get("channel") or "unknown"}\n'
            f'DBC decode: {self._decode_dbc_record(record) or "no matching loaded definition"}'
        )
        key = f'{record["timestamp"]:.6f}|{record["arbitration_id"]:X}|{record["data"]}'
        self.annotation.setText(self.bookmarks.get(key, ""))

    def bookmark_selected(self):
        row = self.frame_table.currentRow()
        visible = self._filtered_records()[-self.MAX_DISPLAY_ROWS:]
        if row < 0 or row >= len(visible):
            QMessageBox.information(self, "Research annotation", "Select a frame first.")
            return
        record = visible[row][0]
        key = f'{record["timestamp"]:.6f}|{record["arbitration_id"]:X}|{record["data"]}'
        self.bookmarks[key] = self.annotation.text().strip()
        self._update_summary()

    def _decode_dbc_record(self, record):
        result = self.dbc_library.decode(
            record["arbitration_id"], bytes.fromhex(record["data"]), record["extended"]
        )
        if result is None:
            return ""
        return "; ".join(
            f"{name}={value} {result.units.get(name, '')}".rstrip()
            for name, value in result.decoded.items()
        )

    def load_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load CAN DBC definition", str(self.dbc_library.library_dir), "DBC files (*.dbc)"
        )
        if not path:
            return
        try:
            summary = self.dbc_library.import_file(path)
        except DBCUnavailableError as exc:
            QMessageBox.warning(self, "DBC support unavailable", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "DBC import failed", str(exc))
            return
        self.dbc_status.setText(
            f"DBC: {summary['name']} | {summary['message_count']} messages | "
            f"{summary['signal_count']} signals | local copy: {summary['path']} "
            f"| Source: {summary['metadata'].get('source_file', 'unknown')} "
            f"| Status: {summary['metadata'].get('verification_status', 'unverified')} "
            f"| Parse: {summary['metadata'].get('validation_mode', 'unknown')} "
            "| Unverified until matched to this vehicle."
        )
        self.refresh_table()

    def edit_dbc_evidence(self):
        if self.dbc_library.database is None:
            QMessageBox.information(self, "DBC evidence", "Load a DBC definition first.")
            return
        metadata = self.dbc_library.metadata
        dialog = QDialog(self)
        dialog.setWindowTitle("DBC source and vehicle evidence")
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        source = QLineEdit(metadata.get("source_origin", ""))
        source.setPlaceholderText("Source URL, repository path or documentation reference")
        vehicle = QLineEdit(metadata.get("vehicle_applicability", ""))
        vehicle.setPlaceholderText("Year, model, engine, market and generation")
        bus = QLineEdit(metadata.get("bus_name", ""))
        bus.setPlaceholderText("Physical network / bus, if known")
        grade = QComboBox()
        for value, label in (
            ("A", "A · Captured and independently checked"),
            ("B", "B · Exact vehicle source, capture-consistent"),
            ("C", "C · Related platform or incomplete source"),
            ("D", "D · Generic / unknown provenance"),
        ):
            grade.addItem(label, value)
        grade.setCurrentIndex(max(0, grade.findData(metadata.get("evidence_grade", "D"))))
        status = QComboBox()
        for value, label in (
            ("unverified", "Unverified"),
            ("provisional", "Provisional candidate"),
            ("verified", "Verified"),
        ):
            status.addItem(label, value)
        status.setCurrentIndex(max(0, status.findData(metadata.get("verification_status", "unverified"))))
        notes = QPlainTextEdit()
        notes.setPlainText(metadata.get("verification_notes", ""))
        notes.setPlaceholderText(
            "Record capture conditions, known physical values, controlled state changes "
            "and the independent cross-check used."
        )
        form.addRow("Source reference", source)
        form.addRow("Vehicle applicability", vehicle)
        form.addRow("Physical bus / network", bus)
        form.addRow("Evidence grade", grade)
        form.addRow("Verification status", status)
        form.addRow("Evidence / cross-check notes", notes)
        layout.addLayout(form)
        guidance = QLabel(
            "Verified is restricted to grade A evidence with a source, exact vehicle, "
            "physical bus and documented known-value cross-check."
        )
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Save evidence")
        save.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            metadata = self.dbc_library.update_metadata(
                source_origin=source.text(),
                vehicle_applicability=vehicle.text(),
                bus_name=bus.text(),
                evidence_grade=grade.currentData(),
                verification_status=status.currentData(),
                verification_notes=notes.toPlainText(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "DBC evidence not saved", str(exc))
            return
        self.dbc_status.setText(
            f"DBC: {self.dbc_library.path.name} | {self.dbc_library.message_count} messages | "
            f"{self.dbc_library.signal_count} signals | Grade {metadata['evidence_grade']} | "
            f"Status: {metadata['verification_status']} | "
            f"Vehicle: {metadata['vehicle_applicability']}"
        )
        self._update_summary()

    def inspect_dbc(self):
        if self.dbc_library.database is None:
            QMessageBox.information(self, "Inspect DBC", "Load a DBC definition first.")
            return
        rows = self.dbc_library.catalog()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"DBC catalog · {self.dbc_library.path.name}")
        dialog.resize(1180, 620)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Raw definition inventory only. Start bit conventions, scaling and applicability "
            "must be checked against the target vehicle and capture."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        columns = [
            ("CAN ID", "frame_id"), ("Fmt", "format"), ("Message", "message"),
            ("DLC", "length"), ("Signal", "signal"), ("Start", "start_bit"),
            ("Bits", "bit_length"), ("Byte order", "byte_order"), ("Signed", "signed"),
            ("Factor", "factor"), ("Offset", "offset"), ("Unit", "unit"),
            ("Min", "minimum"), ("Max", "maximum"), ("Mux", "multiplexer"),
            ("Mux signal", "multiplexer_signal"), ("Mux IDs", "multiplexer_ids"),
            ("Choices", "choices"),
        ]
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels([label for label, _ in columns])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSortingEnabled(True)
        for row_index, record in enumerate(rows):
            for column_index, (_, key) in enumerate(columns):
                value = record.get(key, "")
                if key == "frame_id":
                    value = f"0x{int(value):X}"
                elif value is None:
                    value = ""
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def audit_capture_against_dbc(self):
        """Show how much of the current passive capture matches the loaded DBC."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(
                self, "DBC capture audit", "Capture or import CAN frames first."
            )
            return
        report = audit_dbc_capture(self.dbc_library, dataset)
        dialog = QDialog(self)
        dialog.setWindowTitle("Passive capture vs DBC audit")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        summary = QPlainTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(json.dumps(report, indent=2))
        layout.addWidget(summary, 1)
        note = QLabel(
            "A match means only that the frame ID, format, payload length and decoder "
            "matched this DBC. It does not verify vehicle applicability, bus assignment, "
            "signal meaning or DBC correctness. Unmatched frames are not automatically faults. "
            "No CAN traffic is transmitted."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        rate = report.get("coverage_percent")
        coverage_text = "n/a" if rate is None else f"{rate:.1f}%"
        self.status_label.setText(
            f"DBC audit: {report['matched_frames']:,}/{report['input_frame_count']:,} "
            f"frames matched ({coverage_text})"
        )

    def analyze_dbc_signal_behavior(self):
        """Show descriptive value and timing behavior for DBC-decoded signals."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(
                self, "DBC signal behavior", "Capture or import CAN frames first."
            )
            return
        if self.dbc_library.database is None:
            QMessageBox.information(
                self, "DBC signal behavior", "Load a DBC definition first."
            )
            return
        report = analyze_dbc_signal_behavior(self.dbc_library, dataset)
        dialog = QDialog(self)
        dialog.setWindowTitle("Passive DBC signal behavior")
        dialog.resize(1180, 680)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{report['matched_frames']:,} frames decoded | "
            f"{report['signal_count']:,} numeric signals | "
            f"{report['unmatched_frames']:,} unmatched | "
            f"{report['invalid_records']:,} invalid"
        )
        layout.addWidget(summary)
        columns = [
            ("CAN ID", "can_id"), ("Fmt", "format"), ("Channel", "channel"),
            ("Message", "message"), ("Signal", "signal"), ("Unit", "unit"),
            ("Samples", "sample_count"), ("Min", "min"), ("Max", "max"),
            ("Mean", "mean"), ("First", "first"), ("Last", "last"),
            ("Net Δ", "net_change"), ("Changes", "value_change_count"),
            ("Avg Hz", "average_sample_rate_hz"), ("Max |rate|/s", "max_absolute_rate_per_second"),
            ("Dup times", "duplicate_timestamps"), ("Out of order", "out_of_order_timestamps"),
        ]
        table = QTableWidget(len(report["signals"]), len(columns))
        table.setHorizontalHeaderLabels([label for label, _ in columns])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        for row_index, record in enumerate(report["signals"]):
            for column_index, (_, key) in enumerate(columns):
                value = record.get(key)
                if key == "can_id":
                    value = f"0x{int(value):X}"
                elif value is None:
                    value = "n/a"
                elif isinstance(value, float):
                    value = f"{value:.4f}"
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        note = QLabel(
            "Descriptive capture statistics only. Rates use elapsed_seconds when present; "
            "missing timestamps do not remove value samples. Signal meaning, expected behavior, "
            "vehicle applicability and DBC correctness are not independently verified. "
            "No CAN traffic is transmitted."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"DBC signal analysis: {report['signal_count']:,} numeric signals from "
            f"{report['matched_frames']:,} decoded frames"
        )

    def graph_dbc_signals(self):
        """Plot selected passive DBC signal series and scanner-operation markers."""
        if not HAS_RESEARCH_CHARTS:
            QMessageBox.information(
                self, "DBC signal graph",
                "Qt Charts is unavailable in this PySide6 installation. "
                "The numeric DBC analysis remains available.",
            )
            return
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(self, "DBC signal graph", "Capture or import CAN frames first.")
            return
        if self.dbc_library.database is None:
            QMessageBox.information(self, "DBC signal graph", "Load a DBC definition first.")
            return

        graph_data = build_dbc_signal_series(self.dbc_library, dataset, self.markers)
        signals = graph_data["signals"]
        if not signals:
            QMessageBox.information(
                self, "DBC signal graph",
                "No numeric DBC-decoded samples with valid elapsed_seconds timestamps were found.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Passive DBC signal graph")
        dialog.resize(1320, 820)
        outer = QVBoxLayout(dialog)
        header = QLabel(
            f"{len(signals):,} timestamped numeric signal(s) | "
            f"{len(graph_data['markers']):,} scanner action marker(s) | "
            "capture-relative monotonic time"
        )
        outer.addWidget(header)

        body = QHBoxLayout()
        signal_list = QListWidget()
        signal_list.setMinimumWidth(330)
        signal_list.setMaximumWidth(480)
        signal_list.setToolTip(
            "Select one or more signals. Each signal is independently normalized to 0–100% "
            "so different units are not mixed on a misleading shared physical axis."
        )
        for item in signals:
            channel = item["channel"] or "Unknown channel"
            unit = f" {item['unit']}" if item["unit"] else ""
            label = (
                f"{channel} | 0x{item['can_id']:X} {item['format']} | "
                f"{item['message']}.{item['signal']} [{item['minimum']:.4g}.."
                f"{item['maximum']:.4g}{unit}]"
            )
            entry = QListWidgetItem(label)
            entry.setData(Qt.UserRole, item["key"])
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Unchecked)
            signal_list.addItem(entry)
        body.addWidget(signal_list, 1)

        chart = QChart()
        chart.setTitle("DBC signals vs capture time")
        chart.legend().setVisible(True)
        chart.setAnimationOptions(QChart.NoAnimation)
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.Antialiasing)
        chart_view.setRubberBand(QChartView.RectangleRubberBand)
        body.addWidget(chart_view, 4)
        outer.addLayout(body, 1)

        axis_x = QValueAxis()
        axis_x.setTitleText("Elapsed time from recording start (seconds)")
        axis_y = QValueAxis()
        axis_y.setTitleText("Independently normalized signal value (%)")
        axis_y.setRange(0.0, 100.0)
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)

        marker_check = QCheckBox("Overlay scanner action markers")
        marker_check.setChecked(True)
        outer.addWidget(marker_check)
        hint = QLabel(
            "Each signal is scaled independently from its observed minimum to maximum. "
            "Legend entries retain the original unit and range. This is for comparing timing "
            "and shape, not comparing absolute values. Missing timestamps are omitted."
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        def redraw():
            chart.removeAllSeries()
            selected_keys = {
                signal_list.item(i).data(Qt.UserRole)
                for i in range(signal_list.count())
                if signal_list.item(i).checkState() == Qt.Checked
            }
            x_values = []
            for item in signals:
                if item["key"] not in selected_keys:
                    continue
                samples = item["samples"]
                if not samples:
                    continue
                minimum, maximum = item["minimum"], item["maximum"]
                span = maximum - minimum
                line = QLineSeries()
                unit = f" {item['unit']}" if item["unit"] else ""
                channel = item["channel"] or "Unknown"
                line.setName(
                    f"{channel} 0x{item['can_id']:X} {item['message']}.{item['signal']} "
                    f"({minimum:.4g}..{maximum:.4g}{unit})"
                )
                # Bound rendering cost for large captures while preserving endpoints.
                stride = max(1, (len(samples) + 7999) // 8000)
                chosen = samples[::stride]
                if chosen[-1] != samples[-1]:
                    chosen.append(samples[-1])
                for elapsed, value in chosen:
                    normalized = 50.0 if span == 0 else ((value - minimum) / span) * 100.0
                    line.append(float(elapsed), float(normalized))
                    x_values.append(float(elapsed))
                chart.addSeries(line)
                line.attachAxis(axis_x)
                line.attachAxis(axis_y)

            if marker_check.isChecked():
                for marker in graph_data["markers"]:
                    elapsed = marker["elapsed_seconds"]
                    marker_line = QLineSeries()
                    marker_line.setName(f"Marker {elapsed:.3f}s: {marker['label']}")
                    pen = QPen()
                    pen.setStyle(Qt.DashLine)
                    pen.setWidth(1)
                    marker_line.setPen(pen)
                    marker_line.append(elapsed, 0.0)
                    marker_line.append(elapsed, 100.0)
                    chart.addSeries(marker_line)
                    marker_line.attachAxis(axis_x)
                    marker_line.attachAxis(axis_y)
                    x_values.append(elapsed)

            if x_values:
                left, right = min(x_values), max(x_values)
                if left == right:
                    axis_x.setRange(left - 0.5, right + 0.5)
                else:
                    padding = max((right - left) * 0.02, 0.001)
                    axis_x.setRange(left - padding, right + padding)
            else:
                axis_x.setRange(0.0, 1.0)

        plot_button = QPushButton("Plot selected signals")
        plot_button.clicked.connect(redraw)
        select_all_button = QPushButton("Select all")
        select_all_button.clicked.connect(
            lambda: [signal_list.item(i).setCheckState(Qt.Checked)
                     for i in range(signal_list.count())]
        )
        clear_button = QPushButton("Clear selection")
        clear_button.clicked.connect(
            lambda: [signal_list.item(i).setCheckState(Qt.Unchecked)
                     for i in range(signal_list.count())]
        )
        marker_check.toggled.connect(redraw)
        controls = QHBoxLayout()
        controls.addWidget(select_all_button)
        controls.addWidget(clear_button)
        controls.addWidget(plot_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        controls.addWidget(close_button)
        outer.addLayout(controls)
        # Start with a manageable subset rather than overlaying every decoded signal.
        for index in range(min(6, signal_list.count())):
            signal_list.item(index).setCheckState(Qt.Checked)
        redraw()
        dialog.exec()
        self.status_label.setText(
            f"DBC graph closed: {len(signals):,} timestamped signals available"
        )

    def compare_dbcs(self):
        if self.dbc_library.path is None:
            QMessageBox.information(self, "Compare DBCs", "Load a DBC definition first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select comparison DBC", "", "DBC files (*.dbc)"
        )
        if not path:
            return
        try:
            report = DBCLibrary.compare_files(self.dbc_library.path, path)
        except DBCUnavailableError as exc:
            QMessageBox.warning(self, "DBC support unavailable", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "DBC comparison failed", str(exc))
            return

        lines = [
            f"Reference: {report['left']}",
            f"Candidate: {report['right']}",
            f"Parser mode: {report['left_validation_mode']} / {report['right_validation_mode']}",
            f"Messages: {report['left_message_count']} vs {report['right_message_count']}",
            f"Shared CAN IDs/formats: {report['shared_message_count']}",
            f"Only in reference: {len(report['left_only'])}",
            f"Only in candidate: {len(report['right_only'])}",
            f"Shared messages with definition differences: {len(report['message_differences'])}",
            "",
            "This is a structural comparison only. It does not establish vehicle applicability.",
        ]
        for label, key in (("Reference-only messages", "left_only"), ("Candidate-only messages", "right_only")):
            if report[key]:
                lines += ["", label + ":"]
                lines.extend(
                    f"  0x{item['frame_id']:X} {'EXT' if item['extended'] else 'STD'} {item['name']}"
                    for item in report[key][:20]
                )
        for item in report["message_differences"][:30]:
            lines += [
                "",
                f"0x{item['frame_id']:X} {'EXT' if item['extended'] else 'STD'} "
                f"{item['left_name']} / {item['right_name']}"
            ]
            if item["left_length"] != item["right_length"]:
                lines.append(f"  Payload length: {item['left_length']} vs {item['right_length']}")
            for change in item["signal_differences"][:20]:
                if change["kind"] == "message_name_changed":
                    lines.append(f"  Message name: {change['left']} -> {change['right']}")
                elif change["kind"] == "signal_changed":
                    fields = ", ".join(
                        f"{name}: {values['left']} -> {values['right']}"
                        for name, values in change["fields"].items()
                    )
                    lines.append(f"  Changed {change['signal']}: {fields}")
                elif change["kind"] in ("signal_added", "signal_removed"):
                    lines.append(f"  {change['kind'].replace('_', ' ').title()}: {change['signal']}")
                elif change["kind"] == "message_length":
                    lines.append(f"  Payload length: {change['left']} -> {change['right']}")
        QMessageBox.information(self, "DBC comparison", "\n".join(lines))

    def _update_summary(self):
        if not hasattr(self, "summary"):
            return
        dataset = self._visible_records()
        counts = Counter((r["arbitration_id"], r["extended"]) for r in dataset)
        services = Counter()
        for record in dataset:
            _, hint = classify_can_payload(bytes.fromhex(record["data"]))
            if (hint in UDS_SERVICES.values() or hint.startswith("Negative response")
                    or hint.startswith("Positive response") or hint.startswith("Possible")):
                services[hint] += 1
        lines = [
            f"Recorded frames: {len(self.frames):,}",
            f"Live preview frames: {len(self.live_preview):,}" if not self.frames else "Live preview paused while a recorded/imported set is active.",
            f"Unique CAN IDs: {len(counts):,}",
            f"Bookmarks: {len(self.bookmarks):,}  |  Operation markers: {len(self.markers):,}",
            "",
            "Most frequent CAN IDs:",
        ]
        lines.extend(
            f"  0x{can_id:X}{' EXT' if extended else ''}: {count:,}"
            for (can_id, extended), count in counts.most_common(10)
        )
        lines += ["", "Recognized protocol hints (heuristic only):"]
        lines.extend(f"  {name}: {count:,}" for name, count in services.most_common(12))
        if self.dbc_library.database is not None:
            coverage = self.dbc_library.decode_coverage(dataset[-20000:])
            lines += [
                "",
                f"Loaded DBC: {self.dbc_library.path.name}",
                f"DBC frame matches: {coverage['matched_frames']:,} | unmatched: {coverage['unmatched_frames']:,}",
                "Decoded signal statistics (last 20,000 observed frames):",
            ]
            lines.extend(
                f"  {name}: n={stats['count']} min={stats['min']:.5g} mean={stats['mean']:.5g} max={stats['max']:.5g} {stats.get('unit', '')}"
                for name, stats in sorted(coverage["signals"].items())
            )
        if self.reference_frames:
            current_ids = Counter((r["arbitration_id"], r["extended"]) for r in dataset)
            reference_ids = Counter((r["arbitration_id"], r["extended"]) for r in self.reference_frames)
            changed = sorted(set(current_ids) | set(reference_ids),
                             key=lambda key: abs(current_ids[key] - reference_ids[key]), reverse=True)
            lines += ["", f"Comparison capture: {len(self.reference_frames):,} frames",
                      "Largest CAN-ID count differences (working minus reference):"]
            lines.extend(
                f"  0x{can_id:X}{' EXT' if extended else ''}: "
                f"{current_ids[(can_id, extended)] - reference_ids[(can_id, extended)]:+}"
                for can_id, extended in changed[:12]
            )
            if self.dbc_library.database is not None:
                dbc_comparison = self.dbc_library.compare_captures(
                    dataset[-20000:], self.reference_frames[-20000:]
                )
                lines += [
                    "",
                    "Decoded DBC signal comparison (last 20,000 frames per capture):",
                    f"Working matched/unmatched: {dbc_comparison['working']['matched_frames']:,} / {dbc_comparison['working']['unmatched_frames']:,}",
                    f"Reference matched/unmatched: {dbc_comparison['reference']['matched_frames']:,} / {dbc_comparison['reference']['unmatched_frames']:,}",
                ]
                for item in dbc_comparison["signal_differences"][:20]:
                    if item["status"] == "shared":
                        lines.append(
                            f"  {item['signal']}: working mean={item['working']['mean']:.6g} "
                            f"{item['working']['unit']}; reference mean={item['reference']['mean']:.6g} "
                            f"{item['reference']['unit']}; delta={item['mean_delta']:+.6g}"
                        )
                    else:
                        lines.append(f"  {item['signal']}: {item['status']}")
        self.summary.setPlainText("\n".join(lines))

    def import_capture(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import CAN capture", "", "Capture files (*.json *.jsonl *.ndjson *.csv *.log *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            metadata, records = load_capture_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.frames = records
        self.live_preview.clear()
        self._pending_preview.clear()
        self.metadata = dict(metadata)
        self.bookmarks = self.metadata.pop("bookmarks", {})
        self.markers = self.metadata.pop("markers", [])
        self.metadata["imported_from"] = path
        self.refresh_table()
        self.status_label.setText(f"Imported {len(records):,} frames from {Path(path).name}")

    def load_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load comparison capture", "", "Capture files (*.json *.jsonl *.ndjson *.csv *.log *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            metadata, records = load_capture_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Comparison load failed", str(exc))
            return
        self.reference_frames = records
        self.reference_metadata = dict(metadata)
        self.reference_metadata["imported_from"] = path
        self.refresh_table()
        self.status_label.setText(f"Comparison reference loaded: {Path(path).name} ({len(records):,} frames)")


    def load_sequence_captures(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load operation-sequence captures", "",
            "Capture files (*.json *.jsonl *.ndjson *.csv *.log *.txt);;All files (*)"
        )
        if not paths:
            return
        loaded = []
        failures = []
        for path in paths:
            try:
                metadata, records = load_capture_file(path)
            except Exception as exc:
                failures.append(f"{Path(path).name}: {exc}")
                continue
            markers = metadata.pop("markers", [])
            loaded.append({
                "name": metadata.get("session_name") or Path(path).name,
                "metadata": metadata,
                "frames": records,
                "markers": markers,
            })
        self.sequence_captures = loaded
        message = (
            f"Loaded {len(loaded)} sequence capture(s); "
            f"{sum(len(item['markers']) for item in loaded)} action markers."
        )
        if failures:
            message += "\\n\\nCould not load:\\n" + "\\n".join(failures)
        self.status_label.setText(message.replace("\\n", "\n"))

    def _module_inventory_capture_set(self):
        """Return independently loaded captures for passive node comparison."""
        if self.sequence_captures:
            return list(self.sequence_captures)
        captures = []
        if self.frames:
            name = (
                self.metadata.get("session_name")
                or Path(self.metadata.get("imported_from", "Working capture")).name
            )
            captures.append({"name": name, "frames": self.frames})
        if self.reference_frames:
            name = (
                self.reference_metadata.get("session_name")
                or Path(self.reference_metadata.get("imported_from", "Reference capture")).name
            )
            captures.append({"name": name, "frames": self.reference_frames})
        return captures

    def analyze_module_inventory(self):
        """Compare observed CAN nodes across independently loaded capture files."""
        captures = self._module_inventory_capture_set()
        if len(captures) < 2:
            QMessageBox.information(
                self, "Cross-capture module inventory",
                "Load at least two saved captures using Load sequences, or load a working capture and a comparison capture."
            )
            return
        result = compare_module_discovery(captures)
        lines = [
            f"Independent captures analyzed: {result['capture_count']}",
            f"Distinct CAN nodes: {result['node_count']}",
            "Nodes are keyed by CAN ID, CAN format, and channel.",
            "Repeatability is not proof of physical ECU identity. No CAN traffic was transmitted.",
            "",
            "CAPTURES",
        ]
        for capture in result["captures"]:
            lines.append(
                f"  {capture['name']}: {capture['frame_count']:,} frames, "
                f"{capture['observed_node_count']} nodes, "
                f"{capture['probable_responder_count']} probable responders"
            )
        lines += ["", "CROSS-CAPTURE NODE INVENTORY"]
        for node in result["nodes"]:
            channel = node["channel"] if node["channel"] is not None else "unspecified"
            request_ids = ", ".join(f"0x{value:X}" for value in node["request_ids"]) or "none"
            services = ", ".join(f"0x{value:02X}" for value in node["services"]) or "none"
            lines.append(
                f"  0x{node['can_id']:X} {'EXT' if node['extended'] else 'STD'} "
                f"channel={channel} | {node['evidence_level']} | "
                f"{node['repeatability']} | captures={node['capture_count']}/{result['capture_count']} | "
                f"frames={node['observed_frame_count']}"
            )
            lines.append(
                f"    probable responder captures={node['probable_capture_count']}; "
                f"request IDs={request_ids}; services={services}"
            )
            lines.append(f"    {node['interpretation']}")
        if not result["nodes"]:
            lines.append("No valid CAN nodes were found in the selected captures.")
        lines += ["", "LIMITATIONS"]
        lines.extend(f"  - {item}" for item in result["limitations"])

        dialog = QDialog(self)
        dialog.setWindowTitle("Cross-capture passive module inventory")
        dialog.resize(1050, 680)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"{result['node_count']:,} distinct nodes across {result['capture_count']:,} captures"
        ))
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"Compared {result['node_count']:,} passive CAN nodes across {result['capture_count']:,} captures"
        )


    def analyze_can_timing(self):
        """Show passive inter-frame timing observations for the current capture."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(
                self, "CAN timing analysis", "Capture or import CAN frames first."
            )
            return

        report = analyze_message_periodicity(dataset)
        dialog = QDialog(self)
        dialog.setWindowTitle("Passive CAN message timing")
        dialog.resize(1050, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"{report['frame_count'] if 'frame_count' in report else len(dataset):,} input frames · "
            f"{report['node_count']:,} CAN ID/format/channel groups · "
            f"{report['invalid_record_count']:,} invalid records"
        ))
        note = QLabel(
            "Intervals are calculated from timestamps in this capture. They are observed rates, "
            "not proof of an ECU's configured transmit period. Capture buffering, dropped frames, "
            "timestamp resolution and clock quality can affect the result. No frames are transmitted."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        columns = [
            "CAN ID", "Channel", "Format", "Frames", "Intervals",
            "Median ms", "Mean ms", "Min ms", "Max ms", "p95 deviation ms",
            "Observed Hz", "Duplicate", "Out of order",
        ]
        table = QTableWidget(report["node_count"], len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSortingEnabled(False)

        def milliseconds(value):
            return "" if value is None else f"{value * 1000:.3f}"

        for row, node in enumerate(report["nodes"]):
            interval = node["median_interval_s"]
            values = [
                f"0x{node['can_id']:X}",
                str(node["channel"] or "unspecified"),
                "EXT" if node["extended"] else "STD",
                f"{node['frame_count']:,}",
                f"{node['interval_count']:,}",
                milliseconds(interval),
                milliseconds(node["mean_interval_s"]),
                milliseconds(node["min_interval_s"]),
                milliseconds(node["max_interval_s"]),
                milliseconds(node["p95_absolute_deviation_s"]),
                f"{1.0 / interval:.3f}" if interval and interval > 0 else "",
                str(node["duplicate_timestamp_count"]),
                str(node["non_monotonic_timestamp_count"]),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)

        footer = QLabel(
            "Observed Hz = reciprocal of median positive interval. Duplicate and out-of-order "
            "timestamps are excluded from interval calculations and reported separately."
        )
        footer.setWordWrap(True)
        layout.addWidget(footer)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"CAN timing analysis: {report['node_count']:,} groups from {len(dataset):,} frames"
        )


    def analyze_payload_variability(self):
        """Display observed byte/bit changes for the current passive capture."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(
                self, "Payload variability", "Capture or import CAN frames first."
            )
            return

        report = analyze_payload_variability(dataset)
        dialog = QDialog(self)
        dialog.setWindowTitle("Passive CAN payload variability")
        dialog.resize(1120, 680)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"{report['input_frame_count']:,} input frames · "
            f"{report['node_count']:,} CAN ID/format/channel/DLC groups · "
            f"{report['invalid_record_count']:,} invalid records"
        ))
        note = QLabel(
            "Variable bytes and bits are observations, not decoded signals. This analysis "
            "does not infer byte order, scaling, signedness, multiplexing, units, or ECU identity. "
            "Capture order and missing frames affect transition counts. No CAN traffic is transmitted."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        columns = [
            "CAN ID", "Channel", "Format", "DLC", "Frames",
            "Variable bytes", "Byte offsets / values", "Variable bit masks",
        ]
        table = QTableWidget(report["node_count"], len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        for row, node in enumerate(report["nodes"]):
            details = []
            masks = []
            for item in node["bytes"]:
                label = f"B{item['offset']}="
                if item["constant"]:
                    label += f"{item['most_common_value']:02X} fixed"
                else:
                    label += (
                        f"{item['min_value']:02X}-{item['max_value']:02X} "
                        f"({item['unique_value_count']} values)"
                    )
                details.append(label)
                if item["variable_bit_mask"]:
                    masks.append(f"B{item['offset']}:0x{item['variable_bit_mask']:02X}")
            values = [
                f"0x{node['can_id']:X}",
                str(node["channel"] or "unspecified"),
                "EXT" if node["extended"] else "STD",
                str(node["dlc"]),
                f"{node['frame_count']:,}",
                ", ".join(str(value) for value in node["variable_byte_offsets"]) or "none",
                "  ".join(details),
                ", ".join(masks) or "none",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)

        footer = QLabel(
            "Bit masks use conventional byte notation: bit 7 is the most-significant bit, "
            "bit 0 the least-significant bit. A set mask bit changed at least once in this capture."
        )
        footer.setWordWrap(True)
        layout.addWidget(footer)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"Payload variability: {report['node_count']:,} groups from {len(dataset):,} frames"
        )

    def analyze_operation_sequences(self):
        if len(self.sequence_captures) < 2:
            QMessageBox.information(
                self, "Operation-sequence comparison",
                "Load at least two saved research captures that contain action markers."
            )
            return
        result = compare_operation_sequences(self.sequence_captures)
        lines = [
            f"Captures analyzed: {result['capture_count']}",
            "Operations are grouped by the marker's operation label.",
            "Rates are normalized to frames/second; response delay is the first observed matching frame after the marker.",
            "One-capture observations may be incidental. Repeatability is evidence, not proof of ECU identity or causation.",
            "",
            "CAPTURE SEQUENCES",
        ]
        for capture in result["capture_sequences"]:
            sequence = " -> ".join(capture["operations"]) or "(no valid markers)"
            lines.append(f"  {capture['name']}: {sequence}")
        lines += ["", "SEQUENCE ALIGNMENT"]
        lines.append(
            f"Reference order: {result['sequence_reference'] or '(none)'}"
        )
        if not result["sequence_comparisons"]:
            lines.append("Only one capture is available; no cross-capture order comparison.")
        for comparison in result["sequence_comparisons"]:
            lines.append(f"  {comparison['capture_name']}:")
            if comparison["matches_reference"]:
                lines.append("    Matches reference operation order.")
            else:
                for change in comparison["changes"]:
                    before = " -> ".join(change["reference_operations"]) or "(nothing)"
                    after = " -> ".join(change["capture_operations"]) or "(nothing)"
                    lines.append(
                        f"    {change['change_type'].upper()} at reference step "
                        f"{change['reference_index'] + 1}, capture step "
                        f"{change['capture_index'] + 1}: reference [{before}] "
                        f"versus capture [{after}]"
                    )
        lines += ["", "OPERATION COMPARISON"]
        for operation in result["operations"]:
            lines.append(
                f"\\n{operation['operation']} | markers={operation['marker_count']} "
                f"| captures={operation['capture_count']}"
            )
            for signal in operation["signals"][:100]:
                channel = signal["channel"] if signal["channel"] is not None else "unspecified"
                delay = signal["median_response_delay_seconds"]
                delay_text = f"{delay * 1000:.1f} ms" if delay is not None else "not observed"
                lines.append(
                    f"  CAN 0x{signal['can_id']:X} "
                    f"{'EXT' if signal['extended'] else 'STD'} ch={channel} "
                    f"{signal['payload'].upper() or '(empty)'} | "
                    f"{signal['capture_count']}/{operation['capture_count']} captures containing this operation | "
                    f"before={signal['average_before_frames_per_second']:.2f}/s "
                    f"after={signal['average_after_frames_per_second']:.2f}/s | "
                    f"median first-frame delay={delay_text} | {signal['repeatability']}"
                )
            if not operation["signals"]:
                lines.append("  No monotonic-timed CAN frames found around these markers.")

        uds_operations = summarize_operation_uds_transactions(
            self.sequence_captures
        )
        lines += ["", "CORRELATED UDS TRANSACTIONS"]
        lines.append(
            "Only complete, probable request/response pairs are shown. "
            "Payloads are raw UDS bytes; identifiers do not prove ECU identity."
        )
        if not uds_operations:
            lines.append("No complete probable UDS transactions were associated with marker windows.")
        for operation in uds_operations:
            lines.append(
                f"  {operation['operation']} | captures={operation['capture_count']}"
            )
            for transaction in operation["transactions"][:100]:
                channel = transaction["channel"] if transaction["channel"] is not None else "unspecified"
                lines.append(
                    f"    0x{transaction['request_id']:X} -> "
                    f"0x{transaction['response_id']:X} "
                    f"{'EXT' if transaction['extended'] else 'STD'} ch={channel} "
                    f"SID=0x{transaction['service']:02X} "
                    f"{transaction['response_kind'].upper()} "
                    f"REQ={transaction['request_payload'].upper()} "
                    f"RESP={transaction['response_payload'].upper()} | "
                    f"{transaction['capture_count']}/{operation['capture_count']} captures | "
                    f"median latency={transaction['median_latency_seconds'] * 1000:.1f} ms | "
                    f"{transaction['repeatability']}"
                )
        identifiers = summarize_operation_uds_identifiers(uds_operations)
        lines += [
            "",
            "OBSERVED UDS IDENTIFIERS",
            "DIDs and routine IDs are raw observed identifiers; meanings are not inferred.",
        ]
        if not identifiers:
            lines.append("No decodable DID or RoutineControl identifiers observed.")
        for item in identifiers:
            detail = (
                f"{item['routine_control_name']} "
                f"(type 0x{item['routine_control_type']:02X}, "
                f"raw subfunction 0x{item['subfunction']:02X})"
                if item["kind"] == "Routine ID" else f"{item['access']} request"
            )
            lines.append(
                f"  {item['operation']} | {item['label']} | {detail} | "
                f"captures={item['capture_count']} | requests={item['request_count']} | "
                f"positive={item['positive_count']} negative={item['negative_count']} "
                f"other={item['unknown_count']} | {item['repeatability']}"
            )
            if item["response_examples"]:
                lines.append(
                    "    response examples: " + ", ".join(
                        value.upper() for value in item["response_examples"][:5]
                    )
                )
        did_variations = summarize_operation_did_response_variation(uds_operations)
        lines += [
            "",
            "DID RESPONSE DATA COMPARISON",
            "Raw data bytes only. Single-DID positive responses are compared; multi-DID "
            "responses are skipped because record boundaries are not known. Byte offsets are zero-based.",
        ]
        if not did_variations:
            lines.append("No safely comparable positive single-DID responses observed.")
        for item in did_variations:
            lengths = ", ".join(str(value) for value in item["value_lengths"]) or "none"
            offsets = ", ".join(str(value) for value in item["variable_byte_offsets"]) or "none"
            lines.append(
                f"  {item['operation']} | {item['label']} | "
                f"captures={item['capture_count']} | observations={item['total_count']} | "
                f"distinct values={item['distinct_value_count']} | "
                f"data lengths={lengths} bytes | variable offsets={offsets} | "
                f"{item['data_pattern']}"
            )
            for value in item["value_examples"]:
                lines.append(f"    data={value.upper() or '(empty)'}")
        dialog = QDialog(self)
        dialog.setWindowTitle("Multi-capture operation-sequence comparison")
        dialog.resize(1100, 720)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{result['capture_count']} captures · {len(result['operations'])} operation types"
        )
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\\n".join(lines).replace("\\n", "\n"))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"Compared {result['capture_count']} captures across {len(result['operations'])} operation types."
        )

    def save_session(self):
        self._flush_pending_frames()
        if not self.frames:
            QMessageBox.information(self, "Save research session", "There are no frames to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save research session", "freerov3r_research.json", "FreeRov3r research (*.json)"
        )
        if not path:
            return
        payload = {
            "format": "freerov3r-research-v1",
            "metadata": {
                **self.metadata,
                "session_name": self.session_name.text().strip(),
                "operation": self.operation.currentText(),
                "notes": self.notes.text().strip(),
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "capture_timestamp_basis": "host_monotonic",
                "device_timestamp_basis": "esp_timer_get_time microseconds since each board boot; clocks are independent and unsynchronized",
                "firmware_protocol": 2,
                "channel_names": sorted({str(frame.get("channel")) for frame in self.frames if frame.get("channel")}),
                "channel_frame_counts": dict(Counter(str(frame.get("channel") or "unspecified") for frame in self.frames)),
            },
            "frames": self.frames,
            "bookmarks": self.bookmarks,
            "markers": self.markers,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status_label.setText(f"Saved {len(self.frames):,} frames to {Path(path).name}")

    def decode_did_responses(self):
        """Load a source-backed DID registry and decode matching captured responses."""
        self._flush_pending_frames()
        if not self.frames:
            QMessageBox.information(
                self, "DID response decoding", "Capture or import CAN frames first."
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DID definition registry", "",
            "DID definitions (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            registry = DIDDefinitionRegistry.from_json(path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(
                self, "DID definition registry",
                f"Could not load the definition file:\n{exc}"
            )
            return

        vehicle = self.did_vehicle_key.text().strip()
        if not vehicle:
            QMessageBox.warning(
                self, "DID response decoding",
                "Enter the exact vehicle key used by the definitions."
            )
            return

        messages = reassemble_isotp(self.frames)
        transactions = pair_uds_transactions(messages)
        decoded = decode_uds_did_transactions(
            transactions, registry, vehicle=vehicle
        )
        self.did_registry = registry
        self.did_registry_path = path

        lines = [
            f"Definition file: {Path(path).name}",
            f"Vehicle key: {vehicle}",
            f"Transactions paired: {sum(p.get('confidence') == 'probable' for p in transactions)}",
            f"Single-DID positive reads considered: {len(decoded)}",
            "",
            "Only exact vehicle/DID matches are decoded. Raw payloads and source provenance are retained.",
            "Multi-DID, negative, unmatched and unknown definitions are not interpreted.",
            "",
        ]
        for item in decoded:
            result = item["decoded"]
            lines.append(
                f"DID 0x{item['did']:04X} | request CAN 0x{int(item['request_id']):X} "
                f"-> response CAN 0x{int(item['response_id']):X}"
            )
            lines.append(
                f"  REQ={item['request_payload'].upper()} RESP={item['response_payload'].upper()}"
            )
            if result["status"] == "unknown_definition":
                lines.append(f"  UNKNOWN DEFINITION | raw data={result.get('data', '').upper()}")
                continue
            if result["status"] != "decoded":
                lines.append(f"  Not decoded: {result['status']}")
                continue
            definition = result["definition"]
            source = definition["source"]
            lines.append(
                f"  {definition['name']} | module={definition['module'] or 'unassigned'} "
                f"| confidence={definition['confidence']}"
            )
            lines.append(
                f"  Source: {source['title']} | {source['reference']} "
                f"{source['url']}".rstrip()
            )
            lines.append(f"  Raw DID data: {result['data'].upper()}")
            for field in result["fields"]:
                if field["status"] == "truncated":
                    value = "TRUNCATED"
                else:
                    value = str(field["value"])
                    if field["unit"]:
                        value += f" {field['unit']}"
                lines.append(
                    f"    +{field['offset']} {field['name']}: {value} "
                    f"[{field['raw_hex'].upper()}]"
                )
        if not decoded:
            lines.append("No eligible single-DID positive responses were found.")

        dialog = QDialog(self)
        dialog.setWindowTitle("Source-backed DID response decoding")
        dialog.resize(1050, 700)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"{len(decoded)} eligible response(s) · {len(registry._definitions)} definition(s) loaded"
        ))
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"DID decoding complete: {len(decoded)} eligible response(s); raw captures unchanged."
        )

    def analyze_isotp(self):
        """Reassemble captured ISO-TP messages without transmitting anything."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(self, "ISO-TP reassembly", "Capture or import CAN frames first.")
            return

        messages = reassemble_isotp(dataset)
        complete = [item for item in messages if item["status"] == "complete"]
        incomplete = [item for item in messages if item["status"] != "complete"]
        lines = [
            f"Input frames: {len(dataset):,}",
            f"Complete messages: {len(complete):,}",
            f"Incomplete / malformed: {len(incomplete):,}",
            "",
            "Messages (capture order):",
        ]
        for item in messages[-500:]:
            lines.append(
                f'{item["started_at"]:.6f}  CAN 0x{item["arbitration_id"]:X}  '
                f'{item["status"].upper()}  {item["payload"].upper()}  '
                f'UDS: {classify_uds_payload(bytes.fromhex(item["payload"]))}  '
                f'[{item["frame_count"]} frame(s)]  {item["detail"]}'
            )
        if len(messages) > 500:
            lines.append(f"... {len(messages) - 500:,} earlier messages omitted from this view.")

        dialog = QDialog(self)
        dialog.setWindowTitle("ISO-TP reassembly results")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{len(complete):,} complete messages · {len(incomplete):,} incomplete or malformed"
        )
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"ISO-TP analysis complete: {len(complete):,} complete, "
            f"{len(incomplete):,} incomplete or malformed"
        )

    def analyze_uds_pairs(self):
        """Show probable UDS request/response pairs from passive capture data."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(self, "UDS transaction pairing", "Capture or import CAN frames first.")
            return

        messages = reassemble_isotp(dataset)
        pairs = pair_uds_transactions(messages)
        matched = [pair for pair in pairs if pair["confidence"] == "probable"]
        unmatched = [pair for pair in pairs if pair["confidence"] != "probable"]
        lines = [
            f"Complete ISO-TP messages: {sum(item['status'] == 'complete' for item in messages):,}",
            f"Probable request/response pairs: {len(matched):,}",
            f"Unmatched messages: {len(unmatched):,}",
            "",
            "Pairing is heuristic. CAN IDs and direction are not proof of ECU identity.",
            "",
        ]
        for pair in pairs[-500:]:
            request = pair.get("request")
            response = pair.get("response")
            if request and response:
                lines.append(
                    f'PAIRED  {request["started_at"]:.6f} → {response["started_at"]:.6f}  '
                    f'0x{request["arbitration_id"]:X} → 0x{response["arbitration_id"]:X}  '
                    f'{request["payload"].upper()} → {response["payload"].upper()}  '
                    f'{pair["latency_seconds"] * 1000:.2f} ms  '
                    f'{pair["response_kind"].upper()}  {pair["addressing_hint"]}'
                )
            else:
                message = pair.get("message") or request or response
                if message:
                    lines.append(
                        f'UNMATCHED  {message["started_at"]:.6f}  '
                        f'0x{message["arbitration_id"]:X}  {message["payload"].upper()}'
                    )
        dialog = QDialog(self)
        dialog.setWindowTitle("UDS request / response analysis")
        dialog.resize(1000, 620)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{len(matched):,} probable pairs · {len(unmatched):,} unmatched messages"
        )
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"UDS pairing complete: {len(matched):,} probable pairs, {len(unmatched):,} unmatched"
        )

    def analyze_address_map(self):
        """Aggregate repeated probable pairs into candidate responder addresses."""
        self._flush_pending_frames()
        dataset = self.frames if self.frames else self.live_preview
        if not dataset:
            QMessageBox.information(self, "CAN address map", "Capture or import CAN frames first.")
            return

        messages = reassemble_isotp(dataset)
        transactions = pair_uds_transactions(messages)
        candidates = summarize_ecu_address_pairs(transactions)
        matched_count = sum(item.get("confidence") == "probable" for item in transactions)
        lines = [
            f"Complete ISO-TP messages: {sum(item['status'] == 'complete' for item in messages):,}",
            f"Probable UDS pairs used: {matched_count:,}",
            f"Candidate request/response ID groups: {len(candidates):,}",
            "",
            "These are observed responder CAN IDs, not identified ECUs.",
            "Confidence is based on repeated protocol-level pair observations only.",
            "",
        ]
        for item in candidates:
            services = ", ".join(f"0x{sid:02X}" for sid in item["services"])
            channel = item["channel"] if item["channel"] is not None else "unspecified"
            lines.append(
                f'Request 0x{item["request_id"]:X} → candidate responder 0x{item["response_id"]:X}  '
                f'{"EXT" if item["extended"] else "STD"}  channel={channel}  '
                f'pairs={item["pair_count"]}  services={services or "none"}  '
                f'positive={item["positive_count"]} negative={item["negative_count"]}  '
                f'avg={item["average_latency_seconds"] * 1000:.2f} ms  '
                f'{item["addressing_hint"]}'
            )
            lines.append(f'  Status: {item["interpretation"]}')
        if not candidates:
            lines.append("No probable request/response pairs were available to build a candidate map.")

        dialog = QDialog(self)
        dialog.setWindowTitle("Evidence-based CAN address map")
        dialog.resize(1050, 650)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{len(candidates):,} candidate ID groups from {matched_count:,} probable UDS pairs"
        )
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"CAN address analysis complete: {len(candidates):,} candidate ID groups; ECU identities remain unknown"
        )


    def analyze_cross_captures(self):
        """Validate whether probable CAN address pairs recur in both captures."""
        self._flush_pending_frames()
        if not self.frames or not self.reference_frames:
            QMessageBox.information(
                self, "Cross-capture validation",
                "Load a working capture and a comparison capture first."
            )
            return

        working_messages = reassemble_isotp(self.frames)
        reference_messages = reassemble_isotp(self.reference_frames)
        working_pairs = pair_uds_transactions(working_messages)
        reference_pairs = pair_uds_transactions(reference_messages)
        working_name = (
            self.metadata.get("session_name")
            or Path(self.metadata.get("imported_from", "Working capture")).name
            or "Working capture"
        )
        reference_name = (
            self.reference_metadata.get("session_name")
            or Path(self.reference_metadata.get("imported_from", "Reference capture")).name
            or "Reference capture"
        )
        summaries = summarize_cross_capture_address_pairs([
            {"name": working_name, "transactions": working_pairs},
            {"name": reference_name, "transactions": reference_pairs},
        ])
        repeated = [item for item in summaries if item["capture_count"] >= 2]
        lines = [
            f"Working capture: {working_name} ({len(self.frames):,} CAN frames; "
            f"{sum(p['confidence'] == 'probable' for p in working_pairs):,} probable pairs)",
            f"Reference capture: {reference_name} ({len(self.reference_frames):,} CAN frames; "
            f"{sum(p['confidence'] == 'probable' for p in reference_pairs):,} probable pairs)",
            f"Address pairs repeated in both captures: {len(repeated):,}",
            f"Distinct candidate pairs observed: {len(summaries):,}",
            "",
            "Each capture was decoded and paired independently. No transaction was paired across files.",
            "Repeatability strengthens an observed ID relationship; it does not identify a physical ECU.",
            "",
        ]
        for item in summaries:
            channel = item["channel"] if item["channel"] is not None else "unspecified"
            services = ", ".join(f"0x{sid:02X}" for sid in item["services"])
            lines.append(
                f'Request 0x{item["request_id"]:X} → responder candidate 0x{item["response_id"]:X} '
                f'{"EXT" if item["extended"] else "STD"} channel={channel}'
            )
            lines.append(
                f'  {item["repeatability"]}; captures={item["capture_count"]}/2; '
                f'pairs={item["pair_count"]}; per-capture={item["per_capture_pair_counts"]}'
            )
            lines.append(
                f'  services={services or "none"}; positive={item["positive_count"]}; '
                f'negative={item["negative_count"]}; average latency='
                f'{item["average_latency_seconds"] * 1000:.2f} ms'
            )
            lines.append(f'  Interpretation: {item["interpretation"]}')
        if not summaries:
            lines.append("No probable UDS request/response pairs were found in either capture.")

        dialog = QDialog(self)
        dialog.setWindowTitle("Cross-capture CAN address validation")
        dialog.resize(1050, 680)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{len(repeated):,} repeated ID relationships · {len(summaries):,} total candidates"
        )
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"Cross-capture validation complete: {len(repeated):,} repeated ID relationships; "
            "physical ECU identities remain unknown"
        )


    def analyze_marker_windows(self):
        """Compare frame payload frequencies in short windows around each action marker."""
        self._flush_pending_frames()
        if not self.frames or not self.markers:
            QMessageBox.information(
                self, "Operation comparison",
                "A recorded capture with at least one action marker is required."
            )
            return
        results = analyze_marker_windows(self.frames, self.markers)
        lines = [
            "Default windows: 2.0 seconds before and 5.0 seconds after each marker.",
            "Only frames carrying the recording's monotonic elapsed_seconds are included.",
            "Payload count changes are correlation evidence, not proof of ECU identity or causation.",
            "",
        ]
        for result in results:
            marker = result["marker"]
            lines.append(
                f'MARKER {result["marker_index"]}: {marker.get("elapsed_seconds", 0):.3f}s '
                f'| {marker.get("operation", "Unspecified")} | {marker.get("note", "")}'
            )
            lines.append(
                f'  Frames: before={result["before_frames"]}, after={result["after_frames"]}'
            )
            for change in result["changes"][:30]:
                channel = change["channel"] if change["channel"] is not None else "unspecified"
                lines.append(
                    f'  CAN 0x{change["can_id"]:X} '
                    f'{"EXT" if change["extended"] else "STD"} channel={channel} '
                    f'{change["payload"].upper() or "(empty)"} '
                    f'before={change["before_count"]} after={change["after_count"]} '
                    f'delta={change["delta"]:+}'
                )
            if not result["changes"]:
                lines.append("  No payload-frequency changes found in the selected windows.")
            lines.append("")
        if not results:
            lines.append("No usable marker timestamps were found.")
        dialog = QDialog(self)
        dialog.setWindowTitle("Scanner operation traffic comparison")
        dialog.resize(1050, 680)
        layout = QVBoxLayout(dialog)
        summary = QLabel(f"{len(results):,} operation markers analyzed")
        layout.addWidget(summary)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n".join(lines))
        layout.addWidget(output, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self.status_label.setText(
            f"Operation comparison complete: {len(results):,} markers; correlation only"
        )

    def build_analysis_packet(self):
        self._flush_pending_frames()
        lines = [
            "# FreeRov3r protocol research packet",
            "",
            "Analyze only the captured evidence. Separate observations, hypotheses, and unknowns.",
            "Do not infer ECU identity or request/response direction from CAN ID alone.",
            "ISO-TP and UDS labels below are heuristic hints, not confirmed interpretations.",
            "Do not recommend replaying unknown frames or performing ECU writes.",
            "",
            "## Per-channel timestamp quality",
            json.dumps(analyze_channel_timestamps(self.frames), indent=2),
            "",
            "## Passive CAN payload variability",
            json.dumps(analyze_payload_variability(self.frames), indent=2),
            "",
            "## DBC capture coverage audit",
            json.dumps(audit_dbc_capture(self.dbc_library, self.frames), indent=2),
            "",
            "## DBC signal behavior",
            json.dumps(analyze_dbc_signal_behavior(self.dbc_library, self.frames), indent=2),
            "",
            "## Session context",
            json.dumps({
                **self.metadata,
                "session_name": self.session_name.text().strip(),
                "operation": self.operation.currentText(),
                "notes": self.notes.text().strip(),
            }, indent=2),
            "",
            f"## Capture ({len(self.frames)} frames)",
            "| Timestamp | Elapsed seconds | CAN ID | Format | Payload | ISO-TP | UDS hint |",
            "|---:|---:|---:|---|---|---|---|",
        ]
        for record in self.frames[:20000]:
            iso, uds = classify_can_payload(bytes.fromhex(record["data"]))
            elapsed = (
                f'{record["elapsed_seconds"]:.6f}'
                if record.get("elapsed_seconds") is not None else ""
            )
            lines.append(
                f'| {record["timestamp"]:.6f} | {elapsed} | 0x{record["arbitration_id"]:X} | '
                f'{"EXT" if record["extended"] else "STD"} | {record["data"].upper()} | {iso} | {uds} |'
            )
        inventory_captures = self._module_inventory_capture_set()
        if len(inventory_captures) >= 2:
            lines += [
                "",
                "## Cross-capture passive module inventory",
                "Each saved capture is analyzed independently. No CAN transmission or cross-file UDS pairing occurs.",
                json.dumps(compare_module_discovery(inventory_captures), indent=2),
            ]
        messages = reassemble_isotp(self.frames)
        lines += [
            "",
            "## Reassembled ISO-TP messages",
            f"Complete: {sum(item['status'] == 'complete' for item in messages)}",
            f"Incomplete / malformed: {sum(item['status'] != 'complete' for item in messages)}",
            "| Start timestamp | CAN ID | Status | Payload | UDS service | Frames | Detail |",
            "|---:|---:|---|---|---|---:|---|",
        ]
        for item in messages[:20000]:
            lines.append(
                f'| {item["started_at"]:.6f} | 0x{item["arbitration_id"]:X} | '
                f'{item["status"]} | {item["payload"].upper()} | '
                f'{classify_uds_payload(bytes.fromhex(item["payload"]))} | '
                f'{item["frame_count"]} | {item["detail"]} |'
            )
        transactions = pair_uds_transactions(messages)
        lines += [
            "",
            "## Probable UDS request / response pairs",
            "Associations are heuristic, not proof of ECU identity or direction.",
            "| Request time | Request CAN ID | Request payload | Response time | Response CAN ID | Response payload | Latency ms | Type | Addressing hint |",
            "|---:|---:|---|---:|---:|---|---:|---|---|",
        ]
        for pair in transactions[:20000]:
            request = pair.get("request")
            response = pair.get("response")
            if request and response:
                lines.append(
                    f'| {request["started_at"]:.6f} | 0x{request["arbitration_id"]:X} | '
                    f'{request["payload"].upper()} | {response["started_at"]:.6f} | '
                    f'0x{response["arbitration_id"]:X} | {response["payload"].upper()} | '
                    f'{pair["latency_seconds"] * 1000:.3f} | {pair["response_kind"]} | '
                    f'{pair["addressing_hint"]} |'
                )
        address_candidates = summarize_ecu_address_pairs(transactions)
        module_discovery = discover_modules(self.frames)
        lines += [
            "",
            "## Passive module discovery",
            "This section analyzes captured traffic only. It does not transmit diagnostic requests.",
            f"Observed CAN nodes: {module_discovery['valid_observed_id_count']}",
            f"Complete ISO-TP messages: {module_discovery['complete_isotp_message_count']}",
            f"Probable UDS transactions: {module_discovery['probable_uds_transaction_count']}",
            "| CAN ID | Format | Channel | Frames | Role | Evidence | Request IDs | UDS services |",
            "|---:|---|---|---:|---|---|---|---|",
        ]
        for node in module_discovery["nodes"]:
            request_ids = ", ".join(f"0x{value:X}" for value in node["request_ids"]) or "—"
            services = ", ".join(f"0x{value:02X}" for value in node["services"]) or "—"
            lines.append(
                f"| 0x{node['can_id']:X} | "
                f"{'EXT' if node['extended'] else 'STD'} | "
                f"{node['channel'] or 'unspecified'} | {node['frame_count']} | "
                f"{node['role']} | {node['evidence_level']} | "
                f"{request_ids} | {services} |"
            )
        lines += ["", "Discovery limitations:"]
        lines.extend(f"- {item}" for item in module_discovery["limitations"])
        lines += [
            "",
            "## Candidate CAN responder address map",
            "Observed ID relationships only; physical ECU identities are unknown.",
            "| Request ID | Candidate responder ID | Format | Channel | Pair count | Services | Positive | Negative | Average latency ms |",
            "|---:|---:|---|---|---:|---|---:|---:|---:|",
        ]
        for item in address_candidates:
            service_text = ", ".join("0x{:02X}".format(sid) for sid in item["services"])
            lines.append(
                f'| 0x{item["request_id"]:X} | 0x{item["response_id"]:X} | '
                f'{"EXT" if item["extended"] else "STD"} | {item["channel"] or "unspecified"} | '
                f'{item["pair_count"]} | {service_text} | '
                f'{item["positive_count"]} | {item["negative_count"]} | '
                f'{item["average_latency_seconds"] * 1000:.3f} |'
            )
        lines += ["", "## Operation markers"]
        lines.extend(
            f'- {m["elapsed_seconds"]:.3f}s | {m["operation"]} | {m["note"]}'
            for m in self.markers
        )
        marker_results = analyze_marker_windows(self.frames, self.markers) if self.frames and self.markers else []
        lines += ["", "## Marker-window traffic comparison",
                  "Default windows: 2 seconds before and 5 seconds after each marker. "
                  "Only monotonic-timed frames are included; correlations do not prove causation."]
        for result in marker_results:
            marker = result["marker"]
            lines.append(
                f'- Marker {result["marker_index"]} at {marker["elapsed_seconds"]:.3f}s: '
                f'{marker.get("operation", "Unspecified")}; frames before/after: '
                f'{result["before_frames"]}/{result["after_frames"]}'
            )
            for change in result["changes"][:50]:
                lines.append(
                    f'  - CAN 0x{change["can_id"]:X} {change["payload"].upper()}: '
                    f'{change["before_count"]} → {change["after_count"]} '
                    f'(delta {change["delta"]:+})'
                )
        if self.sequence_captures:
            sequence_result = compare_operation_sequences(self.sequence_captures)
            lines += [
                "",
                "## Multi-capture operation sequence comparison",
                f"Reference capture: {sequence_result['sequence_reference']}",
            ]
            for comparison in sequence_result["sequence_comparisons"]:
                lines.append(
                    f"- {comparison['capture_name']}: "
                    f"{'matches reference order' if comparison['matches_reference'] else 'operation order differs'}"
                )
                for change in comparison["changes"]:
                    before = " -> ".join(change["reference_operations"]) or "(nothing)"
                    after = " -> ".join(change["capture_operations"]) or "(nothing)"
                    lines.append(
                        f"  - {change['change_type']}: reference [{before}] "
                        f"versus capture [{after}]"
                    )

            uds_operations = summarize_operation_uds_transactions(
                self.sequence_captures
            )
            lines += [
                "",
                "## UDS transactions grouped by marked operation",
                "Only complete probable pairs are included. CAN IDs do not establish physical ECU identity.",
            ]
            for operation in uds_operations:
                lines.append(
                    f"### {operation['operation']} "
                    f"({operation['capture_count']} capture(s) contained this operation)"
                )
                for transaction in operation["transactions"]:
                    lines.append(
                        f"- 0x{transaction['request_id']:X} -> "
                        f"0x{transaction['response_id']:X}; "
                        f"SID 0x{transaction['service']:02X}; "
                        f"{transaction['response_kind']}; "
                        f"request {transaction['request_payload'].upper()}; "
                        f"response {transaction['response_payload'].upper()}; "
                        f"seen in {transaction['capture_count']} capture(s); "
                        f"median latency {transaction['median_latency_seconds'] * 1000:.2f} ms"
                    )
                if not operation["transactions"]:
                    lines.append("- No complete probable UDS transaction observed.")

            did_variations = summarize_operation_did_response_variation(uds_operations)
            lines += [
                "",
                "## DID response data comparison",
                "Raw bytes only; multi-DID responses are omitted because record boundaries are unknown. Byte offsets are zero-based.",
            ]
            for item in did_variations:
                offsets = ", ".join(str(value) for value in item["variable_byte_offsets"]) or "none"
                lines.append(
                    f"- {item['operation']} {item['label']}: "
                    f"{item['capture_count']} captures; {item['total_count']} observations; "
                    f"{item['distinct_value_count']} distinct values; "
                    f"lengths={item['value_lengths']}; variable byte offsets={offsets}; "
                    f"{item['data_pattern']}; examples={item['value_examples']}"
                )

            identifier_summaries = summarize_operation_uds_identifiers(uds_operations)
            lines += [
                "",
                "## Observed UDS data and routine identifiers",
                "Raw identifiers only; no vehicle-specific meaning is assigned.",
            ]
            for item in identifier_summaries:
                lines.append(
                    f"- {item['operation']}: {item['label']}; "
                    f"requests={item['request_count']}; "
                    f"captures={item['capture_count']}; "
                    f"positive={item['positive_count']}; "
                    f"negative={item['negative_count']}; "
                    f"other={item['unknown_count']}"
                )
        registry = getattr(self, "did_registry", None)
        if registry is not None:
            did_results = decode_uds_did_transactions(
                transactions, registry,
                vehicle=self.did_vehicle_key.text().strip(),
            )
            lines += [
                "",
                "## Source-backed DID decoding",
                f"Definition file: {getattr(self, 'did_registry_path', '')}",
                f"Vehicle key: {self.did_vehicle_key.text().strip()}",
                "Only paired positive single-DID reads are decoded; raw payloads and provenance are retained.",
            ]
            for item in did_results:
                decoded = item["decoded"]
                lines.append(
                    f"- DID 0x{item['did']:04X}: REQ={item['request_payload'].upper()} "
                    f"RESP={item['response_payload'].upper()} status={decoded['status']}"
                )
                if decoded["status"] == "decoded":
                    definition = decoded["definition"]
                    source = definition["source"]
                    lines.append(
                        f"  - {definition['name']} | {definition['confidence']} | "
                        f"{source['title']} | {source['reference']} | {source['url']}"
                    )
                    for field in decoded["fields"]:
                        lines.append(
                            f"  - +{field['offset']} {field['name']}: "
                            f"{field['value'] if field['status'] == 'decoded' else 'TRUNCATED'} "
                            f"[{field['raw_hex'].upper()}] {field['unit']}"
                        )
                elif decoded["status"] == "unknown_definition":
                    lines.append(f"  - Raw data: {decoded.get('data', '').upper()}")

        lines += ["", "## Bookmarks"]
        lines.extend(f"- {key}: {note}" for key, note in self.bookmarks.items())
        if self.dbc_library.database is not None:
            coverage = self.dbc_library.decode_coverage(self.frames)
            lines += [
                "",
                "## DBC decode coverage",
                f"- Definition: {self.dbc_library.path.name}",
                f"- Messages / signals: {self.dbc_library.message_count} / {self.dbc_library.signal_count}",
                f"- Source file: {self.dbc_library.metadata.get('source_file', 'unknown')}",
                f"- Source origin: {self.dbc_library.metadata.get('source_origin', 'not recorded')}",
                f"- Vehicle applicability: {self.dbc_library.metadata.get('vehicle_applicability', 'unverified')}",
                f"- Physical bus: {self.dbc_library.metadata.get('bus_name', 'not recorded')}",
                f"- Evidence grade: {self.dbc_library.metadata.get('evidence_grade', 'unknown')}",
                f"- Verification: {self.dbc_library.metadata.get('verification_status', 'unverified')}",
                f"- Evidence notes: {self.dbc_library.metadata.get('verification_notes', 'none')}",
                f"- SHA-256: {self.dbc_library.metadata.get('sha256', 'unknown')}",
                f"- Matched / unmatched frames: {coverage['matched_frames']} / {coverage['unmatched_frames']}",
                "- Provenance: user-imported DBC; applicability to the selected vehicle is not assumed.",
            ]
            lines.extend(
                f"- {name}: n={stats['count']}, min={stats['min']:.6g}, mean={stats['mean']:.6g}, max={stats['max']:.6g} {stats.get('unit', '')}"
                for name, stats in sorted(coverage["signals"].items())
            )
        if self.reference_frames:
            lines += ["", f"Comparison capture contains {len(self.reference_frames)} frames."]
            if self.dbc_library.database is not None:
                dbc_comparison = self.dbc_library.compare_captures(
                    self.frames[-20000:], self.reference_frames[-20000:]
                )
                lines += [
                    "",
                    "## Decoded DBC signal comparison",
                    f"- Working capture frames: {dbc_comparison['working']['frame_count']}",
                    f"- Working matched / unmatched: {dbc_comparison['working']['matched_frames']} / {dbc_comparison['working']['unmatched_frames']}",
                    f"- Reference capture frames: {dbc_comparison['reference']['frame_count']}",
                    f"- Reference matched / unmatched: {dbc_comparison['reference']['matched_frames']} / {dbc_comparison['reference']['unmatched_frames']}",
                    f"- Interpretation: {dbc_comparison['interpretation']}",
                ]
                for item in dbc_comparison["signal_differences"]:
                    if item["status"] == "shared":
                        lines.append(
                            f"- {item['signal']}: working n={item['working']['count']} "
                            f"mean={item['working']['mean']:.6g}; reference n={item['reference']['count']} "
                            f"mean={item['reference']['mean']:.6g}; delta={item['mean_delta']:+.6g} "
                            f"{item['working']['unit']}"
                        )
                    else:
                        lines.append(f"- {item['signal']}: {item['status']}")
        return "\n".join(lines)

    def copy_analysis_packet(self):
        self._flush_pending_frames()
        if not self.frames:
            QMessageBox.information(self, "REA analysis packet", "Capture or import frames first.")
            return
        QApplication.clipboard().setText(self.build_analysis_packet())
        self.status_label.setText("REA analysis packet copied to clipboard.")

    def clear_data(self):
        answer = QMessageBox.question(
            self, "Clear research data",
            "Clear the working capture, comparison capture, sequence captures and bookmarks? Saved files are not affected.",
        )
        if answer != QMessageBox.Yes:
            return
        self.recording = False
        self.record_button.setText("Start research recording")
        self.frames.clear()
        self.live_preview.clear()
        self._pending_records.clear()
        self._pending_preview.clear()
        self.reference_frames.clear()
        self.reference_metadata = {}
        self.sequence_captures.clear()
        self.bookmarks.clear()
        self.markers.clear()
        self.metadata = {}
        self._recording_started_monotonic = None
        self.refresh_table()
        self.frame_detail.clear()
        self.status_label.setText("Research working set cleared. Saved capture files are unchanged.")
