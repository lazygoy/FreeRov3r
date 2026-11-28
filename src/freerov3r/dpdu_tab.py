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
from .hardware.dpdu_mdf import (
    DPduCableDescription,
    DPduDescriptionError,
    DPduModuleDescription,
    map_resource_to_dlc_pins,
    parse_d_pdu_cdf,
    parse_d_pdu_mdf,
)
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


class _ResourceQueryWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        registration: DPduModuleRegistration,
        module_handle: int,
        module_type_id: int,
        bus_type_id: int,
        protocol_id: int,
        dlc_pins: tuple[tuple[int, int], ...],
        parent=None,
    ):
        super().__init__(parent)
        self.registration = registration
        self.module_handle = int(module_handle)
        self.module_type_id = int(module_type_id)
        self.bus_type_id = int(bus_type_id)
        self.protocol_id = int(protocol_id)
        self.dlc_pins = tuple(dlc_pins)

    def run(self):
        runtime = DPduApiRuntime(self.registration)
        try:
            modules = runtime.open()
            selected = next(
                (item for item in modules if item.module_handle == self.module_handle),
                None,
            )
            if selected is None:
                raise RuntimeError("Selected MVCI module disappeared from the live inventory")
            if selected.module_type_id != self.module_type_id:
                raise RuntimeError("Selected MVCI module type changed; inspect the API again")
            groups = runtime.enumerate_resource_ids(
                self.module_handle,
                self.bus_type_id,
                self.protocol_id,
                self.dlc_pins,
            )
            resource_ids = sorted({
                resource_id
                for group in groups
                if group.module_handle == self.module_handle
                for resource_id in group.resource_ids
            })
            self.completed.emit(resource_ids)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                runtime.close()
            except Exception as exc:
                self.failed.emit(f"D-PDU resource-query cleanup failed: {exc}")


class DPduTab(QWidget):
    """Passive discovery plus explicit, operator-confirmed receive-only startup."""

    def __init__(self, event_sink, parent=None):
        super().__init__(parent)
        self.event_sink = event_sink
        self._registrations: list[DPduModuleRegistration] = []
        self._inventory_worker: _InventoryWorker | None = None
        self._resource_worker: _ResourceQueryWorker | None = None
        self._worker: DPduDiagnosticWorker | None = None
        self._modules: list[DPduLiveModule] = []
        self._mdf: DPduModuleDescription | None = None
        self._cdf: DPduCableDescription | None = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        intro = QLabel(
            "D-PDU API / MVCI diagnostic reception. Discovery and capability queries are "
            "passive. Starting reception physically activates the selected resource."
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

        resource_box = QGroupBox("MDF/CDF capability and live resource query")
        resource_layout = QFormLayout(resource_box)
        self.cable_combo = QComboBox()
        self.cable_combo.setMinimumWidth(320)
        self.resource_combo = QComboBox()
        self.resource_combo.setMinimumWidth(320)
        self.live_resource_combo = QComboBox()
        self.live_resource_combo.setMinimumWidth(320)
        self.resource_details = QLabel("Select a module and cable to inspect supported resources.")
        self.resource_details.setWordWrap(True)
        self.pin_mapping_details = QLabel("No cable pin mapping selected.")
        self.pin_mapping_details.setWordWrap(True)
        resource_layout.addRow("Cable definition:", self.cable_combo)
        resource_layout.addRow("MDF resource definition:", self.resource_combo)
        resource_layout.addRow("VCI resource ID:", self.live_resource_combo)
        resource_layout.addRow("Resource details:", self.resource_details)
        resource_layout.addRow("Mapped DLC pins:", self.pin_mapping_details)
        root.addWidget(resource_box)

        self.query_resources_button = QPushButton("Query compatible resources from VCI")
        self.query_resources_button.setEnabled(False)
        root.addWidget(self.query_resources_button)
        self.live_resource_label = QLabel(
            "No live resource IDs queried. This query does not connect to the vehicle."
        )
        self.live_resource_label.setWordWrap(True)
        root.addWidget(self.live_resource_label)

        config_box = QGroupBox("Receive-only protocol configuration")
        config_layout = QFormLayout(config_box)
        self.mask_edit = QLineEdit()
        self.mask_edit.setPlaceholderText("Protocol response mask, e.g. FF")
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("Protocol response pattern, e.g. 62")
        self.acceptance_id_edit = QLineEdit()
        self.acceptance_id_edit.setPlaceholderText("Acceptance ID (decimal or 0x...)")
        config_layout.addRow("Response mask (hex):", self.mask_edit)
        config_layout.addRow("Response pattern (hex):", self.pattern_edit)
        config_layout.addRow("Acceptance ID:", self.acceptance_id_edit)
        root.addWidget(config_box)

        config_note = QLabel(
            "The MDF/CDF supplies bus, protocol and module-to-DLC pin mapping. The VCI's "
            "PDUGetResourceIds response supplies the actual live resource IDs. Response "
            "filters and acceptance ID remain protocol-specific operator inputs; verify "
            "them against the selected VCI and diagnostic protocol documentation."
        )
        config_note.setWordWrap(True)
        root.addWidget(config_note)

        self.confirm_checkbox = QCheckBox(
            "I have verified the selected VCI, cable, protocol and response filters, "
            "and authorize physical connection to the vehicle."
        )
        root.addWidget(self.confirm_checkbox)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Start D-PDU reception")
        self.stop_button = QPushButton("Stop reception")
        self.start_button.setEnabled(False)
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
        self.cable_combo.currentIndexChanged.connect(self._resource_selection_changed)
        self.resource_combo.currentIndexChanged.connect(self._resource_selection_changed)
        self.live_resource_combo.currentIndexChanged.connect(self._live_resource_changed)
        self.query_resources_button.clicked.connect(self.query_compatible_resources)
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
        self._modules = []
        self._mdf = None
        self._cdf = None
        self.module_combo.clear()
        self.cable_combo.clear()
        self.resource_combo.clear()
        self.live_resource_combo.clear()
        self._live_resource_ids = set()
        self.query_resources_button.setEnabled(False)
        self.start_button.setEnabled(False)
        if not isinstance(registration, DPduModuleRegistration):
            return
        self.registration_details.setText(
            f"Library: {registration.library_file}\n"
            f"MDF: {registration.module_description_file or 'not registered'}\n"
            f"CDF: {registration.cable_description_file or 'not registered'}"
        )
        try:
            if not registration.module_description_file or not registration.cable_description_file:
                raise DPduDescriptionError("Selected RDF does not provide both MDF and CDF paths")
            self._mdf = parse_d_pdu_mdf(registration.module_description_file)
            self._cdf = parse_d_pdu_cdf(registration.cable_description_file)
            for cable in self._cdf.cables:
                self.cable_combo.addItem(
                    f"{cable.short_name} (ID {cable.object_id}, DLC {cable.dlc_type_eid or 'unspecified'})",
                    cable.object_id,
                )
            if not self._cdf.cables:
                raise DPduDescriptionError("CDF contains no cable definitions")
            self.status_label.setText(
                f"Parsed MDF: {len(self._mdf.resources)} resources, "
                f"{len(self._mdf.module_types)} module types. "
                f"Parsed CDF: {len(self._cdf.cables)} cable definitions."
            )
        except (DPduDescriptionError, OSError) as exc:
            self._mdf = None
            self._cdf = None
            self.status_label.setText(f"D-PDU description parsing failed: {exc}")
            self.registration_details.setText(
                self.registration_details.text() + f"\nDescription error: {exc}"
            )

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
        self.start_button.setEnabled(False)
        self.status_label.setText("Loading selected D-PDU API and enumerating live modules. Vehicle remains offline.")
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
        if self._inventory_worker is not None:
            self._inventory_worker.deleteLater()
            self._inventory_worker = None

    def _inventory_failed(self, message):
        self.status_label.setText(f"D-PDU inventory failed: {message}")

    def _module_changed(self, *_):
        handle = self.module_combo.currentData()
        module = next((item for item in self._modules if item.module_handle == handle), None)
        self.resource_combo.clear()
        self.live_resource_combo.clear()
        self._live_resource_ids = set()
        self.query_resources_button.setEnabled(False)
        self.start_button.setEnabled(False)
        if module is None:
            self.module_details.setText("No live module selected.")
            return
        self.module_details.setText(
            f"Handle: {module.module_handle} | Type ID: {module.module_type_id} | "
            f"Vendor: {module.vendor_module_name or 'not supplied'} | "
            f"Additional info: {module.vendor_additional_info or 'not supplied'}"
        )
        if self._mdf is None:
            self.resource_details.setText("MDF is unavailable; resource discovery is disabled.")
            return
        resources = self._mdf.resources_for_module_type(module.module_type_id)
        for resource in resources:
            self.resource_combo.addItem(
                f"{resource.short_name} (ID {resource.object_id}) | "
                f"{resource.bus_type_name} / {resource.protocol_name}",
                resource.object_id,
            )
        self.resource_details.setText(
            f"{len(resources)} MDF resource definition(s) match this live module type."
        )
        self._resource_selection_changed()

    def _selected_resource_and_cable(self):
        if self._mdf is None or self._cdf is None:
            raise ValueError("Valid MDF and CDF descriptions are required")
        resource_id = self.resource_combo.currentData()
        cable_id = self.cable_combo.currentData()
        resource = next(
            (item for item in self._mdf.resources if item.object_id == resource_id),
            None,
        )
        cable = next(
            (item for item in self._cdf.cables if item.object_id == cable_id),
            None,
        )
        if resource is None or cable is None:
            raise ValueError("Select an MDF resource and a CDF cable")
        return resource, cable

    def _resource_selection_changed(self, *_):
        self.query_resources_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.live_resource_combo.clear()
        self._live_resource_ids = set()
        try:
            resource, cable = self._selected_resource_and_cable()
            mapped = map_resource_to_dlc_pins(resource, cable)
            mapping_text = ", ".join(
                f"module {pin.module_pin_number} → DLC {pin.dlc_pin_number} ({pin.pin_type_name})"
                for pin in mapped
            )
            self.resource_details.setText(
                f"Bus: {resource.bus_type_name} (ID {resource.bus_type_id}) | "
                f"Protocol: {resource.protocol_name} (ID {resource.protocol_id})"
            )
            self.pin_mapping_details.setText(mapping_text)
            self.query_resources_button.setEnabled(
                self.module_combo.currentData() is not None
                and self._resource_worker is None
            )
        except (ValueError, DPduDescriptionError) as exc:
            self.resource_details.setText(str(exc))
            self.pin_mapping_details.setText("No valid cable pin mapping.")
            self.live_resource_label.setText("No live resource IDs queried.")

    def query_compatible_resources(self):
        if self._resource_worker and self._resource_worker.isRunning():
            return
        registration = self.registration_combo.currentData()
        module_handle = self.module_combo.currentData()
        module = next((item for item in self._modules if item.module_handle == module_handle), None)
        if not isinstance(registration, DPduModuleRegistration) or module is None:
            return
        try:
            resource, cable = self._selected_resource_and_cable()
            mapped = map_resource_to_dlc_pins(resource, cable)
            dlc_pins = tuple(
                (pin.dlc_pin_number, pin.pin_type_id) for pin in mapped
            )
        except (ValueError, DPduDescriptionError) as exc:
            QMessageBox.warning(self, "D-PDU resource query", str(exc))
            return

        self.query_resources_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.resource_combo.setEnabled(False)
        self.cable_combo.setEnabled(False)
        self.live_resource_label.setText(
            "Querying PDUGetResourceIds. This is a capability query; the module and vehicle remain offline."
        )
        self._resource_worker = _ResourceQueryWorker(
            registration,
            module.module_handle,
            module.module_type_id,
            resource.bus_type_id,
            resource.protocol_id,
            dlc_pins,
            self,
        )
        self._resource_worker.completed.connect(self._resource_query_completed)
        self._resource_worker.failed.connect(self._resource_query_failed)
        self._resource_worker.finished.connect(self._resource_query_finished)
        self._resource_worker.start()

    def _resource_query_completed(self, resource_ids):
        self.resource_combo.setEnabled(True)
        self.cable_combo.setEnabled(True)
        self.live_resource_combo.clear()
        for resource_id in resource_ids:
            self.live_resource_combo.addItem(str(resource_id), int(resource_id))
        self.live_resource_label.setText(
            f"VCI returned {len(resource_ids)} matching live resource ID(s): "
            + (", ".join(str(value) for value in resource_ids) if resource_ids else "none")
        )
        self._live_resource_ids = set(resource_ids)
        self.start_button.setEnabled(bool(resource_ids))

    def _live_resource_changed(self, *_):
        selected = self.live_resource_combo.currentData()
        self.start_button.setEnabled(selected in getattr(self, "_live_resource_ids", set()))

    def _resource_query_failed(self, message):
        self.live_resource_label.setText(f"Live resource query failed: {message}")

    def _resource_query_finished(self):
        self.resource_combo.setEnabled(True)
        self.cable_combo.setEnabled(True)
        if self._resource_worker is not None:
            self._resource_worker.deleteLater()
            self._resource_worker = None
        self.query_resources_button.setEnabled(
            self.resource_combo.currentData() is not None
            and self.cable_combo.currentData() is not None
        )

    def start_reception(self):
        if self._worker and self._worker.isRunning():
            return
        registration = self.registration_combo.currentData()
        module_handle = self.module_combo.currentData()
        resource_id = self.live_resource_combo.currentData()
        if (
            not isinstance(registration, DPduModuleRegistration)
            or module_handle is None
            or resource_id is None
            or resource_id not in getattr(self, "_live_resource_ids", set())
        ):
            QMessageBox.warning(
                self, "D-PDU configuration",
                "Inspect the API, select an MDF resource and CDF cable, then query live compatible resource IDs."
            )
            return
        if not self.confirm_checkbox.isChecked():
            QMessageBox.warning(
                self, "Physical connection not authorized",
                "Review the selected VCI, cable, protocol and response filters, then explicitly check the authorization box."
            )
            return
        try:
            mask = parse_hex_bytes(self.mask_edit.text(), "Response mask")
            pattern = parse_hex_bytes(self.pattern_edit.text(), "Response pattern")
            acceptance_id = parse_uint32(self.acceptance_id_edit.text(), "Acceptance ID")
            if len(mask) != len(pattern):
                raise ValueError("Response mask and pattern must contain the same number of bytes")
            config = DPduWorkerConfig(
                registration=registration,
                module_handle=int(module_handle),
                resource_id=int(resource_id),
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
        self.query_resources_button.setEnabled(False)
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
        self.start_button.setEnabled(
            self.live_resource_combo.currentData() in getattr(self, "_live_resource_ids", set())
        )
        self.query_resources_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.confirm_checkbox.setChecked(False)
        self.confirm_checkbox.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Request worker shutdown and wait before the owning window is destroyed."""
        for worker in (self._worker, self._resource_worker, self._inventory_worker):
            if worker is not None and worker.isRunning():
                if isinstance(worker, DPduDiagnosticWorker):
                    worker.stop()
                if not worker.wait(timeout_ms):
                    return False
        return True
