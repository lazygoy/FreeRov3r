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

from .archive_registry import ArchiveRegistryError, load_archive_records, record_archive, record_verification

from .firmware_archive import (
    ArchiveError,
    create_dual_backup,
    inspect_destination,
    verify_dual_backup,
)


class TuningTab(QWidget):
    """Read-only calibration research and verified local archive workspace."""

    SETTINGS_PATH = Path.home() / ".freerov3r" / "tuning_archive_settings.json"
    ARCHIVE_SUBDIR = Path("FreeRov3r") / "recovery"
    REGISTRY_PATH = Path.home() / ".freerov3r" / "firmware_archive_registry.json"

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
        self.refresh_archive_registry()

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

        self.internal_capacity = QLabel("Capacity not checked")
        self.internal_capacity.setWordWrap(True)
        archive_layout.addWidget(self.internal_capacity)

        self.removable_value = QLineEdit(self.removable_root)
        self.removable_value.setReadOnly(True)
        removable_button = QPushButton("Choose USB / removable drive…")
        removable_button.clicked.connect(self.select_removable_root)
        removable_row = QHBoxLayout()
        removable_row.addWidget(self.removable_value, 1)
        removable_row.addWidget(removable_button)
        archive_layout.addLayout(removable_row)
        self.removable_capacity = QLabel("Capacity not checked")
        self.removable_capacity.setWordWrap(True)
        archive_layout.addWidget(self.removable_capacity)

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
        self.storage_check_button = QPushButton("Check storage capacity / write access")
        self.storage_check_button.clicked.connect(self.check_storage)
        action_row.addWidget(self.storage_check_button)
        self.archive_button = QPushButton("Create dual verified archive")
        self.archive_button.clicked.connect(self.create_archive)
        self.verify_button = QPushButton("Verify existing archive")
        self.verify_button.clicked.connect(self.verify_archive)
        action_row.addWidget(self.archive_button)
        action_row.addWidget(self.verify_button)
        action_row.addStretch(1)
        archive_layout.addLayout(action_row)

        registry_group = QGroupBox("PERSISTENT BACKUP REGISTER")
        registry_layout = QVBoxLayout(registry_group)
        self.registry_view = QTextEdit()
        self.registry_view.setReadOnly(True)
        self.registry_view.setMaximumHeight(125)
        self.registry_view.setPlaceholderText("No archive records saved on this computer.")
        registry_layout.addWidget(self.registry_view)
        refresh_registry_button = QPushButton("Refresh backup register")
        refresh_registry_button.clicked.connect(self.refresh_archive_registry)
        registry_layout.addWidget(refresh_registry_button)
        archive_layout.addWidget(registry_group)

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
            self._refresh_archive_status()

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
        self.internal_capacity.setText("Capacity not checked" if self.internal_root else "Internal destination not selected")
        self.removable_capacity.setText("Capacity not checked" if self.removable_root else "Removable destination not selected")
        if not self.internal_root or not self.removable_root:
            self.archive_status.setText("Select two separate destinations to enable archive verification.")
            return
        try:
            internal, removable = self._archive_paths()
            required = Path(self.source_file).stat().st_size if self.source_file and Path(self.source_file).is_file() else 0
            for root, label in ((self.internal_root, self.internal_capacity), (self.removable_root, self.removable_capacity)):
                try:
                    info = inspect_destination(root, required_bytes=required)
                    label.setText(f"{info['free_bytes']:,} bytes free of {info['total_bytes']:,}; {required:,} required for selected file.")
                except (ArchiveError, OSError) as exc:
                    label.setText(f"Storage check unavailable: {exc}")
            if (internal / "freerov3r-recovery-manifest.json").is_file() and (
                removable / "freerov3r-recovery-manifest.json"
            ).is_file():
                self.archive_status.setText("Archive manifests found. Run verification before relying on these copies.")
            else:
                self.archive_status.setText("No complete dual archive detected at the selected destinations.")
        except ArchiveError as exc:
            self.archive_status.setText(str(exc))

    def check_storage(self):
        if not self.internal_root or not self.removable_root:
            QMessageBox.warning(self, "Destinations required", "Choose both archive destinations first.")
            return
        required = 0
        if self.source_file:
            try:
                required = Path(self.source_file).stat().st_size
            except OSError as exc:
                QMessageBox.warning(self, "Source unavailable", str(exc))
                return
        try:
            results = []
            for label, root in (("Internal", self.internal_root), ("Removable", self.removable_root)):
                info = inspect_destination(root, required_bytes=required, test_write=True)
                results.append(
                    f"{label}: {info['path']}\n"
                    f"Free: {info['free_bytes']:,} / {info['total_bytes']:,} bytes; "
                    f"required: {required:,}; write/read test: passed"
                )
            self.internal_capacity.setText(results[0].replace("\n", " | "))
            self.removable_capacity.setText(results[1].replace("\n", " | "))
            self.archive_status.setText("Storage preflight passed. This checks current free space and write/read access only.")
            QMessageBox.information(self, "Storage preflight passed", "\n\n".join(results))
        except (ArchiveError, OSError) as exc:
            self.archive_status.setText(f"STORAGE PREFLIGHT FAILED: {exc}")
            QMessageBox.warning(self, "Storage preflight failed", str(exc))

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
        try:
            record_archive(self.REGISTRY_PATH, result)
            self.refresh_archive_registry()
        except ArchiveRegistryError as exc:
            self.archive_status.setText(f"ARCHIVE VERIFIED, BUT REGISTER UPDATE FAILED: {exc}")
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
        try:
            record_verification(
                self.REGISTRY_PATH,
                internal,
                removable,
                result,
            )
            self.refresh_archive_registry()
        except ArchiveRegistryError as exc:
            self.archive_status.setText(f"VERIFICATION FINISHED, BUT REGISTER UPDATE FAILED: {exc}")
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

    def refresh_archive_registry(self):
        try:
            records = load_archive_records(self.REGISTRY_PATH)
        except ArchiveRegistryError as exc:
            self.registry_view.setPlainText(f"REGISTER ERROR: {exc}")
            return
        if not records:
            self.registry_view.setPlainText("No backup records saved on this computer.")
            return
        lines = []
        for item in reversed(records[-50:]):
            lines.append(
                f"{item.get('timestamp_utc', 'unknown time')} | "
                f"VIN {item.get('vin', 'unknown')} | {item.get('module', 'unknown')} | "
                f"{item.get('status', 'unknown')} | {item.get('file_name', 'unnamed')} | "
                f"SHA-256 {item.get('sha256', 'unknown')}"
            )
            lines.append(
                f"  Internal: {item.get('internal_archive', 'unknown')} | "
                f"Removable: {item.get('removable_archive', 'unknown')}"
            )
            if item.get("last_verified_utc"):
                lines.append(f"  Last verified: {item['last_verified_utc']}")
        self.registry_view.setPlainText("\n".join(lines))

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
