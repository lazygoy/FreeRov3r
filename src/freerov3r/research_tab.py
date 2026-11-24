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
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
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

    groups = {}
    for capture_index, capture in enumerate(captures or []):
        if not isinstance(capture, dict):
            continue
        capture_name = str(capture.get("name") or f"Capture {capture_index + 1}")
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
            markers.append((center, str(marker.get("operation") or "Unspecified")))

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
            group["capture_names"].add(capture_name)

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

def _frame_record(frame):
    return {
        "timestamp": float(getattr(frame, "timestamp", 0.0) or 0.0),
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
        return {
            "timestamp": float(record.get("timestamp", record.get("time", 0.0)) or 0.0),
            "arbitration_id": arbitration_id,
            "extended": extended,
            "data": payload.hex(),
            "channel": record.get("channel"),
        }
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
        self.sequence_captures = []
        self.bookmarks = {}
        self.markers = []
        self.metadata = {}
        self._recording_started_monotonic = None
        self.recording = False
        self.live_enabled = True
        self._pending_records = []
        self._pending_preview = []

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._flush_pending_frames)
        self.refresh_timer.start()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        intro = QGroupBox("PROTOCOL RESEARCH · DEVELOPMENT ONLY")
        intro_layout = QVBoxLayout(intro)
        self.status_label = QLabel(
            "This tab only observes incoming frames. It never transmits or replays; the selected main adapter may have its own active polling behavior."
        )
        self.status_label.setWordWrap(True)
        intro_layout.addWidget(self.status_label)
        root.addWidget(intro)

        session_box = QGroupBox("RESEARCH SESSION")
        session_form = QFormLayout(session_box)
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
        session_form.addRow("Session:", self.session_name)
        session_form.addRow("Scanner operation:", self.operation)
        session_form.addRow("Operator notes:", self.notes)
        session_form.addRow("Vehicle:", self.vin_label)
        root.addWidget(session_box)

        controls = QHBoxLayout()
        self.live_check = QCheckBox("Show incoming live frames")
        self.live_check.setChecked(True)
        self.live_check.toggled.connect(self._set_live_enabled)
        controls.addWidget(self.live_check)
        self.record_button = QPushButton("Start research recording")
        self.record_button.clicked.connect(self.toggle_recording)
        controls.addWidget(self.record_button)
        self.marker_button = QPushButton("Mark scanner action")
        self.marker_button.clicked.connect(self.mark_action)
        controls.addWidget(self.marker_button)
        self.import_button = QPushButton("Import capture")
        self.import_button.clicked.connect(self.import_capture)
        controls.addWidget(self.import_button)
        self.reference_button = QPushButton("Load comparison capture")
        self.reference_button.clicked.connect(self.load_reference)
        controls.addWidget(self.reference_button)
        self.sequence_load_button = QPushButton("Load sequence captures")
        self.sequence_load_button.clicked.connect(self.load_sequence_captures)
        controls.addWidget(self.sequence_load_button)
        self.save_button = QPushButton("Save session")
        self.save_button.clicked.connect(self.save_session)
        controls.addWidget(self.save_button)
        controls.addStretch(1)
        root.addLayout(controls)

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
        self.frame_table = QTableWidget(0, 7)
        self.frame_table.setHorizontalHeaderLabels([
            "Timestamp", "CAN ID", "Format", "DLC", "Payload", "ISO-TP", "UDS hint"
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
        self.frame_detail.setMaximumHeight(115)
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
        self.summary.setMinimumHeight(140)
        self.summary.setPlaceholderText("Frame counts, frequent IDs, protocol hints and comparison results appear here.")
        analysis_layout.addWidget(self.summary)
        lower_layout.addWidget(analysis_box, 1)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
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
        self.packet_button = QPushButton("Copy REA analysis packet")
        self.packet_button.clicked.connect(self.copy_analysis_packet)
        self.clear_button = QPushButton("Clear research data")
        self.clear_button.clicked.connect(self.clear_data)
        footer.addWidget(self.isotp_button)
        footer.addWidget(self.pair_button)
        footer.addWidget(self.address_map_button)
        footer.addWidget(self.marker_analysis_button)
        footer.addWidget(self.sequence_analysis_button)
        footer.addWidget(self.packet_button)
        footer.addWidget(self.clear_button)
        footer.addStretch(1)
        self.count_label = QLabel("0 displayed · 0 recorded")
        footer.addWidget(self.count_label)
        root.addLayout(footer)

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
            f'Channel: {record.get("channel") or "unknown"}'
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
            _, records = load_capture_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Comparison load failed", str(exc))
            return
        self.reference_frames = records
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
            },
            "frames": self.frames,
            "bookmarks": self.bookmarks,
            "markers": self.markers,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status_label.setText(f"Saved {len(self.frames):,} frames to {Path(path).name}")

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
            "## Session context",
            json.dumps({
                **self.metadata,
                "session_name": self.session_name.text().strip(),
                "operation": self.operation.currentText(),
                "notes": self.notes.text().strip(),
            }, indent=2),
            "",
            f"## Capture ({len(self.frames)} frames)",
            "| Timestamp | CAN ID | Format | Payload | ISO-TP | UDS hint |",
            "|---:|---:|---|---|---|---|",
        ]
        for record in self.frames[:20000]:
            iso, uds = classify_can_payload(bytes.fromhex(record["data"]))
            lines.append(
                f'| {record["timestamp"]:.6f} | 0x{record["arbitration_id"]:X} | '
                f'{"EXT" if record["extended"] else "STD"} | {record["data"].upper()} | {iso} | {uds} |'
            )
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
        lines += ["", "## Bookmarks"]
        lines.extend(f"- {key}: {note}" for key, note in self.bookmarks.items())
        if self.reference_frames:
            lines += ["", f"Comparison capture contains {len(self.reference_frames)} frames."]
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
        self.sequence_captures.clear()
        self.bookmarks.clear()
        self.markers.clear()
        self.metadata = {}
        self._recording_started_monotonic = None
        self.refresh_table()
        self.frame_detail.clear()
        self.status_label.setText("Research working set cleared. Saved capture files are unchanged.")
