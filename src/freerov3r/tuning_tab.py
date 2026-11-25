"""Conservative tuning workspace foundation.

This first version is deliberately observational. It does not transmit CAN,
unlock ECUs, alter calibration data, or flash modules.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)


class TuningTab(QWidget):
    """Read-only calibration research workspace with an exportable lab log."""

    def __init__(self, vin_provider=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self._build_ui()
        self.refresh_vehicle()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        heading = QLabel("ENGINE CALIBRATION WORKSPACE")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)

        intro = QLabel(
            "Research and document the vehicle's engine-control calibration. "
            "This workspace is currently read-only: no CAN commands, ECU unlock "
            "requests, calibration writes, or flashing are performed."
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

        roadmap = QGroupBox("CALIBRATION WORKFLOW")
        roadmap_layout = QFormLayout(roadmap)
        stages = [
            ("1. Identify", "Read ECU part number, hardware ID, software ID and calibration ID."),
            ("2. Baseline", "Record DTCs, live data, adaptations and operating conditions."),
            ("3. Backup", "Obtain and verify an original calibration read with a recovery plan."),
            ("4. Analyze", "Identify map structures, axes, units, checksums and calibration dependencies."),
            ("5. Validate", "Compare changes offline and validate on suitable bench/dyno equipment."),
            ("6. Program", "Only after protocol, authorization, power stability and recovery are established."),
        ]
        for name, description in stages:
            label = QLabel(description)
            label.setWordWrap(True)
            roadmap_layout.addRow(name, label)
        root.addWidget(roadmap)

        safety = QLabel(
            "CURRENT CAPABILITY: documentation and offline research only. "
            "ECU unlocking and flashing are future development stages, not "
            "available functions. Unknown map definitions or unsupported "
            "write procedures must never be guessed."
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
                handle.write("Mode: Read-only research\n\n")
                handle.write(self.log.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
