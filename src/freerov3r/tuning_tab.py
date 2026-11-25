"""Conservative tuning workspace with local dual-location archive controls.

The archive controls only copy a firmware file that the user already has.
They do not acquire firmware from, or communicate with, a vehicle ECU.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from .firmware_archive import (
    ArchiveError,
    create_dual_backup,
    verify_dual_backup,
)


class TuningTab(QWidget):
    """Read-only calibration research and verified local archive workspace."""

    SETTINGS_PATH = Path.home() / ".freerov3r" / "tuning_archive_settings.json"
    ARCHIVE_SUBDIR = Path("FreeRov3r") / "recovery"

    def __init__(self, vin_provider=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self.source_file = ""
        self.internal_root = ""
        self.removable_root = ""
        self._load_archive_settings()
        self._build_ui()
        self.refresh_vehicle()
        self._refresh_archive_status()

    def _load_archive_settings(self):
        try:
            data = json.loads(self.SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.internal_root = str(data.get("internal_root", ""))
                self.removable_root = str(data.get("removable_root", ""))
        except (OSError, json.JSONDecodeError):
            pass

    def _save_archive_settings(self):
        try:
            self.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.SETTINGS_PATH.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({
                    "internal_root": self.internal_root,
                    "removable_root": self.removable_root,
                }, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.SETTINGS_PATH)
        except OSError as exc:
            QMessageBox.warning(self, "Settings not saved", str(exc))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        heading = QLabel("ENGINE CALIBRATION WORKSPACE")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)

        intro = QLabel(
            "Research and document the vehicle's engine-control calibration. "
            "This workspace does not send CAN commands, unlock ECUs, write "
            "calibration data, or flash modules."
        )
        intro.setWordWrap(True)
        intro.setObjectName("welcomeSubtitle")
        root.addWidget(intro)

        identity = QGroupBox("VEHICLE / ECU IDENTITY")
        identity_form = QFormLayout(identity)
        self.vin_value = QLabel("Not identified")
        self.vin_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.engine_value = QLabel("Land Rover L319 5.0L petrol V8 (project default; unverified)")
        self.ecu_value = QLabel("Not yet identified from a vehicle scan")
        self.calibration_value = QLabel("Unknown")
        identity_form.addRow("VIN:", self.vin_value)
        identity_form.addRow("Engine profile:", self.engine_value)
        identity_form.addRow("ECU hardware/software:", self.ecu_value)
        identity_form.addRow("Calibration ID:", self.calibration_value)
        root.addWidget(identity)

        archive_group = QGroupBox("ORIGINAL FIRMWARE ARCHIVE")
        archive_layout = QVBoxLayout(archive_group)
        archive_notice = QLabel(
            "Offline file archive only. Select a firmware file already obtained "
            "by another method. FreeRov3r does not read firmware from the ECU here. "
            "Both destinations must be separate and independently writable."
        )
        archive_notice.setWordWrap(True)
        archive_notice.setObjectName("statusWarning")
        archive_layout.addWidget(archive_notice)

        source_row = QHBoxLayout()
        self.source_value = QLineEdit()
        self.source_value.setReadOnly(True)
        self.source_value.setPlaceholderText("No firmware file selected")
        source_button = QPushButton("Select firmware file…")
        source_button.clicked.connect(self.select_source_file)
        source_row.addWidget(self.source_value, 1)
        source_row.addWidget(source_button)
        archive_layout.addLayout(source_row)

        self.internal_value = QLineEdit(self.internal_root)
        self.internal_value.setReadOnly(True)
        internal_button = QPushButton("Choose internal drive…")
        internal_button.clicked.connect(self.select_internal_root)
        internal_row = QHBoxLayout()
        internal_row.addWidget(self.internal_value, 1)
        internal_row.addWidget(internal_button)
        archive_layout.addLayout(internal_row)

        self.removable_value = QLineEdit(self.removable_root)
        self.removable_value.setReadOnly(True)
        removable_button = QPushButton("Choose USB / removable drive…")
        removable_button.clicked.connect(self.select_removable_root)
        removable_row = QHBoxLayout()
        removable_row.addWidget(self.removable_value, 1)
        removable_row.addWidget(removable_button)
        archive_layout.addLayout(removable_row)

        metadata = QFormLayout()
        self.module_input = QLineEdit("ECM")
        self.hardware_input = QLineEdit()
        self.hardware_input.setPlaceholderText("Unknown until confirmed")
        self.software_input = QLineEdit()
        self.software_input.setPlaceholderText("Unknown until confirmed")
        self.calibration_input = QLineEdit()
        self.calibration_input.setPlaceholderText("Unknown until confirmed")
        metadata.addRow("Module:", self.module_input)
        metadata.addRow("Hardware ID:", self.hardware_input)
        metadata.addRow("Software ID:", self.software_input)
        metadata.addRow("Calibration ID:", self.calibration_input)
        archive_layout.addLayout(metadata)

        action_row = QHBoxLayout()
        self.archive_button = QPushButton("Create dual verified archive")
        self.archive_button.clicked.connect(self.create_archive)
        self.verify_button = QPushButton("Verify existing archive")
        self.verify_button.clicked.connect(self.verify_archive)
        action_row.addWidget(self.archive_button)
        action_row.addWidget(self.verify_button)
        action_row.addStretch(1)
        archive_layout.addLayout(action_row)

        self.archive_status = QLabel("Archive not yet checked")
        self.archive_status.setWordWrap(True)
        self.archive_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        archive_layout.addWidget(self.archive_status)
        root.addWidget(archive_group)

        roadmap = QGroupBox("CALIBRATION WORKFLOW")
        roadmap_layout = QFormLayout(roadmap)
        stages = [
            ("1. Identify", "Read ECU part number, hardware ID, software ID and calibration ID."),
            ("2. Baseline", "Record DTCs, live data, adaptations and operating conditions."),
            ("3. Backup", "Preserve the original file in two locations and establish a recovery plan."),
            ("4. Analyze", "Identify map structures, axes, units, checksums and calibration dependencies."),
            ("5. Validate", "Compare changes offline and validate on suitable bench/dyno equipment."),
            ("6. Program", "Blocked until exact compatibility, recovery method, tools and prerequisites are validated."),
        ]
        for name, description in stages:
            label = QLabel(description)
            label.setWordWrap(True)
            roadmap_layout.addRow(name, label)
        root.addWidget(roadmap)

        safety = QLabel(
            "A verified pair of files is not proof that an ECU can be recovered. "
            "Recovery hardware, credentials, exact module compatibility and a "
            "validated module-specific recovery procedure remain separate requirements."
        )
        safety.setWordWrap(True)
        safety.setObjectName("statusWarning")
        root.addWidget(safety)

        notes_group = QGroupBox("TUNING RESEARCH LOG")
        notes_layout = QVBoxLayout(notes_group)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Record an observation, test condition, or calibration question...")
        self.note_input.returnPressed.connect(self.add_observation)
        notes_layout.addWidget(self.note_input)
        actions = QHBoxLayout()
        add_button = QPushButton("Log observation")
        add_button.clicked.connect(self.add_observation)
        export_button = QPushButton("Export research log")
        export_button.clicked.connect(self.export_log)
        actions.addWidget(add_button)
        actions.addWidget(export_button)
        actions.addStretch(1)
        notes_layout.addLayout(actions)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("No tuning observations recorded in this session.")
        self.log.setMinimumHeight(150)
        notes_layout.addWidget(self.log)
        root.addWidget(notes_group)
        root.addStretch(1)

    def refresh_vehicle(self):
        vin = self.vin_provider()
        self.vin_value.setText(str(vin) if vin else "Not identified")

    def select_source_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an existing firmware file", "",
            "Firmware / binary files (*.bin *.rom *.hex *.mot *.s19 *.srec);;All files (*)",
        )
        if path:
            self.source_file = path
            self.source_value.setText(path)

    def _select_root(self, title: str) -> str:
        return QFileDialog.getExistingDirectory(self, title, "")

    def select_internal_root(self):
        path = self._select_root("Choose internal archive destination")
        if path:
            self.internal_root = path
            self.internal_value.setText(path)
            self._save_archive_settings()
            self._refresh_archive_status()

    def select_removable_root(self):
        path = self._select_root("Choose USB / removable archive destination")
        if path:
            self.removable_root = path
            self.removable_value.setText(path)
            self._save_archive_settings()
            self._refresh_archive_status()

    def _archive_paths(self):
        if not self.internal_root or not self.removable_root:
            raise ArchiveError("Select both an internal destination and a removable destination.")
        return (
            Path(self.internal_root) / self.ARCHIVE_SUBDIR,
            Path(self.removable_root) / self.ARCHIVE_SUBDIR,
        )

    def _refresh_archive_status(self):
        if not self.internal_root or not self.removable_root:
            self.archive_status.setText("Select two separate destinations to enable archive verification.")
            return
        try:
            internal, removable = self._archive_paths()
            if (internal / "freerov3r-recovery-manifest.json").is_file() and (
                removable / "freerov3r-recovery-manifest.json"
            ).is_file():
                self.archive_status.setText("Archive manifests found. Run verification before relying on these copies.")
            else:
                self.archive_status.setText("No complete dual archive detected at the selected destinations.")
        except ArchiveError as exc:
            self.archive_status.setText(str(exc))

    def create_archive(self):
        if not self.source_file:
            QMessageBox.warning(self, "Firmware file required", "Select an existing firmware file first.")
            return
        if not self.internal_root or not self.removable_root:
            QMessageBox.warning(self, "Destinations required", "Choose both the internal drive and removable drive.")
            return
        vin = self.vin_provider()
        metadata = {
            "vin": vin or "not_identified",
            "module": self.module_input.text().strip() or "unknown",
            "hardware_id": self.hardware_input.text().strip() or "unknown",
            "software_id": self.software_input.text().strip() or "unknown",
            "calibration_id": self.calibration_input.text().strip() or "unknown",
            "acquisition_note": "User-selected existing file; acquisition method not established by this archive operation.",
        }
        try:
            result = create_dual_backup(
                self.source_file,
                self.internal_root,
                self.removable_root,
                archive_subdir=self.ARCHIVE_SUBDIR,
                metadata=metadata,
            )
        except (ArchiveError, OSError) as exc:
            self.archive_status.setText(f"ARCHIVE FAILED: {exc}")
            QMessageBox.warning(self, "Archive failed", str(exc))
            return
        self.archive_status.setText(
            f"VERIFIED: {len(result['files'])} file(s). Both archived copies were reopened "
            "and matched against the manifest SHA-256 and file size."
        )
        self.log.append(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"Dual archive verified: {Path(self.source_file).name}; VIN={metadata['vin']}; "
            f"module={metadata['module']}; SHA-256={result['files'][0]['copies']['internal']['sha256']}"
        )
        QMessageBox.information(self, "Archive verified", "Both copies were read back and hash-verified.")

    def verify_archive(self):
        try:
            internal, removable = self._archive_paths()
            result = verify_dual_backup(internal, removable)
        except (ArchiveError, OSError) as exc:
            self.archive_status.setText(f"VERIFICATION FAILED: {exc}")
            QMessageBox.warning(self, "Verification failed", str(exc))
            return
        if result["verified"]:
            self.archive_status.setText(
                f"VERIFIED: {len(result['files'])} file(s). Both copies match the shared manifest."
            )
            QMessageBox.information(self, "Archive verified", "Both archive copies match the manifest.")
        else:
            self.archive_status.setText("VERIFICATION FAILED: one or more archived files do not match.")
            QMessageBox.warning(
                self, "Archive mismatch",
                "At least one archived copy is missing, unreadable, or has a hash/size mismatch.",
            )

    def add_observation(self):
        note = self.note_input.text().strip()
        if not note:
            return
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.log.append(f"[{timestamp}] {note}")
        self.note_input.clear()

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export tuning research log", "freerov3r_tuning_log.txt",
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("FreeRov3r Tuning Research Log\n")
                handle.write(f"VIN: {self.vin_provider() or 'Not identified'}\n")
                handle.write("Mode: Read-only research / local archive management\n")
                handle.write(f"Internal archive root: {self.internal_root or 'Not selected'}\n")
                handle.write(f"Removable archive root: {self.removable_root or 'Not selected'}\n\n")
                handle.write(self.log.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
