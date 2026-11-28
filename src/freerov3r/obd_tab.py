"""Searchable OBD-II PID selection and favorite-group workspace."""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostics.obd2 import (
    OBD_PIDS, PID_CATEGORIES_ALL, PID_MULTI_VALUE_KEYS, search_mode01_pids,
)


class OBDTab(QWidget):
    """Searchable, categorized OBD-II PID selector with persistent user groups."""

    def __init__(self, settings=None, parent=None, settings_save_callback=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self.settings_save_callback = settings_save_callback
        self.pid_rows = {}
        self._loading_group = False
        self._syncing_selection = False
        self.selection_changed_callback = None
        self.selected_pids_provider = None
        self.favorites_changed_callback = None
        self.navigate_to_graph_callback = None
        self.last_sample_time = {}
        self.activity_phase = True
        layout = QVBoxLayout(self)

        note = QLabel(
            "<b>OBD-II</b><br>"
            "Read-only Mode 01 polling is available when using the dedicated ELM327 OBD-II "
            "connection. Other interfaces remain passive unless their transmit support is "
            "implemented and explicitly enabled. No ECU write commands are sent. "
            "The simulator streams clearly labeled synthetic Mode 01 values; real vehicles "
            "also populate this table when matching response frames are observed. "
            "A listed PID is not proof that the vehicle supports it."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Find sensor:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search coolant, RPM, throttle, voltage, PID…")
        self.search_edit.textChanged.connect(self.filter_pids)
        search_row.addWidget(self.search_edit, 2)
        search_row.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(PID_CATEGORIES_ALL)
        self.category_combo.currentTextChanged.connect(self.filter_pids)
        search_row.addWidget(self.category_combo, 1)
        layout.addLayout(search_row)

        favorite_row = QHBoxLayout()
        favorite_row.addWidget(QLabel("Favorite group:"))
        self.favorite_combo = QComboBox()
        self.favorite_combo.setMinimumWidth(170)
        self.favorite_combo.currentIndexChanged.connect(self._favorite_selection_changed)
        favorite_row.addWidget(self.favorite_combo, 1)
        self.load_group_btn = QPushButton("Load")
        self.load_group_btn.clicked.connect(self.load_favorite_group)
        favorite_row.addWidget(self.load_group_btn)
        self.save_group_btn = QPushButton("Save selected as…")
        self.save_group_btn.clicked.connect(self.save_favorite_group)
        favorite_row.addWidget(self.save_group_btn)
        self.delete_group_btn = QPushButton("Delete")
        self.delete_group_btn.clicked.connect(self.delete_favorite_group)
        favorite_row.addWidget(self.delete_group_btn)
        layout.addLayout(favorite_row)

        self.table = QTableWidget(len(OBD_PIDS), 7)
        self.table.setHorizontalHeaderLabels(
            ["Poll", "PID", "Category", "Sensor", "Unit", "Value", "Live"]
        )
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for row, (pid, desc, unit) in enumerate(OBD_PIDS):
            pid_int = int(pid, 16)
            category = next(
                (entry[3] for entry in search_mode01_pids() if entry[0] == pid),
                "Other",
            )
            poll_item = QTableWidgetItem()
            poll_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            poll_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, poll_item)
            self.table.setItem(row, 1, QTableWidgetItem(pid))
            self.table.setItem(row, 2, QTableWidgetItem(category))
            self.table.setItem(row, 3, QTableWidgetItem(desc))
            self.table.setItem(row, 4, QTableWidgetItem(unit))
            self.table.setItem(row, 5, QTableWidgetItem("—"))
            live_item = QTableWidgetItem("○")
            live_item.setTextAlignment(Qt.AlignCenter)
            live_item.setToolTip("No recent samples")
            self.table.setItem(row, 6, live_item)
            self.pid_rows[pid_int] = row
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 58)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(4, 65)
        self.table.setColumnWidth(5, 85)
        self.table.setColumnWidth(6, 48)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(1000)
        self.activity_timer.timeout.connect(self._update_activity_indicators)
        self.activity_timer.start()
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table, 1)

        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Request interval:"))
        self.poll_interval_ms = QSpinBox()
        self.poll_interval_ms.setRange(50, 2000)
        self.poll_interval_ms.setValue(200)
        self.poll_interval_ms.setSuffix(" ms / PID")
        self.poll_interval_ms.setToolTip(
            "Delay between sequential Mode 01 PID requests on an active ELM327 connection."
        )
        poll_row.addWidget(self.poll_interval_ms)
        select_visible_btn = QPushButton("Select visible")
        select_visible_btn.clicked.connect(lambda: self._set_visible_checks(Qt.Checked))
        poll_row.addWidget(select_visible_btn)
        clear_visible_btn = QPushButton("Clear visible")
        clear_visible_btn.clicked.connect(lambda: self._set_visible_checks(Qt.Unchecked))
        poll_row.addWidget(clear_visible_btn)
        self.open_graph_btn = QPushButton("View in Graph")
        self.open_graph_btn.clicked.connect(lambda: self.navigate_to_graph_callback() if self.navigate_to_graph_callback else None)
        poll_row.addWidget(self.open_graph_btn)
        poll_row.addStretch()
        layout.addLayout(poll_row)

        btn_row = QHBoxLayout()
        self.request_btn = QPushButton(
            "Active polling is selected by the ELM327 OBD-II connection"
        )
        self.request_btn.setEnabled(False)
        self.request_btn.setToolTip(
            "Polling starts only when the dedicated ELM327 OBD-II adapter is selected."
        )
        btn_row.addWidget(self.request_btn)
        clear_btn = QPushButton("Clear Values")
        clear_btn.clicked.connect(self.clear_values)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        dtc_group = QGroupBox("DIAGNOSTIC TROUBLE CODES")
        dtc_layout = QVBoxLayout(dtc_group)
        dtc_actions = QHBoxLayout()
        self.read_dtcs_btn = QPushButton("Read Stored / Pending / Permanent Codes")
        self.read_dtcs_btn.setEnabled(False)
        self.read_dtcs_btn.setToolTip(
            "Uses standard read-only OBD-II services 03, 07 and 0A on an active ELM327 OBD-II connection."
        )
        self.read_dtcs_btn.clicked.connect(self.request_dtc_scan)
        dtc_actions.addWidget(self.read_dtcs_btn)
        self.dtc_status_label = QLabel("Connect an ELM327 OBD-II adapter to read trouble codes.")
        self.dtc_status_label.setWordWrap(True)
        dtc_actions.addWidget(self.dtc_status_label, 1)
        dtc_layout.addLayout(dtc_actions)
        self.dtc_table = QTableWidget(0, 5)
        self.dtc_table.setHorizontalHeaderLabels(
            ["Code", "Status", "Response ECU", "Channel", "Raw"]
        )
        self.dtc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.dtc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.dtc_table.setMaximumHeight(190)
        self.dtc_table.setAlternatingRowColors(True)
        self.dtc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        dtc_layout.addWidget(self.dtc_table)
        layout.addWidget(dtc_group)

        readiness_group = QGroupBox("READINESS MONITORS (MODE 01 PID 01)")
        readiness_layout = QVBoxLayout(readiness_group)
        readiness_actions = QHBoxLayout()
        self.read_readiness_btn = QPushButton("Read Readiness")
        self.read_readiness_btn.setEnabled(False)
        self.read_readiness_btn.setToolTip(
            "Read-only OBD-II Mode 01 PID 01 request. Runs through the adapter-owning thread."
        )
        self.read_readiness_btn.clicked.connect(self.request_readiness_scan)
        readiness_actions.addWidget(self.read_readiness_btn)
        self.readiness_status_label = QLabel(
            "Connect an ELM327 OBD-II adapter to read inspection readiness."
        )
        self.readiness_status_label.setWordWrap(True)
        readiness_actions.addWidget(self.readiness_status_label, 1)
        readiness_layout.addLayout(readiness_actions)
        self.readiness_table = QTableWidget(0, 3)
        self.readiness_table.setHorizontalHeaderLabels(["Monitor", "Supported", "Complete"])
        self.readiness_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.readiness_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.readiness_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.readiness_table.setMaximumHeight(220)
        self.readiness_table.setAlternatingRowColors(True)
        self.readiness_table.setEditTriggers(QTableWidget.NoEditTriggers)
        readiness_layout.addWidget(self.readiness_table)
        freeze_group = QGroupBox("FREEZE-FRAME DATA (MODE 02)")
        freeze_layout = QVBoxLayout(freeze_group)
        self.freeze_frame_source_note = QLabel(
            "Freeze Frame uses the OBD-II PIDs selected in the Graph workspace. "
            "Choose or change those signals in Graph before requesting Mode 02 data."
        )
        self.freeze_frame_source_note.setWordWrap(True)
        self.freeze_frame_source_note.setObjectName("freezeFrameSourceNote")
        freeze_layout.addWidget(self.freeze_frame_source_note)
        freeze_actions = QHBoxLayout()
        self.read_freeze_frame_btn = QPushButton("Read Freeze Frame")
        self.read_freeze_frame_btn.setEnabled(False)
        self.read_freeze_frame_btn.setToolTip(
            "Read-only Mode 02 request for the currently selected PIDs and frame number."
        )
        self.read_freeze_frame_btn.clicked.connect(self.request_freeze_frame_scan)
        freeze_actions.addWidget(self.read_freeze_frame_btn)
        self.freeze_frame_number = QSpinBox()
        self.freeze_frame_number.setRange(0, 255)
        self.freeze_frame_number.setValue(0)
        self.freeze_frame_number.setPrefix("Frame ")
        freeze_actions.addWidget(self.freeze_frame_number)
        self.freeze_frame_status_label = QLabel(
            "Connect an ELM327 OBD-II adapter. PID selection comes from the Graph workspace."
        )
        self.freeze_frame_status_label.setWordWrap(True)
        freeze_actions.addWidget(self.freeze_frame_status_label, 1)
        freeze_layout.addLayout(freeze_actions)
        self.freeze_frame_table = QTableWidget(0, 6)
        self.freeze_frame_table.setHorizontalHeaderLabels(
            ["PID", "Measurement", "Value", "Unit", "ECU", "Raw"]
        )
        self.freeze_frame_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.freeze_frame_table.setMaximumHeight(220)
        self.freeze_frame_table.setAlternatingRowColors(True)
        self.freeze_frame_table.setEditTriggers(QTableWidget.NoEditTriggers)
        freeze_layout.addWidget(self.freeze_frame_table)
        layout.addWidget(freeze_group)
        self.read_freeze_frame_callback = None

        vehicle_info_group = QGroupBox("VEHICLE / ECU IDENTIFICATION (MODE 09)")
        vehicle_info_layout = QVBoxLayout(vehicle_info_group)
        vehicle_info_actions = QHBoxLayout()
        self.read_vehicle_info_btn = QPushButton("Read Vehicle Information")
        self.read_vehicle_info_btn.setEnabled(False)
        self.read_vehicle_info_btn.setToolTip(
            "Read-only SAE J1979 Mode 09 requests for VIN, calibration IDs, CVNs and ECU name."
        )
        self.read_vehicle_info_btn.clicked.connect(self.request_vehicle_info_scan)
        vehicle_info_actions.addWidget(self.read_vehicle_info_btn)
        self.vehicle_info_status_label = QLabel(
            "Connect an ELM327 OBD-II adapter to read ECU-reported identification."
        )
        self.vehicle_info_status_label.setWordWrap(True)
        vehicle_info_actions.addWidget(self.vehicle_info_status_label, 1)
        vehicle_info_layout.addLayout(vehicle_info_actions)
        self.vehicle_info_table = QTableWidget(0, 6)
        self.vehicle_info_table.setHorizontalHeaderLabels(
            ["PID", "Information", "Value", "Response ECU", "Channel", "Raw"]
        )
        self.vehicle_info_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.vehicle_info_table.setMaximumHeight(220)
        self.vehicle_info_table.setAlternatingRowColors(True)
        self.vehicle_info_table.setEditTriggers(QTableWidget.NoEditTriggers)
        vehicle_info_layout.addWidget(self.vehicle_info_table)
        layout.addWidget(vehicle_info_group)

        monitor_tests_group = QGroupBox("ON-BOARD MONITOR TEST RESULTS (MODE 06)")
        monitor_tests_layout = QVBoxLayout(monitor_tests_group)
        monitor_tests_actions = QHBoxLayout()
        self.read_monitor_tests_btn = QPushButton("Read Monitor Tests")
        self.read_monitor_tests_btn.setEnabled(False)
        self.read_monitor_tests_btn.setToolTip(
            "Read-only SAE J1979 Mode 06 requests. Values remain raw until a verified UASID scale is available."
        )
        self.read_monitor_tests_btn.clicked.connect(self.request_monitor_tests_scan)
        monitor_tests_actions.addWidget(self.read_monitor_tests_btn)
        self.monitor_tests_status_label = QLabel(
            "Connect an ELM327 OBD-II adapter to read supported monitor test results."
        )
        self.monitor_tests_status_label.setWordWrap(True)
        monitor_tests_actions.addWidget(self.monitor_tests_status_label, 1)
        monitor_tests_layout.addLayout(monitor_tests_actions)
        self.monitor_tests_table = QTableWidget(0, 9)
        self.monitor_tests_table.setHorizontalHeaderLabels(
            ["MID", "TID", "UASID", "Value (raw)", "Minimum (raw)", "Maximum (raw)", "Result", "ECU", "Channel"]
        )
        self.monitor_tests_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.monitor_tests_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.monitor_tests_table.setMaximumHeight(260)
        self.monitor_tests_table.setAlternatingRowColors(True)
        self.monitor_tests_table.setEditTriggers(QTableWidget.NoEditTriggers)
        monitor_tests_layout.addWidget(self.monitor_tests_table)
        layout.addWidget(monitor_tests_group)

        self.readiness_metadata_label = QLabel("MIL and DTC count: not yet read")
        self.readiness_metadata_label.setWordWrap(True)
        readiness_layout.addWidget(self.readiness_metadata_label)
        layout.addWidget(readiness_group)
        self.read_dtcs_callback = None
        self.read_readiness_callback = None
        self.read_vehicle_info_callback = None
        self.read_monitor_tests_callback = None
        self._refresh_favorite_combo()

    def request_dtc_scan(self):
        if self.read_dtcs_callback is None:
            self.dtc_status_label.setText("Start an ELM327 OBD-II connection before requesting DTCs.")
            return
        if self.read_dtcs_callback():
            self.read_dtcs_btn.setEnabled(False)
            self.dtc_status_label.setText("Reading stored, pending and permanent DTCs…")
        else:
            self.dtc_status_label.setText("DTC read is unavailable or another read is already in progress.")

    def set_dtc_scan_enabled(self, enabled):
        self.read_dtcs_btn.setEnabled(bool(enabled))
        self.read_readiness_btn.setEnabled(bool(enabled))
        self.read_freeze_frame_btn.setEnabled(bool(enabled))
        self.read_vehicle_info_btn.setEnabled(bool(enabled))
        self.read_monitor_tests_btn.setEnabled(bool(enabled))
        if not enabled:
            self.dtc_status_label.setText("Connect an ELM327 OBD-II adapter to read trouble codes.")
            self.readiness_status_label.setText(
                "Connect an ELM327 OBD-II adapter to read inspection readiness."
            )

    def request_readiness_scan(self):
        if self.read_readiness_callback is None:
            self.readiness_status_label.setText(
                "Start an ELM327 OBD-II connection before requesting readiness."
            )
            return
        if self.read_readiness_callback():
            self.read_readiness_btn.setEnabled(False)
            self.readiness_status_label.setText("Reading Mode 01 PID 01 readiness…")
        else:
            self.readiness_status_label.setText(
                "Readiness request is unavailable or another read is already in progress."
            )

    def request_freeze_frame_scan(self):
        if self.read_freeze_frame_callback is None:
            self.freeze_frame_status_label.setText(
                "Start an ELM327 OBD-II connection before requesting freeze-frame data."
            )
            return
        pids = self.selected_pids()
        if not pids:
            self.freeze_frame_status_label.setText("Select at least one PID above.")
            return
        if self.read_freeze_frame_callback(pids, self.freeze_frame_number.value()):
            self.read_freeze_frame_btn.setEnabled(False)
            self.freeze_frame_status_label.setText("Reading selected Mode 02 freeze-frame PIDs…")
        else:
            self.freeze_frame_status_label.setText(
                "Freeze-frame request is unavailable or another read is already in progress."
            )

    def request_vehicle_info_scan(self):
        if self.read_vehicle_info_callback is None:
            self.vehicle_info_status_label.setText(
                "Start an ELM327 OBD-II connection before requesting vehicle information."
            )
            return
        if self.read_vehicle_info_callback():
            self.read_vehicle_info_btn.setEnabled(False)
            self.vehicle_info_status_label.setText("Reading Mode 09 vehicle and ECU identification…")
        else:
            self.vehicle_info_status_label.setText(
                "Vehicle-information request is unavailable or another read is already in progress."
            )

    def request_monitor_tests_scan(self):
        if self.read_monitor_tests_callback is None:
            self.monitor_tests_status_label.setText(
                "Start an ELM327 OBD-II connection before requesting Mode 06 results."
            )
            return
        if self.read_monitor_tests_callback():
            self.read_monitor_tests_btn.setEnabled(False)
            self.monitor_tests_status_label.setText("Reading supported Mode 06 monitor tests…")
        else:
            self.monitor_tests_status_label.setText(
                "Mode 06 request is unavailable or another read is already in progress."
            )

    def show_monitor_test_results(self, result):
        self.monitor_tests_table.setRowCount(0)
        supported = result.get("supported_monitor_ids", [])
        responses = result.get("responses", [])
        for response in responses:
            ecu = f"{response.get('arbitration_id', 0):08X}" + (
                " (29-bit)" if response.get("is_extended_id") else " (11-bit)"
            )
            for record in response.get("results", []):
                row = self.monitor_tests_table.rowCount()
                self.monitor_tests_table.insertRow(row)
                values = (
                    f"{response.get('monitor_id', 0):02X}",
                    f"{record.get('test_id', 0):02X}",
                    f"{record.get('unit_scaling_id', 0):02X}",
                    record.get("value_raw"),
                    record.get("minimum_raw"),
                    record.get("maximum_raw"),
                    record.get("status", "unknown"),
                    ecu,
                    response.get("channel", ""),
                )
                for column, value in enumerate(values):
                    self.monitor_tests_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.monitor_tests_status_label.setText(
            f"Read complete: {self.monitor_tests_table.rowCount()} test result(s) across "
            f"{len(responses)} ECU response(s); {len(supported)} supported monitor ID(s). "
            "Values are raw and have no inferred units."
            if responses else
            f"No valid Mode 06 result records returned. {len(supported)} supported monitor ID(s) reported."
        )
        self.read_monitor_tests_btn.setEnabled(True)

    def set_monitor_tests_scan_error(self, message):
        self.monitor_tests_status_label.setText(f"Mode 06 read failed: {message}")
        self.read_monitor_tests_btn.setEnabled(True)

    def show_vehicle_info_results(self, results):
        self.vehicle_info_table.setRowCount(0)
        for result in results:
            ecu = f"{result.get('arbitration_id', 0):08X}" + (
                " (29-bit)" if result.get("is_extended_id") else " (11-bit)"
            )
            for item in result.get("items", []):
                row = self.vehicle_info_table.rowCount()
                self.vehicle_info_table.insertRow(row)
                values = (
                    f"09 {result.get('pid', 0):02X}",
                    item.get("type", "").replace("_", " ").title(),
                    item.get("value", ""),
                    ecu,
                    result.get("channel", ""),
                    result.get("raw", ""),
                )
                for column, value in enumerate(values):
                    self.vehicle_info_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.vehicle_info_status_label.setText(
            f"Read complete: {sum(len(result.get('items', [])) for result in results)} "
            f"identification record(s) from {len(results)} ECU response(s)."
            if results else "No valid Mode 09 vehicle-information responses were returned."
        )
        self.read_vehicle_info_btn.setEnabled(True)

    def set_vehicle_info_scan_error(self, message):
        self.vehicle_info_status_label.setText(f"Vehicle-information read failed: {message}")
        self.read_vehicle_info_btn.setEnabled(True)

    def show_freeze_frame_results(self, results):
        self.freeze_frame_table.setRowCount(0)
        for result in results:
            ecu = f"{result.get('arbitration_id', 0):08X}" + (
                " (29-bit)" if result.get("is_extended_id") else " (11-bit)"
            )
            for measurement in result.get("measurements", []):
                row = self.freeze_frame_table.rowCount()
                self.freeze_frame_table.insertRow(row)
                values = (
                    result.get("pid", ""),
                    measurement.get("name", ""),
                    f"{measurement.get('value', 0):.4g}",
                    measurement.get("unit", ""),
                    ecu,
                    result.get("raw", ""),
                )
                for column, value in enumerate(values):
                    self.freeze_frame_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.freeze_frame_status_label.setText(
            f"Read complete: {len(results)} PID response(s) across the selected freeze frame."
            if results else "No valid freeze-frame responses were returned."
        )
        self.read_freeze_frame_btn.setEnabled(True)

    def set_freeze_frame_scan_error(self, message):
        self.freeze_frame_status_label.setText(f"Freeze-frame read failed: {message}")
        self.read_freeze_frame_btn.setEnabled(True)

    def show_readiness_results(self, results):
        self.readiness_table.setRowCount(0)
        for result in results:
            for monitor in result.get("monitors", []):
                row = self.readiness_table.rowCount()
                self.readiness_table.insertRow(row)
                values = (
                    monitor.get("name", "").replace("_", " ").title(),
                    "Yes" if monitor.get("supported") else "No",
                    "N/A" if monitor.get("complete") is None else
                    ("Complete" if monitor.get("complete") else "Incomplete"),
                )
                for column, value in enumerate(values):
                    self.readiness_table.setItem(row, column, QTableWidgetItem(str(value)))
        if not results:
            self.readiness_metadata_label.setText("No valid PID 01 response was returned.")
            self.readiness_status_label.setText("Read complete: no readiness response received.")
        else:
            primary = results[0]
            mil = "ON" if primary.get("mil_on") else "OFF"
            self.readiness_metadata_label.setText(
                f"MIL: {mil} | DTC count: {primary.get('dtc_count', 'Unknown')} | "
                f"Ignition: {primary.get('ignition_type', 'Unknown')} | "
                f"ECU: {primary.get('arbitration_id', 0):08X} "
                f"({'29-bit' if primary.get('is_extended_id') else '11-bit'}) | "
                f"Channel: {primary.get('channel', 'Unknown')} | Raw: {primary.get('raw', '')}"
            )
            self.readiness_status_label.setText(
                f"Read complete: {len(results)} ECU response(s). Unsupported monitors are shown as N/A."
            )
        self.read_readiness_btn.setEnabled(True)

    def set_readiness_scan_error(self, message):
        self.readiness_status_label.setText(f"Readiness read failed: {message}")
        self.read_readiness_btn.setEnabled(True)

    def show_dtc_results(self, codes):
        self.dtc_table.setRowCount(0)
        for code in codes:
            row = self.dtc_table.rowCount()
            self.dtc_table.insertRow(row)
            values = (
                code.get("code", ""),
                code.get("status", ""),
                f"{code.get('arbitration_id', 0):08X}"
                + (" (29-bit)" if code.get("is_extended_id") else " (11-bit)"),
                code.get("channel", ""),
                code.get("raw", ""),
            )
            for column, value in enumerate(values):
                self.dtc_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.dtc_status_label.setText(
            f"Read complete: {len(codes)} code record(s). "
            "Descriptions are not inferred; verify OEM-specific meaning separately."
            if codes else
            "Read complete: no stored, pending or permanent codes were returned."
        )
        self.read_dtcs_btn.setEnabled(True)

    def set_dtc_scan_error(self, message):
        self.dtc_status_label.setText(f"DTC read failed: {message}")
        self.read_dtcs_btn.setEnabled(True)

    def filter_pids(self, *_):
        query = self.search_edit.text()
        category = self.category_combo.currentText()
        visible = {int(row[0], 16) for row in search_mode01_pids(query, category)}
        for pid, row in self.pid_rows.items():
            self.table.setRowHidden(row, pid not in visible)

    def _set_visible_checks(self, state):
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, 0).setCheckState(state)

    def selected_pids(self):
        if callable(self.selected_pids_provider):
            pids = set()
            for sensor_id in self.selected_pids_provider():
                parts = str(sensor_id).lower().split("_", 2)
                if len(parts) >= 2 and parts[0] == "obd":
                    try:
                        pids.add(int(parts[1], 16))
                    except ValueError:
                        continue
            return sorted(pids)
        return [
            int(self.table.item(row, 1).text(), 16)
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]

    def selected_sensor_ids(self):
        selected = set()
        for pid in self.selected_pids():
            keys = PID_MULTI_VALUE_KEYS.get(pid)
            if keys:
                selected.update(f"obd_{pid:02X}_{key}" for key in keys)
            else:
                selected.add(f"obd_{pid:02X}")
        return selected

    def set_selected_sensor_ids(self, sensor_ids):
        selected = {str(value).lower() for value in sensor_ids}
        self._syncing_selection = True
        self.table.blockSignals(True)
        for pid, row in self.pid_rows.items():
            keys = PID_MULTI_VALUE_KEYS.get(pid, ())
            checked = f"obd_{pid:02X}" in selected or any(
                f"obd_{pid:02X}_{key}" in selected for key in keys
            )
            self.table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.table.blockSignals(False)
        self._syncing_selection = False

    def _on_table_item_changed(self, item):
        if item.column() == 0 and not self._syncing_selection and self.selection_changed_callback:
            self.selection_changed_callback(self.selected_sensor_ids())

    def _update_activity_indicators(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        self.activity_phase = not self.activity_phase
        for pid, row in self.pid_rows.items():
            item = self.table.item(row, 6)
            active = now - self.last_sample_time.get(pid, 0) <= 5.0
            item.setText("●" if active else "○")
            item.setForeground(QColor("#39d98a") if active and self.activity_phase else
                               QColor("#27885b") if active else QColor("#77818c"))
            item.setToolTip("Live data arriving" if active else "No recent samples")

    def update_value(self, pid, value):
        row = self.pid_rows.get(pid)
        if row is not None:
            if isinstance(value, str):
                display_value = value
            else:
                display_value = f"{value:.2f}".rstrip("0").rstrip(".")
            self.table.item(row, 5).setText(display_value)
            self.last_sample_time[pid] = time.monotonic()

    def clear_values(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 5).setText("—")

    def _favorite_groups(self):
        groups = self.settings.get("obd_pid_favorites", {})
        return groups if isinstance(groups, dict) else {}

    def _refresh_favorite_combo(self, selected_name=None):
        self._loading_group = True
        self.favorite_combo.clear()
        self.favorite_combo.addItem("Choose saved group…", None)
        for name in sorted(self._favorite_groups(), key=str.casefold):
            self.favorite_combo.addItem(name, name)
        if selected_name:
            index = self.favorite_combo.findData(selected_name)
            if index >= 0:
                self.favorite_combo.setCurrentIndex(index)
        self._loading_group = False
        has_group = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(has_group)
        self.delete_group_btn.setEnabled(has_group)

    def _favorite_selection_changed(self, *_):
        if self._loading_group:
            return
        has_group = self.favorite_combo.currentData() is not None
        self.load_group_btn.setEnabled(has_group)
        self.delete_group_btn.setEnabled(has_group)

    def load_favorite_group(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        sensor_ids = set()
        for value in self._favorite_groups().get(name, []):
            text = str(value).strip().lower()
            if text.startswith("obd_"):
                sensor_ids.add(text)
            else:
                try:
                    sensor_ids.add(f"obd_{int(text, 16):02X}")
                except ValueError:
                    continue
        self.set_selected_sensor_ids(sensor_ids)
        if self.selection_changed_callback:
            self.selection_changed_callback(sensor_ids)

    def save_favorite_group(self):
        pids = self.selected_pids()
        if not pids:
            QMessageBox.information(
                self, "No PIDs selected",
                "Select at least one sensor before saving a favorite group.",
            )
            return
        name, accepted = QInputDialog.getText(
            self, "Save PID group", "Group name:"
        )
        name = name.strip()
        if not accepted or not name:
            return
        groups = dict(self._favorite_groups())
        groups[name] = [f"obd_{pid:02X}" for pid in pids]
        self.settings["obd_pid_favorites"] = groups
        if self.settings_save_callback:
            self.settings_save_callback(self.settings)
        self._refresh_favorite_combo(name)
        if self.favorites_changed_callback:
            self.favorites_changed_callback(name)

    def delete_favorite_group(self):
        name = self.favorite_combo.currentData()
        if not name:
            return
        groups = dict(self._favorite_groups())
        groups.pop(name, None)
        self.settings["obd_pid_favorites"] = groups
        save_settings(self.settings)
        self._refresh_favorite_combo()
        if self.favorites_changed_callback:
            self.favorites_changed_callback()
