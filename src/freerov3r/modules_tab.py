"""Synthetic module diagnostics workspace."""

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .core.vehicle.knowledge import VehicleKnowledgeStore


class ModulesTab(QWidget):
    def __init__(self, network: SimulatedModuleNetwork, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.network = network
        self.simulation_enabled = False
        self.current_module_code = None
        self.vehicle_context = None
        self.knowledge_store = VehicleKnowledgeStore(
            Path.home() / ".freerov3r" / "vehicle" / "knowledge.json"
        )
        layout = QVBoxLayout(self)
        note = QLabel("<b>Module diagnostics simulator</b><br>Synthetic L319-style module categories and example DTCs. This is a test fixture, not a scan of a real vehicle. Real ECU addressing and UDS services are not enabled.")
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        self.scan_one_btn = QPushButton("Scan Selected Module")
        self.scan_one_btn.clicked.connect(self.scan_selected)
        actions.addWidget(self.scan_one_btn)
        self.scan_all_btn = QPushButton("Scan All Modules")
        self.scan_all_btn.clicked.connect(self.scan_all)
        actions.addWidget(self.scan_all_btn)
        self.health_report_btn = QPushButton("Generate Health Report")
        self.health_report_btn.setObjectName("primaryButton")
        self.health_report_btn.setToolTip(
            "Scan the complete module inventory and create a concise vehicle health summary."
        )
        self.health_report_btn.clicked.connect(self.generate_health_report)
        actions.addWidget(self.health_report_btn)
        self.clear_module_btn = QPushButton("Clear Selected Module")
        self.clear_module_btn.clicked.connect(self.clear_module)
        actions.addWidget(self.clear_module_btn)
        self.clear_all_btn = QPushButton("Clear All Simulated DTCs")
        self.clear_all_btn.clicked.connect(self.clear_all)
        actions.addWidget(self.clear_all_btn)
        layout.addLayout(actions)

        evidence_box = QGroupBox("RETAINED VEHICLE NETWORK EVIDENCE")
        evidence_layout = QVBoxLayout(evidence_box)
        evidence_note = QLabel(
            "Passive capture observations only. A CAN ID or probable UDS responder is not a confirmed ECU identity. "
            "This inventory does not represent a live scan."
        )
        evidence_note.setWordWrap(True)
        evidence_layout.addWidget(evidence_note)
        self.observed_nodes_table = QTableWidget(0, 7)
        self.observed_nodes_table.setHorizontalHeaderLabels([
            "Channel", "CAN ID", "Format", "Frames", "Observed role",
            "Captures", "Evidence",
        ])
        self.observed_nodes_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.observed_nodes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.observed_nodes_table.setSelectionBehavior(QTableWidget.SelectRows)
        evidence_layout.addWidget(self.observed_nodes_table)
        self.observed_nodes_status = QLabel("Select a vehicle to load retained network observations.")
        evidence_layout.addWidget(self.observed_nodes_status)

        self.verified_modules_table = QTableWidget(0, 4)
        self.verified_modules_table.setHorizontalHeaderLabels([
            "Verified module identity", "Network", "Status", "Source",
        ])
        self.verified_modules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.verified_modules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        evidence_layout.addWidget(QLabel("Independently verified module identities"))
        evidence_layout.addWidget(self.verified_modules_table)
        layout.addWidget(evidence_box)

        split = QHBoxLayout()
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Category / module", "DTCs", "Last scan"])
        self.module_tree.setMinimumWidth(230)
        self.module_tree.itemSelectionChanged.connect(self.show_selected_module)
        split.addWidget(self.module_tree, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Diagnostic trouble codes"))
        self.dtc_table = QTableWidget(0, 4)
        self.dtc_table.setHorizontalHeaderLabels(["Code", "Description", "Status", "Severity"])
        self.dtc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.dtc_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dtc_table.setSelectionMode(QTableWidget.SingleSelection)
        right.addWidget(self.dtc_table, 2)
        self.clear_code_btn = QPushButton("Clear Selected DTC")
        self.clear_code_btn.clicked.connect(self.clear_selected_code)
        right.addWidget(self.clear_code_btn)
        self.result_log = QPlainTextEdit()
        self.result_log.setReadOnly(True)
        self.result_log.setMaximumBlockCount(1000)
        right.addWidget(self.result_log, 1)
        right.addWidget(QLabel("VEHICLE HEALTH REPORT"))
        self.health_report = QPlainTextEdit()
        self.health_report.setReadOnly(True)
        self.health_report.setMinimumHeight(105)
        self.health_report.setPlaceholderText(
            "Run Generate Health Report for a module-by-module summary."
        )
        right.addWidget(self.health_report, 1)
        report_export_row = QHBoxLayout()
        self.export_health_report_btn = QPushButton("Export Health Report")
        self.export_health_report_btn.clicked.connect(self.export_health_report)
        report_export_row.addWidget(self.export_health_report_btn)
        report_export_row.addStretch()
        right.addLayout(report_export_row)
        split.addLayout(right, 2)
        layout.addLayout(split)
        self.set_simulation_enabled(False)
        self.refresh_tree()

    def set_vehicle_context(self, context):
        self.vehicle_context = context
        self.refresh_evidence_inventory()

    def refresh_evidence_inventory(self):
        """Display retained observations separately from synthetic module fixtures."""
        self.observed_nodes_table.setRowCount(0)
        self.verified_modules_table.setRowCount(0)
        if self.vehicle_context is None:
            self.observed_nodes_status.setText("No vehicle context selected.")
            return
        profile_id = str(getattr(self.vehicle_context, "profile_id", "generic") or "generic")
        vehicle = getattr(self.vehicle_context, "vehicle", {}) or {}
        try:
            model_year = int(vehicle.get("model_year"))
        except (TypeError, ValueError):
            model_year = None
        engine_id = vehicle.get("engine_id")
        try:
            inventory = self.knowledge_store.module_inventory(
                profile_id, model_year=model_year, engine_id=engine_id
            )
        except (OSError, ValueError) as exc:
            self.observed_nodes_status.setText(f"Unable to load retained vehicle evidence: {exc}")
            return

        nodes = inventory["observed_can_nodes"]
        self.observed_nodes_table.setRowCount(len(nodes))
        for row, record in enumerate(nodes):
            data = record.get("data") or {}
            values = (
                str(data.get("channel") or "Unknown"),
                f"0x{int(data.get('can_id', 0)):X}",
                "EXT" if data.get("extended") else "STD",
                str(data.get("frame_count", 0)),
                str(data.get("role") or "observed_can_node"),
                str(len(record.get("source_capture_ids") or [])),
                str(record.get("status") or "observed").upper(),
            )
            tooltip = "\n".join((
                str(data.get("interpretation") or ""),
                "Capture IDs: " + ", ".join(record.get("source_capture_ids") or []),
                "Request IDs: " + ", ".join(
                    f"0x{int(value):X}" for value in data.get("request_ids", [])
                ),
                "Services: " + ", ".join(
                    f"0x{int(value):02X}" for value in data.get("services", [])
                ),
                "Physical ECU identity confirmed: No",
            ))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(tooltip)
                self.observed_nodes_table.setItem(row, column, cell)

        verified = inventory["verified_module_identities"]
        self.verified_modules_table.setRowCount(len(verified))
        for row, record in enumerate(verified):
            data = record.get("data") or {}
            values = (
                str(data.get("name") or record.get("artifact_key") or "Unnamed module"),
                str(data.get("network") or "Not specified"),
                str(record.get("status") or "").upper(),
                str(record.get("source_reference") or ", ".join(
                    record.get("source_references") or []
                )),
            )
            for column, value in enumerate(values):
                self.verified_modules_table.setItem(row, column, QTableWidgetItem(value))

        self.observed_nodes_status.setText(
            f"{len(nodes)} retained CAN node observation(s); "
            f"{len(verified)} verified module identity record(s). "
            "No live ECU scan was performed."
        )

    def set_network(self, network: SimulatedModuleNetwork):
        self.network = network
        self.current_module_code = None
        self.refresh_tree()
        self.dtc_table.setRowCount(0)

    def set_simulation_enabled(self, enabled: bool):
        self.simulation_enabled = bool(enabled)
        for control in (self.scan_one_btn, self.scan_all_btn, self.clear_module_btn, self.clear_all_btn, self.clear_code_btn):
            control.setEnabled(self.simulation_enabled)
        if enabled:
            self.result_log.appendPlainText("SIMULATOR ACTIVE: operations affect synthetic in-memory data only.")
        else:
            self.result_log.appendPlainText("Simulator inactive. Select the simulated vehicle interface to enable module operations.")

    def refresh_tree(self):
        selected = self.current_module_code
        self.module_tree.clear()
        groups = {}
        for module in self.network.modules:
            parent = groups.get(module.category)
            if parent is None:
                parent = QTreeWidgetItem([module.category, "", ""])
                self.module_tree.addTopLevelItem(parent)
                groups[module.category] = parent
            item = QTreeWidgetItem([f"{module.code} — {module.name}", str(len(module.dtcs)), module.last_scan or "Not scanned"])
            item.setData(0, Qt.UserRole, module.code)
            parent.addChild(item)
            if module.code == selected:
                self.module_tree.setCurrentItem(item)
        self.module_tree.expandAll()
        refresh_overview = getattr(self, "network_overview_refresh", None)
        if refresh_overview:
            refresh_overview()

    def _selected_code(self):
        item = self.module_tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def show_selected_module(self):
        code = self._selected_code()
        if not code:
            self.dtc_table.setRowCount(0)
            return
        self.current_module_code = code
        module = self.network.get_module(code)
        self.dtc_table.setRowCount(len(module.dtcs))
        for row, dtc in enumerate(module.dtcs):
            for col, value in enumerate((dtc.code, dtc.description, dtc.status, dtc.severity)):
                self.dtc_table.setItem(row, col, QTableWidgetItem(value))

    def _require_vehicle(self):
        vin = self.vin_provider()
        if not vin:
            QMessageBox.warning(self, "Vehicle not selected", "Add and select a vehicle by VIN in the Sensors tab before running or clearing diagnostics.")
            return None
        return vin

    def scan_selected(self):
        code = self._selected_code()
        if not self.simulation_enabled or not code:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        module = self.network.scan_module(code)
        self.result_log.appendPlainText(f"SCAN {code}: response received, {len(module.dtcs)} DTC(s).")
        self.history_callback("module_scan", f"{code} scan completed", {
            "module": code, "module_name": module.name, "category": module.category,
            "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs],
        }, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def scan_all(self):
        if not self.simulation_enabled:
            return
        vin = self.vin_provider()
        if not vin:
            QMessageBox.warning(self, "Vehicle not selected", "Add and select a vehicle by VIN in the Sensors tab before recording diagnostic history.")
            return
        modules = self.network.scan_all()
        total = sum(len(module.dtcs) for module in modules)
        self.result_log.appendPlainText(f"FULL SCAN: {len(modules)} simulated modules responded; {total} DTC(s) found.")
        self.history_callback("full_module_scan", "Full module scan completed", {
            "modules_scanned": len(modules), "dtc_count": total,
            "modules": [{"code": m.code, "name": m.name, "category": m.category,
                        "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in m.dtcs]}
                       for m in modules],
        }, vin=vin)
        self.refresh_tree()

    def generate_health_report(self):
        """Run the available complete inventory check and render an evidence-labelled report."""
        vin = self.vin_provider()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.simulation_enabled:
            report = [
                "FREEROV3R VEHICLE HEALTH REPORT",
                f"Generated: {timestamp}",
                f"Vehicle VIN: {vin or 'Not selected'}",
                "",
                "RESULT: LIVE MODULE SCAN NOT AVAILABLE",
                "",
                "No physical vehicle modules were interrogated. The current live hardware "
                "connection supports passive CAN capture only; live ECU addressing and "
                "module diagnostic requests are not implemented in this build.",
                "",
                "The module inventory shown in this workspace is a development fixture. "
                "It must not be interpreted as the installed modules or actual condition "
                "of the vehicle.",
                "",
                "NEXT STEP",
                "Select 'Simulated vehicle (synthetic OBD-II)' in Capture and start listening "
                "to generate a clearly labelled demonstration report. For a real vehicle "
                "report, verified model-specific ECU addressing and read-only diagnostic "
                "services must be implemented first.",
                "",
                "DATA INTEGRITY: No real ECU results were created or inferred.",
            ]
            self.health_report.setPlainText("\n".join(report))
            self.result_log.appendPlainText(
                "HEALTH REPORT: blocked. Live module interrogation is not implemented; no ECU was queried."
            )
            return

        if not vin:
            self.health_report.setPlainText(
                "FREEROV3R VEHICLE HEALTH REPORT\n"
                f"Generated: {timestamp}\n"
                "RESULT: NOT RUN\n\n"
                "Select a vehicle and save its 17-character VIN in the Sensors tab, "
                "then run the report again. No module scan was performed."
            )
            return

        modules = self.network.scan_all()
        dtc_entries = [
            (module, dtc) for module in modules for dtc in module.dtcs
        ]
        affected = [module for module in modules if module.dtcs]
        severity_counts = {}
        for module, dtc in dtc_entries:
            severity = (dtc.severity or "Unclassified").strip()
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        lines = [
            "FREEROV3R VEHICLE HEALTH REPORT",
            f"Generated: {timestamp}",
            f"Vehicle VIN: {vin}",
            "DATA SOURCE: SYNTHETIC MODULE SIMULATOR",
            "IMPORTANT: This is a demonstration report, not a scan of a physical vehicle.",
            "",
            "EXECUTIVE SUMMARY",
            f"Module inventory scanned: {len(modules)}",
            f"Modules responding in simulator: {sum(1 for module in modules if module.available)}",
            f"Modules with DTC entries: {len(affected)}",
            f"Total DTC entries: {len(dtc_entries)}",
        ]
        if severity_counts:
            lines.append("DTC severity breakdown:")
            lines.extend(
                f"  • {severity}: {count}"
                for severity, count in sorted(severity_counts.items())
            )
        else:
            lines.append("DTC severity breakdown: No DTC entries.")
        lines.extend(["", "MODULE FINDINGS"])
        for module in modules:
            status = "FAULTS RECORDED" if module.dtcs else "NO DTC ENTRIES"
            if not module.available:
                status = "NO SIMULATOR RESPONSE"
            lines.append(f"{module.code} — {module.name} [{module.category}]")
            lines.append(f"  Status: {status}")
            if module.dtcs:
                for dtc in module.dtcs:
                    lines.append(
                        f"  • {dtc.code} | {dtc.status} | {dtc.severity}: {dtc.description}"
                    )
            else:
                lines.append("  • No DTC entries in simulator fixture.")
        lines.extend([
            "",
            "ASSESSMENT",
            (
                f"{len(affected)} module(s) contain example DTC entries. "
                "Review each listed code against verified service information."
                if affected else
                "No DTC entries are present in this simulator fixture."
            ),
            "",
            "LIMITATIONS",
            "All module names, response states and DTC entries above are synthetic test data. "
            "They do not establish actual vehicle fitment, ECU communication, fault status, "
            "roadworthiness or repair requirements. No commands were sent to a physical ECU.",
        ])
        report_text = "\n".join(lines)
        self.health_report.setPlainText(report_text)
        self.result_log.appendPlainText(
            f"HEALTH REPORT: {len(modules)} simulated modules checked; "
            f"{len(affected)} with DTC entries; {len(dtc_entries)} total DTC(s)."
        )
        self.history_callback(
            "module_health_report",
            "Module health report generated (simulator)",
            {
                "source": "synthetic_module_simulator",
                "modules_scanned": len(modules),
                "modules_with_dtcs": len(affected),
                "dtc_count": len(dtc_entries),
                "severity_counts": severity_counts,
                "report": report_text,
            },
            vin=vin,
        )
        self.refresh_tree()

    def export_health_report(self):
        report = self.health_report.toPlainText().strip()
        if not report:
            QMessageBox.information(
                self, "No health report", "Generate a health report before exporting."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export vehicle health report", "vehicle_health_report.txt",
            "Text report (*.txt);;Markdown (*.md)"
        )
        if path:
            Path(path).write_text(report + "\n", encoding="utf-8")
            self.result_log.appendPlainText(f"Health report exported: {path}")

    def clear_selected_code(self):
        code = self._selected_code()
        row = self.dtc_table.currentRow()
        if not self.simulation_enabled or not code or row < 0 or not self.dtc_table.item(row, 0):
            return
        vin = self._require_vehicle()
        if not vin:
            return
        dtc = self.dtc_table.item(row, 0).text()
        if self.network.clear_code(code, dtc):
            self.result_log.appendPlainText(f"CLEAR {code} {dtc}: removed from simulated module memory.")
            self.history_callback("dtc_cleared", f"Cleared {dtc} from {code}", {"module": code, "dtc": dtc}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def clear_module(self):
        code = self._selected_code()
        if not self.simulation_enabled or not code:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        before = [d.code for d in self.network.get_module(code).dtcs]
        count = self.network.clear_module(code)
        self.result_log.appendPlainText(f"CLEAR MODULE {code}: {count} simulated DTC(s) cleared.")
        self.history_callback("module_dtcs_cleared", f"Cleared all DTCs from {code}", {"module": code, "dtcs_cleared": before}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()

    def clear_all(self):
        if not self.simulation_enabled:
            return
        vin = self._require_vehicle()
        if not vin:
            return
        answer = QMessageBox.question(self, "Clear all simulated DTCs", "Remove every DTC from every simulated module?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        before = {m.code: [d.code for d in m.dtcs] for m in self.network.modules if m.dtcs}
        count = self.network.clear_all()
        self.result_log.appendPlainText(f"CLEAR ALL: {count} simulated DTC(s) removed.")
        self.history_callback("all_dtcs_cleared", "Cleared all simulated DTCs", {"dtcs_by_module": before, "total_cleared": count}, vin=vin)
        self.refresh_tree()
        self.show_selected_module()
