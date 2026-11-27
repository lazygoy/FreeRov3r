"""Service-routine catalog and read-only readiness workspace."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHeaderView, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostics.service_routines import ServiceRoutine, ServiceRoutineManager


class SpecialFunctionsTab(QWidget):
    """Service-routine catalog with guarded preflight and VIN-linked audit history."""
    ROUTINES = [
        ("Service & Maintenance", "Instrument cluster / service system", "Service interval reset",
         "Reset the oil-service or scheduled-maintenance reminder after the required maintenance has been completed.",
         "Correct service procedure completed; vehicle configuration and reset method verified."),
        ("Service & Maintenance", "Battery / body electrical system", "Battery registration or adaptation",
         "Register a replacement battery where the vehicle requires battery monitoring adaptation.",
         "Battery specification and monitoring-system support verified for the exact vehicle."),
        ("Service & Maintenance", "Brake system", "Brake pad replacement service mode",
         "Retract or release the electronic parking-brake mechanism for rear brake service, where supported.",
         "Vehicle safely secured; correct axle and actuator procedure confirmed."),
        ("Air Suspension", "Air suspension control module", "Ride-height calibration",
         "Calibrate commanded suspension heights against measured reference points.",
         "Level measuring surface, correct tire pressures, ride-height measurements and vehicle-specific values."),
        ("Air Suspension", "Air suspension control module", "Compressor activation test",
         "Run a controlled compressor and valve-block functional test.",
         "Leak check, pressure limits and compressor thermal limits verified."),
        ("Air Suspension", "Air suspension control module", "Suspension mode / transport-mode control",
         "Inspect or change supported suspension operating modes for service or transport.",
         "Exact mode support and safe vehicle state verified."),
        ("Brakes & ABS", "ABS / stability control module", "ABS hydraulic unit bleeding",
         "Guide a supported automated bleed procedure for the ABS hydraulic unit after brake-system work.",
         "Correct pressure bleeder setup, fluid specification and manufacturer bleed sequence."),
        ("Brakes & ABS", "ABS / stability control module", "Brake pressure sensor calibration",
         "Calibrate supported brake-pressure sensing after relevant component replacement.",
         "No active hydraulic faults; sensor and calibration conditions verified."),
        ("Parking Brake", "Electronic parking-brake module", "Parking brake service mode",
         "Move supported parking-brake actuators into a service position for brake work.",
         "Vehicle secured against movement; actuator and service procedure verified."),
        ("Parking Brake", "Electronic parking-brake module", "Parking brake actuator calibration",
         "Run the supported actuator initialization or calibration after service.",
         "Mechanical installation checked and vehicle-specific calibration method verified."),
        ("Engine & Emissions", "Engine control module", "DPF regeneration",
         "Request a supported diesel particulate-filter regeneration when diagnostic conditions permit.",
         "Oil level, coolant temperature, fuel level, DPF loading and fire-safety conditions checked."),
        ("Engine & Emissions", "Engine control module", "Throttle adaptation",
         "Run a supported throttle-body or throttle-position adaptation after relevant repairs.",
         "No unresolved engine faults; exact engine and throttle procedure verified."),
        ("Engine & Emissions", "Engine control module", "EGR adaptation / relearn",
         "Run a supported EGR initialization or learned-value procedure after component service.",
         "Correct engine variant and required temperature / ignition conditions verified."),
        ("Transmission & Driveline", "Transmission control module", "Transmission adaptive values reset",
         "Reset supported learned transmission values when the repair procedure specifically calls for it.",
         "Repair completed; correct transmission variant and post-reset drive cycle known."),
        ("Transmission & Driveline", "Transfer case control module", "Transfer case calibration",
         "Run supported transfer-case calibration or initialization after relevant repairs.",
         "Driveline configuration and exact calibration prerequisites verified."),
        ("Steering & Chassis", "Steering / ABS modules", "Steering-angle sensor calibration",
         "Calibrate the steering-angle reference after alignment or steering-system work.",
         "Wheels straight, alignment verified and vehicle on a suitable level surface."),
        ("Body & Electrical", "Body control module", "Window regulator initialization",
         "Relearn supported one-touch window limits after battery disconnection or regulator replacement.",
         "Correct window and anti-trap initialization procedure verified."),
        ("Body & Electrical", "Lighting control module", "Headlamp leveling calibration",
         "Calibrate supported automatic headlamp leveling after sensor or suspension work.",
         "Vehicle load and ride height set to the specified calibration condition."),
    ]

    def __init__(self, vin_provider=None, history_callback=None, parent=None):
        super().__init__(parent)
        self.vin_provider = vin_provider or (lambda: None)
        self.history_callback = history_callback or (lambda *args, **kwargs: None)
        self.routine_manager = ServiceRoutineManager()
        self.current_routine = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            "<b>Service routines and module-specific procedures</b><br>"
            "Candidate procedures for the Discovery 4 / LR4 (L319) project. "
            "Compatibility and live command support are not yet verified. "
            "Preflight checks are read-only and do not transmit ECU commands."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("SYSTEM:"))
        self.category_filter = QComboBox()
        self.category_filter.addItem("All systems")
        for category in sorted({item[0] for item in self.ROUTINES}):
            self.category_filter.addItem(category)
        self.category_filter.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.category_filter, 1)
        self.vehicle_label = QLabel("NO VEHICLE SELECTED")
        filter_row.addWidget(self.vehicle_label)
        layout.addLayout(filter_row)

        split = QHBoxLayout()
        self.routine_tree = QTreeWidget()
        self.routine_tree.setHeaderLabels(["Routine", "Module / system", "Status"])
        self.routine_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.routine_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.routine_tree.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.routine_tree, 3)

        details_panel = QVBoxLayout()
        details_panel.addWidget(QLabel("ROUTINE DETAILS"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a routine to inspect its purpose and prerequisites.")
        details_panel.addWidget(self.details, 1)

        self.preflight_button = QPushButton("Run Readiness Check")
        self.preflight_button.setEnabled(False)
        self.preflight_button.setToolTip("Checks available vehicle context and reports missing implementation requirements. Sends no ECU commands.")
        self.preflight_button.clicked.connect(self.run_preflight)
        details_panel.addWidget(self.preflight_button)

        self.execution_note = QLabel(
            "LIVE EXECUTION LOCKED  •  NO ECU COMMANDS SENT"
        )
        self.execution_note.setWordWrap(True)
        details_panel.addWidget(self.execution_note)
        split.addLayout(details_panel, 2)
        layout.addLayout(split, 1)
        self.refresh()

    @staticmethod
    def _routine_id(category, name):
        return f"{category.strip().lower()}::{name.strip().lower()}"

    def _selected_routine(self):
        item = self.routine_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return None
        category, module, name, description, prerequisites = data
        return ServiceRoutine(
            routine_id=self._routine_id(category, name),
            category=category,
            target_module=module,
            name=name,
            description=description,
            prerequisites=prerequisites,
        )

    def refresh(self, *_):
        vin = self.vin_provider()
        self.vehicle_label.setText(vin or "NO VEHICLE SELECTED")
        selected_category = self.category_filter.currentText()
        self.routine_tree.clear()
        groups = {}
        for category, module, name, description, prerequisites in self.ROUTINES:
            if selected_category != "All systems" and category != selected_category:
                continue
            group = groups.get(category)
            if group is None:
                group = QTreeWidgetItem([category, "", ""])
                self.routine_tree.addTopLevelItem(group)
                groups[category] = group
            item = QTreeWidgetItem([name, module, "CATALOG ONLY"])
            item.setData(0, Qt.UserRole, (category, module, name, description, prerequisites))
            group.addChild(item)
        self.routine_tree.expandAll()
        if self.routine_tree.topLevelItemCount():
            first = self.routine_tree.topLevelItem(0)
            if first.childCount():
                self.routine_tree.setCurrentItem(first.child(0))
        else:
            self.current_routine = None
            self.details.clear()
            self.preflight_button.setEnabled(False)

    def show_selected(self):
        routine = self._selected_routine()
        self.current_routine = routine
        if routine is None:
            self.details.clear()
            self.preflight_button.setEnabled(False)
            return
        vin = self.vin_provider() or "Not selected"
        self.preflight_button.setEnabled(True)
        self.details.setPlainText(
            f"ROUTINE: {routine.name}\n"
            f"SYSTEM: {routine.category}\n"
            f"TARGET MODULE: {routine.target_module}\n"
            f"CURRENT VIN: {vin}\n"
            "SUPPORT STATUS: CATALOG ONLY\n\n"
            f"PURPOSE\n{routine.description}\n\n"
            f"PREREQUISITES TO VERIFY\n{routine.prerequisites}\n\n"
            "READINESS REQUIREMENTS\n"
            "• Exact vehicle and module compatibility verified\n"
            "• Module addressing and diagnostic protocol verified\n"
            "• Security-access requirements documented, if applicable\n"
            "• Manufacturer procedure and safety conditions verified\n"
            "• A reviewed routine executor implemented\n\n"
            "The readiness check below reports missing requirements. It does not send commands."
        )
        self.execution_note.setText("LIVE EXECUTION LOCKED  •  NO ECU COMMANDS SENT")

    def run_preflight(self):
        routine = self.current_routine or self._selected_routine()
        if routine is None:
            return
        vin = self.vin_provider()
        result = self.routine_manager.preflight(routine, vin=vin)
        status = "READY" if result.ready else "BLOCKED"
        self.execution_note.setText(
            f"{status}  •  READ-ONLY CHECK  •  NO ECU COMMANDS SENT"
        )
        blockers = "\n".join(f"• {item}" for item in result.blockers) or "No blockers reported."
        self.details.appendPlainText(
            f"\n\nREADINESS RESULT: {status}\n{blockers}"
        )
        self.history_callback(
            "service_routine_preflight",
            f"Preflight {status.lower()}: {routine.name}",
            result.to_dict(),
            vin=vin,
        )
