"""VIN- and module-scoped troubleshooting prompt workspace."""

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHeaderView, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


class SolutionsTab(QWidget):
    """VIN- and module-scoped ChatGPT prompt and saved-response workspace."""
    def __init__(self, network, vin_provider, history_provider, sensor_provider, storage_path, parent=None):
        super().__init__(parent)
        self.network, self.vin_provider = network, vin_provider
        self.history_provider, self.sensor_provider = history_provider, sensor_provider
        self.storage_path = Path(storage_path)
        self.solutions = self._load()
        self.current_module_code = None
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        split = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Problem module", "DTCs"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self.select_module)
        split.addWidget(self.tree, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Scan evidence"))
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        right.addWidget(self.evidence, 2)
        row = QHBoxLayout()
        copy = QPushButton("Copy ChatGPT prompt")
        copy.clicked.connect(self.copy_prompt)
        row.addWidget(copy)
        export = QPushButton("Export prompt")
        export.clicked.connect(self.export_prompt)
        row.addWidget(export)
        right.addLayout(row)
        right.addWidget(QLabel("ChatGPT suggested troubleshooting / solution"))
        self.response = QPlainTextEdit()
        self.response.setPlaceholderText("Paste ChatGPT's response here.")
        right.addWidget(self.response, 3)
        row2 = QHBoxLayout()
        paste = QPushButton("Paste from clipboard")
        paste.clicked.connect(lambda: self.response.setPlainText(QApplication.clipboard().text()))
        row2.addWidget(paste)
        save = QPushButton("Save solution for this VIN / module")
        save.clicked.connect(self.save_solution)
        row2.addWidget(save)
        right.addLayout(row2)
        split.addLayout(right, 3)
        layout.addLayout(split)
        self.refresh()

    def _load(self):
        try:
            value = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.solutions, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.storage_path)

    def set_network(self, network):
        self.network = network
        self.refresh()

    def refresh(self):
        vin = self.vin_provider() or "No VIN selected"
        self.heading.setText(
            f"<b>ChatGPT troubleshooting workspace</b><br>Vehicle: {vin}<br>"
            "Select a module to build a focused prompt from DTCs, vehicle history and recent sensor data. "
            "Prompts and saved replies stay local. No API call is made."
        )
        previous = self.current_module_code
        self.tree.clear()
        groups = {}
        for module in self.network.modules:
            group = groups.get(module.category)
            if group is None:
                group = QTreeWidgetItem([module.category, ""])
                self.tree.addTopLevelItem(group)
                groups[module.category] = group
            item = QTreeWidgetItem([f"{module.code} — {module.name}", str(len(module.dtcs))])
            item.setData(0, Qt.UserRole, module.code)
            group.addChild(item)
            if module.code == previous:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            group = self.tree.topLevelItem(0)
            if group.childCount():
                self.tree.setCurrentItem(group.child(0))
        self.select_module()

    def select_module(self):
        item = self.tree.currentItem()
        code = item.data(0, Qt.UserRole) if item else None
        if not code:
            self.current_module_code = None
            self.evidence.clear()
            self.response.clear()
            return
        self.current_module_code = code
        module = self.network.get_module(code)
        vin = self.vin_provider() or "UNASSIGNED"
        dtcs = [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs]
        evidence = {
            "vin": vin,
            "module": {"code": code, "name": module.name, "category": module.category},
            "scan_state": "not_scanned" if module.last_scan is None else "scanned",
            "last_scan": module.last_scan, "available": module.available, "dtcs": dtcs,
            "data_quality": "Synthetic simulator fixture, not verified live L319 scan data."
        }
        self.evidence.setPlainText(json.dumps(evidence, indent=2, ensure_ascii=False))
        self.response.setPlainText(self.solutions.get(vin, {}).get(code, {}).get("response", ""))

    def build_prompt(self):
        code = self.current_module_code
        if not code:
            return ""
        module = self.network.get_module(code)
        vin = self.vin_provider() or "UNASSIGNED"
        events = self.history_provider(vin)[-30:]
        samples = self.sensor_provider(vin)[-50:]
        data = {
            "vin": vin, "vehicle": "2010-2016 Land Rover Discovery 4 / LR4 (L319)",
            "module": {"code": code, "name": module.name, "category": module.category},
            "scan_state": "not_scanned" if module.last_scan is None else "scanned",
            "last_scan": module.last_scan,
            "dtcs": [{"code": d.code, "description": d.description, "status": d.status, "severity": d.severity} for d in module.dtcs],
            "recent_history": [{"timestamp": e.get("timestamp"), "type": e.get("type"), "summary": e.get("summary"), "details": e.get("details", {})} for e in events],
            "sensor_samples": [{"timestamp": x.timestamp, "name": x.name, "value": x.value, "unit": x.unit, "source": x.source} for x in samples],
            "data_quality": "Module inventory and DTCs are synthetic fixtures, not actual verified L319 faults or definitions."
        }
        instructions = (
            "Troubleshoot this Land Rover Discovery 4 / LR4. Analyze only the evidence. "
            "Separate facts, hypotheses and tests. Do not assume generic DTC descriptions are verified. "
            "For each likely cause explain why it fits, provide safe checks and expected results, required tools, "
            "and what would rule it out. Prioritize non-invasive checks. Do not recommend parts replacement "
            "without confirming tests. Flag safety-critical systems. State clearly if evidence is synthetic or insufficient."
        )
        return instructions + "\n\nEVIDENCE JSON:\n" + json.dumps(data, indent=2, ensure_ascii=False)

    def copy_prompt(self):
        prompt = self.build_prompt()
        if prompt:
            QApplication.clipboard().setText(prompt)
            QMessageBox.information(self, "Copied", "Module-specific ChatGPT prompt copied to clipboard.")

    def export_prompt(self):
        prompt = self.build_prompt()
        if not prompt:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export troubleshooting prompt", "freerov3r_prompt.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(prompt, encoding="utf-8")

    def save_solution(self):
        code = self.current_module_code
        if not code:
            return
        vin = self.vin_provider() or "UNASSIGNED"
        self.solutions.setdefault(vin, {})[code] = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "response": self.response.toPlainText(),
            "dtcs_at_save": [d.code for d in self.network.get_module(code).dtcs]
        }
        self._save()
        QMessageBox.information(self, "Saved", f"Solution saved locally for {vin} / {code}.")
