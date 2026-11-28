"""Operator-reviewed D-PDU API discovery and receive-only configuration UI."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .hardware.dpdu_discovery import DPduModuleRegistration, discover_d_pdu_modules
from .hardware.dpdu_runtime import DPduApiRuntime, DPduLiveModule
from .hardware.dpdu_worker import DPduDiagnosticWorker, DPduWorkerConfig


def parse_uint32(text: str, field_name: str) -> int:
    """Parse decimal or 0x-prefixed uint32 input."""
    value_text = str(text).strip()
    if not value_text:
        raise ValueError(f"{field_name} is required")
    try:
        value = int(value_text, 0)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be decimal or 0x-prefixed hexadecimal") from exc
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{field_name} must fit in uint32")
    return value


def parse_hex_bytes(text: str, field_name: str) -> bytes:
    """Parse byte pairs separated by spaces, commas, or colons."""
    normalized = str(text).strip().replace(",", " ").replace(":", " ")
    if not normalized:
        raise ValueError(f"{field_name} is required")
    compact = "".join(normalized.split())
    if compact.lower().startswith("0x"):
        compact = compact[2:]
    if not compact or len(compact) % 2:
        raise ValueError(f"{field_name} must contain complete hexadecimal byte pairs")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains non-hexadecimal characters") from exc


class _InventoryWorker(QThread):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, registration: DPduModuleRegistration, parent=None):
        super().__init__(parent)
        self.registration = registration

    def run(self):
        runtime = DPduApiRuntime(self.registration)
        try:
            modules = runtime.open()
            self.completed.emit(self.registration, modules)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                runtime.close()
            except Exception as exc:
                self.failed.emit(f"D-PDU API cleanup failed: {exc}")


class DPduTab(QWidget):
    """Passive discovery plus explicit, operator-confirmed receive-only startup."""

    def __init__(self, event_sink, parent=None):
        super().__init__(parent)
        self.event_sink = event_sink
        self._registrations: list[DPduModuleRegistration] = []
        self._inventory_worker: _InventoryWorker | None = None
        self._worker: DPduDiagnosticWorker | None = None
        self._modules: list[DPduLiveModule] = []

        root = QVBoxLayout(self)
        root.setSpacing(12)

        intro = QLabel(
            "D-PDU API / MVCI diagnostic reception. Discovery is passive. "
            "Loading an API enumerates its modules but does not connect to a vehicle. "
            "Starting reception physically activates the selected resource."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        discovery_box = QGroupBox("Installed D-PDU API")
        discovery_layout = QVBoxLayout(discovery_box)
        registration_row = QHBoxLayout()
        self.registration_combo = QComboBox()
        self.registration_combo.setMinimumWidth(360)
        self.detect_button = QPushButton("Detect installed APIs")
        self.inspect_button = QPushButton("Inspect selected API")
        registration_row.addWidget(self.registration_combo, 1)
        registration_row.addWidget(self.detect_button)
        registration_row.addWidget(self.inspect_button)
        discovery_layout.addLayout(registration_row)
        self.registration_details = QLabel("No D-PDU API registrations detected yet.")
        self.registration_details.setWordWrap(True)
        discovery_layout.addWidget(self.registration_details)
        root.addWidget(discovery_box)

        module_box = QGroupBox("Live module inventory")
        module_layout = QFormLayout(module_box)
        self.module_combo = QComboBox()
        self.module_combo.setMinimumWidth(320)
        self.module_details = QLabel("Inspect an installed API to enumerate live modules.")
        self.module_details.setWordWrap(True)
        module_layout.addRow("MVCI module:", self.module_combo)
        module_layout.addRow("Module details:", self.module_details)
        root.addWidget(module_box)

        config_box = QGroupBox("Receive-only protocol configuration")
        config_layout = QFormLayout(config_box)
        self.resource_id_edit = QLineEdit()
        self.resource_id_edit.setPlaceholderText("Required resource ID, e.g. 600 or 0x258")
        self.mask_edit = QLineEdit()
        self.mask_edit.setPlaceholderText("Required response mask, e.g. FF")
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("Required response pattern, e.g. 62")
        self.acceptance_id_edit = QLineEdit("1")
        self.acceptance_id_edit.setPlaceholderText("Acceptance ID (decimal or 0x...)")
        config_layout.addRow("Resource ID:", self.resource_id_edit)
        config_layout.addRow("Response mask (hex):", self.mask_edit)
        config_layout.addRow("Response pattern (hex):", self.pattern_edit)
        config_layout.addRow("Acceptance ID:", self.acceptance_id_edit)
        root.addWidget(config_box)
        config_note = QLabel(
            "Resource ID, protocol-specific response mask/pattern and acceptance ID are "
            "operator-supplied in this first UI. Verify them against the selected VCI's "
            "MDF/CDF and protocol documentation. FreeRov3r does not guess pin mappings, "
            "ComParams or a vehicle protocol."
        )
        config_note.setWordWrap(True)
        root.addWidget(config_note)

        self.confirm_checkbox = QCheckBox(
            "I have verified the selected VCI, protocol, resource ID, pins and filters, "
            "and authorize physical connection to the vehicle."
        )
        root.addWidget(self.confirm_checkbox)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Start D-PDU reception")
        self.stop_button = QPushButton("Stop reception")
        self.stop_button.setEnabled(False)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        root.addLayout(action_row)

        self.status_label = QLabel("D-PDU is idle. No vehicle connection has been made.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch(1)

        self.detect_button.clicked.connect(self.detect_registrations)
        self.inspect_button.clicked.connect(self.inspect_selected_api)
        self.registration_combo.currentIndexChanged.connect(self._registration_changed)
        self.module_combo.currentIndexChanged.connect(self._module_changed)
        self.start_button.clicked.connect(self.start_reception)
        self.stop_button.clicked.connect(self.stop_reception)

    def detect_registrations(self):
        if self._inventory_worker and self._inventory_worker.isRunning():
            return
        self._registrations = discover_d_pdu_modules()
        self.registration_combo.clear()
        for registration in self._registrations:
            label = registration.short_name
            if registration.supplier_name:
                label += f" ({registration.supplier_name})"
            self.registration_combo.addItem(label, registration)
        if not self._registrations:
            self.registration_details.setText(
                "No D-PDU API registrations were found. Install the VCI manufacturer's "
                "D-PDU API package and verify its standard Root File registry entry."
            )
            self.status_label.setText("Passive discovery found no installed D-PDU API.")
            return
        self._registration_changed()
        self.status_label.setText(
            f"Found {len(self._registrations)} registered D-PDU API implementation(s). "
            "No DLL has been loaded and no vehicle connection has been made."
        )

    def _registration_changed(self, *_):
        registration = self.registration_combo.currentData()
        if not isinstance(registration, DPduModuleRegistration):
            return
        self.registration_details.setText(
            f"Library: {registration.library_file}\n"
            f"MDF: {registration.module_description_file or 'not registered'}\n"
            f"CDF: {registration.cable_description_file or 'not registered'}"
        )
        self._modules = []
        self.module_combo.clear()
        self.module_details.setText("Inspect the selected API to enumerate live modules.")

    def inspect_selected_api(self):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "D-PDU busy", "Stop diagnostic reception before inspecting another API.")
            return
        registration = self.registration_combo.currentData()
        if not isinstance(registration, DPduModuleRegistration):
            QMessageBox.information(self, "D-PDU discovery", "Detect and select an installed D-PDU API first.")
            return
        if self._inventory_worker and self._inventory_worker.isRunning():
            return
        self.inspect_button.setEnabled(False)
        self.status_label.setText("Loading selected D-PDU API and enumerating modules. Vehicle remains offline.")
        self._inventory_worker = _InventoryWorker(registration, self)
        self._inventory_worker.completed.connect(self._inventory_completed)
        self._inventory_worker.failed.connect(self._inventory_failed)
        self._inventory_worker.finished.connect(self._inventory_finished)
        self._inventory_worker.start()

    def _inventory_completed(self, registration, modules):
        if self.registration_combo.currentData() != registration:
            return
        self._modules = list(modules or ())
        self.module_combo.clear()
        for module in self._modules:
            label = (
                f"Handle {module.module_handle} | {module.vendor_module_name or module.registration_name} "
                f"| status 0x{module.module_status & 0xFFFFFFFF:08X}"
            )
            self.module_combo.addItem(label, module.module_handle)
        self._module_changed()
        self.status_label.setText(
            f"Enumerated {len(self._modules)} live module(s). API has been closed; "
            "no module was initialized and no vehicle resource was connected."
        )

    def _inventory_finished(self):
        self.inspect_button.setEnabled(True)

    def _inventory_failed(self, message):
        self.status_label.setText(f"D-PDU inventory failed: {message}")

    def _module_changed(self, *_):
        handle = self.module_combo.currentData()
        module = next((item for item in self._modules if item.module_handle == handle), None)
        if module is None:
            self.module_details.setText("No live module selected.")
            return
        self.module_details.setText(
            f"Handle: {module.module_handle} | Type ID: {module.module_type_id} | "
            f"Vendor: {module.vendor_module_name or 'not supplied'} | "
            f"Additional info: {module.vendor_additional_info or 'not supplied'}"
        )

    def start_reception(self):
        if self._worker and self._worker.isRunning():
            return
        registration = self.registration_combo.currentData()
        module_handle = self.module_combo.currentData()
        if not isinstance(registration, DPduModuleRegistration) or module_handle is None:
            QMessageBox.warning(self, "D-PDU configuration", "Detect an API and inspect it to select a live module.")
            return
        if not self.confirm_checkbox.isChecked():
            QMessageBox.warning(
                self, "Physical connection not authorized",
                "Review the VCI, protocol, resource, pins and response filters, then explicitly check the authorization box."
            )
            return
        try:
            resource_id = parse_uint32(self.resource_id_edit.text(), "Resource ID")
            mask = parse_hex_bytes(self.mask_edit.text(), "Response mask")
            pattern = parse_hex_bytes(self.pattern_edit.text(), "Response pattern")
            acceptance_id = parse_uint32(self.acceptance_id_edit.text(), "Acceptance ID")
            if len(mask) != len(pattern):
                raise ValueError("Response mask and pattern must contain the same number of bytes")
            config = DPduWorkerConfig(
                registration=registration,
                module_handle=int(module_handle),
                resource_id=resource_id,
                response_mask=mask,
                response_pattern=pattern,
                acceptance_id=acceptance_id,
                operator_confirmed_physical_connection=True,
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid D-PDU configuration", str(exc))
            return

        self._worker = DPduDiagnosticWorker(config, parent=self)
        self._worker.diagnostic_events.connect(self.event_sink)
        self._worker.status.connect(self.status_label.setText)
        self._worker.failed.connect(self._worker_failed)
        self._worker.finished.connect(self._worker_finished)
        self.confirm_checkbox.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Starting explicitly authorized D-PDU receive session...")
        self._worker.start()

    def stop_reception(self):
        if self._worker and self._worker.isRunning():
            self.stop_button.setEnabled(False)
            self.status_label.setText("Stop requested. Worker is closing the D-PDU session.")
            self._worker.stop()

    def _worker_failed(self, message):
        self.status_label.setText(f"D-PDU worker failed: {message}")

    def _worker_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.confirm_checkbox.setChecked(False)
        self.confirm_checkbox.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Request worker shutdown and wait before the owning window is destroyed."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            if not self._worker.wait(timeout_ms):
                return False
        if self._inventory_worker and self._inventory_worker.isRunning():
            if not self._inventory_worker.wait(timeout_ms):
                return False
        return True
