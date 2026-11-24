"""Private protocol research workspace for FreeRov3r.

This module is intentionally separate from the standard diagnostic workflows.
It records and analyzes traffic already delivered by the selected CAN adapter;
it never transmits diagnostic requests or replays captured frames.
"""
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .dbc_support import DBCLibrary, DBCUnavailableError


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

    # Some capture sources may provide an application payload without ISO-TP PCI.
    service = data[0]
    if service in UDS_SERVICES:
        return "No ISO-TP PCI", f"Possible raw UDS: {UDS_SERVICES[service]}"
    return "Unclassified", "No reliable UDS classification"


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
        self.save_button = QPushButton("Save session")
        self.save_button.clicked.connect(self.save_session)
        controls.addWidget(self.save_button)
        self.load_dbc_button = QPushButton("Load DBC")
        self.load_dbc_button.setToolTip("Import a local DBC file for passive CAN signal decoding. No frames are transmitted.")
        self.load_dbc_button.clicked.connect(self.load_dbc)
        controls.addWidget(self.load_dbc_button)
        controls.addStretch(1)
        root.addLayout(controls)
        self.dbc_status = QLabel("DBC: none loaded. Install optional protocols support to decode imported DBC files.")
        self.dbc_status.setWordWrap(True)
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
        self.packet_button = QPushButton("Copy REA analysis packet")
        self.packet_button.clicked.connect(self.copy_analysis_packet)
        self.clear_button = QPushButton("Clear research data")
        self.clear_button.clicked.connect(self.clear_data)
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
            dbc_text = self._decode_dbc_record(record)
            values = [
                f'{record["timestamp"]:.6f}',
                f'{record["arbitration_id"]:08X}',
                "EXT" if record["extended"] else "STD",
                str(len(payload)),
                payload.hex(" ").upper(),
                iso,
                uds,
                dbc_text,
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
        return "; ".join(f"{name}={value}" for name, value in result.decoded.items())

    def load_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load CAN DBC definition", "", "DBC files (*.dbc)"
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
            "| Imported definition is unverified until matched to this vehicle."
        )
        self.refresh_table()

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
            coverage = self.dbc_library.decode_coverage(dataset)
            lines += [
                "",
                f"Loaded DBC: {self.dbc_library.path.name}",
                f"DBC frame matches: {coverage['matched_frames']:,} | unmatched: {coverage['unmatched_frames']:,}",
                "Decoded signal statistics (observed frames only):",
            ]
            lines.extend(
                f"  {name}: n={stats['count']} min={stats['min']:.5g} mean={stats['mean']:.5g} max={stats['max']:.5g}"
                for name, stats in sorted(coverage["signals"].items())
            )
            if not coverage["matched_frames"]:
                lines.append("  No matching frame IDs and formats in this working set.")
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

    def build_analysis_packet(self):
        self._flush_pending_frames()
        lines = [
            "# FreeRov3r protocol research packet",
            "",
            "Analyze only the captured evidence. Separate observations, hypotheses, and unknowns.",
            "Do not infer ECU identity or request/response direction from CAN ID alone.",
            "ISO-TP and UDS labels below are heuristic hints, not confirmed interpretations.",
            "Do not recommend replaying unknown frames or performing ECU writes.",
            "DBC signal values are decoded from imported definitions; vehicle applicability is unverified unless sourced and validated.",
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
        lines += ["", "## Operation markers"]
        lines.extend(
            f'- {m["elapsed_seconds"]:.3f}s | {m["operation"]} | {m["note"]}'
            for m in self.markers
        )
        lines += ["", "## Bookmarks"]
        lines.extend(f"- {key}: {note}" for key, note in self.bookmarks.items())
        if self.dbc_library.database is not None:
            coverage = self.dbc_library.decode_coverage(self.frames)
            lines += [
                "",
                "## DBC decode coverage",
                f"- Definition: {self.dbc_library.path.name}",
                f"- Messages / signals: {self.dbc_library.message_count} / {self.dbc_library.signal_count}",
                f"- Matched / unmatched frames: {coverage['matched_frames']} / {coverage['unmatched_frames']}",
                "- Provenance: user-imported DBC; applicability to the selected vehicle is not assumed.",
            ]
            lines.extend(
                f"- {name}: n={stats['count']}, min={stats['min']:.6g}, mean={stats['mean']:.6g}, max={stats['max']:.6g}"
                for name, stats in sorted(coverage["signals"].items())
            )
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
            "Clear the working capture, comparison capture and bookmarks? Saved files are not affected.",
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
        self.bookmarks.clear()
        self.markers.clear()
        self.metadata = {}
        self._recording_started_monotonic = None
        self.refresh_table()
        self.frame_detail.clear()
        self.status_label.setText("Research working set cleared. Saved capture files are unchanged.")
