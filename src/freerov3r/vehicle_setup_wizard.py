"""Vehicle setup dialog and background VIN lookup workers."""

from PySide6.QtCore import QThread, Signal, Qt
from .connection_options import populate_connection_combo, select_connection_backend

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .hardware.elm327_serial_adapter import query_vin
from .hardware.interface_inventory import discover_all_interfaces
from .diagnostics.vehicle_identification import (
    identify_vehicle, validate_vin, decode_vin_online,
)


class VinQueryWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.port = port

    def run(self):
        try:
            self.completed.emit(query_vin(self.port))
        except Exception as exc:
            self.failed.emit(str(exc))


class VinDecodeWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, vin, parent=None):
        super().__init__(parent)
        self.vin = vin

    def run(self):
        try:
            self.completed.emit(decode_vin_online(self.vin))
        except Exception as exc:
            self.failed.emit(str(exc))


class VehicleSetupWizard(QDialog):
    """Optional connection and vehicle setup wizard."""

    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("FreeRov3r | Vehicle Setup")
        self.setMinimumSize(760, 540)
        self.setModal(True)
        self.result_data = None
        self._vin_worker = None
        self._decode_worker = None
        self._decoded = None
        self.setObjectName("startupSplash")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        eyebrow = QLabel("FREEROV3R CONFIGURATION")
        eyebrow.setObjectName("splashEyebrow")
        root.addWidget(eyebrow)
        self.page_title = QLabel("Connect an interface")
        self.page_title.setObjectName("splashTitle")
        root.addWidget(self.page_title)
        self.page_description = QLabel(
            "Detect USB serial and paired Bluetooth COM interfaces, or choose one manually. "
            "Wi-Fi discovery is not implemented yet. J2534 driver inventory is passive; detection does not load the driver or transmit to the vehicle."
        )
        self.page_description.setWordWrap(True)
        self.page_description.setObjectName("splashSubtitle")
        root.addWidget(self.page_description)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)

        # Page 1: connection selection
        connection_page = QWidget()
        connection_layout = QVBoxLayout(connection_page)
        connection_form = QFormLayout()
        self.interface_combo = QComboBox()
        populate_connection_combo(self.interface_combo)
        self.channel_edit = QComboBox()
        self.channel_edit.setEditable(True)
        self.channel_edit.setInsertPolicy(QComboBox.NoInsert)
        self.channel_edit.setPlaceholderText("Select detected port or enter channel")
        connection_form.addRow("Interface:", self.interface_combo)
        connection_form.addRow("Port / channel:", self.channel_edit)
        self.show_advanced_interfaces = QCheckBox("Show advanced interfaces")
        self.show_advanced_interfaces.toggled.connect(self._refresh_interface_options)
        connection_form.addRow(self.show_advanced_interfaces)
        connection_layout.addLayout(connection_form)
        detect_row = QHBoxLayout()
        detect_button = QPushButton("Detect interfaces")
        detect_button.clicked.connect(self.detect_interfaces)
        detect_row.addWidget(detect_button)
        detect_row.addStretch()
        connection_layout.addLayout(detect_row)
        self.interface_status = QLabel(
            "ESP32 interfaces are receive-only. Dual mode requires two different COM ports, entered as COMx,COMy (HS-CAN first, MS-CAN second). "
            "ELM327 provides standard read-only OBD-II data, not general raw CAN capture. "
            "Dual ESP32 USB uses two COM ports; dual Wi-Fi uses two IP[:port] endpoints separated by a comma. "
            "Wi-Fi discovery is manual. J2534 Pass-Thru supports receive-only CAN capture in this build."
        )
        self.interface_status.setWordWrap(True)
        self.interface_status.setObjectName("mutedText")
        connection_layout.addWidget(self.interface_status)
        connection_layout.addStretch()
        self.pages.addWidget(connection_page)

        # Page 2: VIN and manual vehicle details
        vehicle_page = QWidget()
        vehicle_layout = QVBoxLayout(vehicle_page)
        vehicle_form = QFormLayout()
        self.vin_edit = QLineEdit()
        self.vin_edit.setMaxLength(17)
        self.vin_edit.setPlaceholderText("17-character VIN")
        self.make_edit = QLineEdit()
        self.make_edit.setPlaceholderText("Manufacturer")
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Model / series")
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Model year")
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Land Rover L319 (LR3 / LR4)", "land_rover_l319")
        self.profile_combo.addItem("Land Rover LR3 / Discovery 3 (L319)", "land_rover_l319_lr3")
        self.profile_combo.addItem("Land Rover LR4 / Discovery 4 (L319)", "land_rover_l319_lr4")
        self.profile_combo.addItem("Generic OBD-II / CAN (other vehicle)", "generic")
        vehicle_form.addRow("VIN:", self.vin_edit)
        vehicle_form.addRow("Make:", self.make_edit)
        vehicle_form.addRow("Model:", self.model_edit)
        vehicle_form.addRow("Model year:", self.year_edit)
        vehicle_form.addRow("Capability package:", self.profile_combo)
        vehicle_layout.addLayout(vehicle_form)
        vin_actions = QHBoxLayout()
        self.read_vin_button = QPushButton("Read VIN from ELM327")
        self.read_vin_button.clicked.connect(self.read_vin)
        vin_actions.addWidget(self.read_vin_button)
        self.decode_vin_button = QPushButton("Identify from VIN")
        self.decode_vin_button.clicked.connect(self.decode_vin)
        vin_actions.addWidget(self.decode_vin_button)
        vehicle_layout.addLayout(vin_actions)
        self.vin_status = QLabel(
            "The VIN is read using the standard OBD-II Mode 09 PID 02 request when "
            "an ELM327 adapter is selected. Other adapters may require transmit-capable "
            "firmware or a manual VIN."
        )
        self.vin_status.setWordWrap(True)
        self.vin_status.setObjectName("mutedText")
        vehicle_layout.addWidget(self.vin_status)
        vehicle_layout.addStretch()
        self.pages.addWidget(vehicle_page)

        # Page 3: review
        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        self.review_text = QPlainTextEdit()
        self.review_text.setReadOnly(True)
        review_layout.addWidget(self.review_text)
        self.pages.addWidget(review_page)

        footer = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("splashContinue")
        self.next_button.clicked.connect(self.go_next)
        self.skip_button = QPushButton("Skip to full workspace")
        self.skip_button.clicked.connect(self.reject)
        self.finish_button = QPushButton("Finish setup")
        self.finish_button.setObjectName("splashContinue")
        self.finish_button.clicked.connect(self.finish_setup)
        footer.addWidget(self.back_button)
        footer.addStretch()
        footer.addWidget(self.skip_button)
        footer.addWidget(self.next_button)
        footer.addWidget(self.finish_button)
        root.addLayout(footer)

        settings = current_settings or {}
        saved_interface = settings.get("interface")
        saved_channel = settings.get("channel", "")
        if saved_interface:
            select_connection_backend(
                self.interface_combo, self.show_advanced_interfaces, saved_interface
            )
        self.channel_edit.setEditText(str(saved_channel or ""))
        self.detect_interfaces()
        self._show_page(0)
        self.interface_combo.currentIndexChanged.connect(self._update_vin_query_availability)
        self.channel_edit.editTextChanged.connect(self._update_vin_query_availability)

    def detect_interfaces(self):
        current = self.channel_edit.currentText().strip()
        ports = discover_all_interfaces()
        self.channel_edit.clear()
        for port in ports:
            self.channel_edit.addItem(port["device"], port["device"])
            index = self.channel_edit.count() - 1
            self.channel_edit.setItemData(
                index,
                f'{port["label"]} | {port["description"]} | '
                f'VID:PID {port["vid"] or "----"}:{port["pid"] or "----"}',
                Qt.ToolTipRole,
            )
        if current:
            self.channel_edit.setEditText(current)
        elif len(ports) == 1:
            self.channel_edit.setCurrentIndex(0)
        elif not ports:
            self.channel_edit.setEditText("")
        recognized = [p for p in ports if p["kind"] in ("esp32", "elm327", "slcan", "j2534")]
        if len(recognized) == 1:
            candidate = recognized[0]
            preferred = {
                "elm327": "elm327_obd",
                "esp32": "esp32_framed_usb",
            }.get(candidate["kind"], candidate["kind"])
            select_connection_backend(
                self.interface_combo, self.show_advanced_interfaces, preferred
            )
            self.channel_edit.setEditText(candidate["device"])
        self.interface_status.setText(
            ("Detected: " + "; ".join(f'{p["device"]} — {p["label"]}' for p in ports))
            if ports else
            "No serial adapters detected. You can still enter a channel manually or continue without hardware."
        )
        self._update_vin_query_availability()

    def _update_vin_query_availability(self):
        data = self.interface_combo.currentData()
        is_elm = bool(data and data[0] in ("elm327", "elm327_obd"))
        self.read_vin_button.setEnabled(is_elm and bool(self.channel_edit.currentText().strip()))
        if is_elm:
            self.read_vin_button.setToolTip("Send the read-only OBD-II Mode 09 PID 02 VIN request.")
        else:
            self.read_vin_button.setToolTip(
                "Active VIN querying is currently implemented for ELM327 serial adapters. "
                "ESP32 firmware is presently receive-only."
            )

    def read_vin(self):
        data = self.interface_combo.currentData()
        port = self.channel_edit.currentText().strip()
        if not data or data[0] != "elm327" or not port:
            return
        self.read_vin_button.setEnabled(False)
        self.decode_vin_button.setEnabled(False)
        self.vin_edit.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.channel_edit.setEnabled(False)
        self.next_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.vin_status.setText("Querying VIN with OBD-II Mode 09 PID 02…")
        self._vin_worker = VinQueryWorker(port, self)
        self._vin_worker.completed.connect(self._vin_query_completed)
        self._vin_worker.failed.connect(self._vin_query_failed)
        self._vin_worker.finished.connect(self._vin_query_finished)
        self._vin_worker.start()

    def _vin_query_completed(self, vin):
        self.vin_edit.setText(vin)
        self.decode_vin()
        self.vin_status.setText("VIN read successfully from the vehicle. " + self.vin_status.text())

    def _vin_query_failed(self, message):
        self.vin_status.setText(f"VIN query failed: {message}")

    def _vin_query_finished(self):
        if self._decode_worker and self._decode_worker.isRunning():
            return
        self.decode_vin_button.setEnabled(True)
        self.vin_edit.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.channel_edit.setEnabled(True)
        self.next_button.setEnabled(True)
        self.back_button.setEnabled(self.pages.currentIndex() > 0)
        self.skip_button.setEnabled(True)
        self._update_vin_query_availability()

    def _apply_vehicle_identification(self, result):
        self._decoded = result
        if result.get("make"):
            self.make_edit.setText(result["make"])
        if result.get("model"):
            self.model_edit.setText(result["model"])
        if result.get("model_year"):
            self.year_edit.setText(str(result["model_year"]))
        profile_id = result.get("profile_id", "generic")
        if profile_id == "generic":
            make = str(result.get("make") or "").strip().lower()
            model = str(result.get("model") or "").strip().lower()
            year = result.get("model_year")
            # Unknown identity defaults to the shared L319 workspace. A VIN
            # decode naming another make/model explicitly selects generic.
            if not make and not model:
                profile_id = "land_rover_l319"
            elif "land rover" in make and not model:
                profile_id = "land_rover_l319"
            elif "land rover" in make and (
                "discovery" in model or "lr3" in model or "lr4" in model
            ):
                if "discovery 3" in model or "lr3" in model or (year and 2005 <= year <= 2009):
                    profile_id = "land_rover_l319_lr3"
                elif "discovery 4" in model or "lr4" in model or (year and 2010 <= year <= 2016):
                    profile_id = "land_rover_l319_lr4"
                else:
                    profile_id = "land_rover_l319"
        profile_index = self.profile_combo.findData(profile_id)
        if profile_index >= 0:
            self.profile_combo.setCurrentIndex(profile_index)

    def decode_vin(self):
        vin = validate_vin(self.vin_edit.text())
        if not vin:
            self.vin_status.setText("Enter a valid 17-character VIN before identifying the vehicle.")
            return
        result = identify_vehicle(vin)
        self._apply_vehicle_identification(result)
        if result.get("profile_id") in ("land_rover_l319_lr3", "land_rover_l319_lr4"):
            self.vin_status.setText(
                f'{result["confidence"].upper()} LOCAL MATCH: {result["reason"]} '
                "Review the suggested vehicle details before continuing."
            )
            return
        self.vin_status.setText(
            "No installed manufacturer-specific package matches this VIN. "
            "Checking NHTSA vPIC for manufacturer-reported make, model and year…"
        )
        self.read_vin_button.setEnabled(False)
        self.decode_vin_button.setEnabled(False)
        self.vin_edit.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.channel_edit.setEnabled(False)
        self.next_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self._decode_worker = VinDecodeWorker(vin, self)
        self._decode_worker.completed.connect(self._vin_decode_completed)
        self._decode_worker.failed.connect(self._vin_decode_failed)
        self._decode_worker.finished.connect(self._vin_decode_finished)
        self._decode_worker.start()

    def _vin_decode_completed(self, result):
        self._apply_vehicle_identification(result)
        details = [
            f'{result.get("make") or "Unknown make"} {result.get("model") or "Unknown model"}',
            str(result.get("model_year") or "Year unavailable"),
        ]
        if result.get("engine_model"):
            details.append(result["engine_model"])
        self.vin_status.setText(
            "NHTSA vPIC result: " + " | ".join(details)
            + ". Generic OBD-II/CAN package selected; manufacturer-specific support is not inferred."
        )

    def _vin_decode_failed(self, message):
        self.vin_status.setText(
            "Online VIN decoding unavailable. The VIN remains saved as an unidentified "
            "vehicle; enter make, model and year manually if needed. " + message
        )

    def _vin_decode_finished(self):
        self.decode_vin_button.setEnabled(True)
        self.vin_edit.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.channel_edit.setEnabled(True)
        self.next_button.setEnabled(True)
        self.back_button.setEnabled(self.pages.currentIndex() > 0)
        self.skip_button.setEnabled(True)
        self._update_vin_query_availability()

    def _show_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Connect an interface", "Identify your vehicle", "Review configuration"]
        descriptions = [
            "Detect a supported adapter or choose one manually. Detection inventories local interfaces; it does not transmit to the vehicle.",
            "Read the VIN with a supported adapter, enter it manually, or provide vehicle details yourself.",
            "Check the selected connection and vehicle profile before applying setup.",
        ]
        self.page_title.setText(titles[index])
        self.page_description.setText(descriptions[index])
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < 2)
        self.finish_button.setVisible(index == 2)

    def go_next(self):
        page = self.pages.currentIndex()
        if page == 0:
            self._show_page(1)
        elif page == 1:
            self._build_review()
            self._show_page(2)

    def go_back(self):
        self._show_page(max(0, self.pages.currentIndex() - 1))

    def _build_review(self):
        interface = self.interface_combo.currentData()
        channel = self.channel_edit.currentText().strip()
        profile_id = self.profile_combo.currentData() or "generic"
        vin = validate_vin(self.vin_edit.text())
        year_text = self.year_edit.text().strip()
        try:
            year = int(year_text) if year_text else None
        except ValueError:
            year = None
        self.result_data = {
            "interface": interface[0] if interface else "virtual",
            "channel": channel or (interface[1] if interface else "freerov3r"),
            "bitrate": 500000,
            "vin": vin,
            "make": self.make_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "model_year": year,
            "profile_id": profile_id,
            "identification": self._decoded or {},
        }
        rows = [
            "CONNECTION",
            f'Interface: {interface[1] if interface else "Virtual CAN"}',
            f'Port / channel: {self.result_data["channel"] or "Not selected"}',
            "",
            "VEHICLE",
            f'VIN: {vin or "Not provided"}',
            f'Make: {self.result_data["make"] or "Not specified"}',
            f'Model: {self.result_data["model"] or "Not specified"}',
            f'Model year: {year or "Not specified"}',
            f'Capability package: {self.profile_combo.currentText()}',
            "",
            "The shared L319 workspace is the default while vehicle identity is unknown. "
            "A VIN decode identifying another make/model selects the generic package.",
        ]
        self.review_text.setPlainText("\n".join(rows))

    def finish_setup(self):
        self._build_review()
        profile_id = self.result_data["profile_id"]
        year = self.result_data["model_year"]
        valid_years = {
            "land_rover_l319": range(2005, 2017),
            "land_rover_l319_lr3": range(2005, 2010),
            "land_rover_l319_lr4": range(2010, 2017),
        }
        if year is not None and profile_id in valid_years and year not in valid_years[profile_id]:
            QMessageBox.warning(
                self,
                "Vehicle profile does not match model year",
                "The selected LR3/LR4 package does not match the entered model year. "
                "Correct the year or select the generic OBD-II/CAN package.",
            )
            return
        self.accept()

    def reject(self):
        for worker in (self._vin_worker, self._decode_worker):
            if worker and worker.isRunning():
                worker.wait(8000)
        super().reject()

    def _refresh_interface_options(self, enabled=False):
        populate_connection_combo(
            self.interface_combo, include_advanced=bool(enabled)
        )
