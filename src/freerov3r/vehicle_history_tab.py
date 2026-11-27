"""Vehicle history browsing and export workspace."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView, QPlainTextEdit,
    QFileDialog, QMessageBox,
)
from .vehicle_history import (
    VehicleHistoryStore, filter_dtc_scan_events, format_dtc_scan_event,
    filter_mode06_scan_events, format_mode06_scan_event,
    filter_readiness_scan_events, filter_freeze_frame_scan_events,
    filter_vehicle_info_scan_events, filter_obd_scan_events,
    format_readiness_scan_event, format_freeze_frame_scan_event,
    format_vehicle_info_scan_event, export_history_json, export_history_csv,
    search_history_events, format_capture_event, filter_can_activity_events,
)


class VehicleHistoryTab(QWidget):
    def __init__(self, store: VehicleHistoryStore, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        self.recovery_notice = QLabel()
        self.recovery_notice.setWordWrap(True)
        self.recovery_notice.setObjectName("historyRecoveryNotice")
        self.recovery_notice.setStyleSheet(
            "QLabel#historyRecoveryNotice { color: #8a4b08; "
            "background: #fff4df; border: 1px solid #e7c98e; "
            "border-radius: 5px; padding: 8px; }"
        )
        layout.addWidget(self.recovery_notice)
        self.update_recovery_notice()
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Vehicle VIN:"))
        self.vin_filter = QComboBox()
        self.vin_filter.currentIndexChanged.connect(self.refresh_events)
        controls.addWidget(self.vin_filter, 1)
        controls.addWidget(QLabel("Event type:"))
        self.event_filter = QComboBox()
        self.event_filter.addItem("All events", "all")
        self.event_filter.addItem("CAN activity", "can")
        self.event_filter.addItem("All OBD-II scans", "obd")
        self.event_filter.addItem("DTC scans", "dtc")
        self.event_filter.addItem("Readiness scans", "readiness")
        self.event_filter.addItem("Freeze-frame scans", "freeze_frame")
        self.event_filter.addItem("Vehicle information scans", "vehicle_info")
        self.event_filter.addItem("Mode 06 scans", "mode06")
        self.event_filter.currentIndexChanged.connect(self.refresh_events)
        controls.addWidget(self.event_filter)
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Search VIN, event, summary, or details...")
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.textChanged.connect(self.refresh_events)
        controls.addWidget(self.search_filter, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(refresh_btn)
        export_json_btn = QPushButton("Export JSON")
        export_json_btn.clicked.connect(lambda: self.export_history("json"))
        controls.addWidget(export_json_btn)
        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.clicked.connect(lambda: self.export_history("csv"))
        controls.addWidget(export_csv_btn)
        layout.addLayout(controls)

        split = QHBoxLayout()
        self.events_tree = QTreeWidget()
        self.events_tree.setHeaderLabels(["Date / time", "Event", "Summary"])
        self.events_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.events_tree.itemSelectionChanged.connect(self.show_details)
        split.addWidget(self.events_tree, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a history entry to inspect its recorded details.")
        split.addWidget(self.details, 2)
        layout.addLayout(split)
        self.refresh()

    def update_recovery_notice(self):
        if self.store.load_error:
            self.recovery_notice.setText(
                "Vehicle history could not be read. New history events will not be saved "
                "until the file-access problem is fixed. Original file: "
                f"{self.store.path}\\nError: {self.store.load_error}"
            )
            self.recovery_notice.setVisible(True)
        elif self.store.recovery_backup_path:
            self.recovery_notice.setText(
                "A damaged vehicle-history file was preserved for recovery. "
                "A new history file will be created when the next event is recorded. "
                f"Backup: {self.store.recovery_backup_path}"
            )
            self.recovery_notice.setVisible(True)
        else:
            self.recovery_notice.clear()
            self.recovery_notice.setVisible(False)

    def refresh(self):
        self.update_recovery_notice()
        current = self.vin_filter.currentData()
        self.vin_filter.blockSignals(True)
        self.vin_filter.clear()
        self.vin_filter.addItem("All vehicles", None)
        for vin in self.store.vehicles():
            self.vin_filter.addItem(vin, vin)
        index = self.vin_filter.findData(current)
        self.vin_filter.setCurrentIndex(index if index >= 0 else 0)
        self.vin_filter.blockSignals(False)
        self.refresh_events()

    def selected_events(self):
        selected_vin = self.vin_filter.currentData()
        events = self.store.events if selected_vin is None else self.store.for_vin(selected_vin)
        event_filter = self.event_filter.currentData()
        if event_filter == "can":
            events = filter_can_activity_events(events)
        elif event_filter == "obd":
            events = filter_obd_scan_events(events)
        elif event_filter == "dtc":
            events = filter_dtc_scan_events(events)
        elif event_filter == "readiness":
            events = filter_readiness_scan_events(events)
        elif event_filter == "freeze_frame":
            events = filter_freeze_frame_scan_events(events)
        elif event_filter == "vehicle_info":
            events = filter_vehicle_info_scan_events(events)
        elif event_filter == "mode06":
            events = filter_mode06_scan_events(events)
        events = search_history_events(events, self.search_filter.text())
        return events

    def export_history(self, format_name):
        if format_name == "json":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export vehicle history as JSON", "vehicle_history.json",
                "JSON files (*.json)",
            )
            exporter = export_history_json
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export vehicle history as CSV", "vehicle_history.csv",
                "CSV files (*.csv)",
            )
            exporter = export_history_csv
        if not path:
            return
        try:
            exported = exporter(path, self.selected_events())
        except OSError as exc:
            QMessageBox.warning(self, "History export failed", str(exc))
            return
        QMessageBox.information(
            self, "History exported",
            f"Exported {len(self.selected_events())} event(s) to:\n{exported}",
        )

    def refresh_events(self):
        self.events_tree.clear()
        events = self.selected_events()
        for event in reversed(events):
            timestamp = event.get("timestamp", "")
            item = QTreeWidgetItem([
                timestamp.replace("T", " "),
                event.get("type", ""),
                event.get("summary", ""),
            ])
            item.setData(0, Qt.UserRole, event)
            self.events_tree.addTopLevelItem(item)
        self.events_tree.resizeColumnToContents(0)
        self.events_tree.resizeColumnToContents(1)
        self.details.clear()

    def show_details(self):
        item = self.events_tree.currentItem()
        event = item.data(0, Qt.UserRole) if item else None
        if not event:
            self.details.clear()
        elif event.get("type") in {"dtc_scan_completed", "dtc_scan_failed"}:
            self.details.setPlainText(format_dtc_scan_event(event))
        elif event.get("type") in {"readiness_scan_completed", "readiness_scan_failed"}:
            self.details.setPlainText(format_readiness_scan_event(event))
        elif event.get("type") in {"monitor_tests_scan_completed", "monitor_tests_scan_failed"}:
            self.details.setPlainText(format_mode06_scan_event(event))
        elif event.get("type") in {"freeze_frame_scan_completed", "freeze_frame_scan_failed"}:
            self.details.setPlainText(format_freeze_frame_scan_event(event))
        elif event.get("type") in {"vehicle_info_scan_completed", "vehicle_info_scan_failed"}:
            self.details.setPlainText(format_vehicle_info_scan_event(event))
        elif event.get("type") in {"capture_started", "capture_completed", "vin_detected"}:
            self.details.setPlainText(format_capture_event(event))
        else:
            self.details.setPlainText(json.dumps(event, indent=2, ensure_ascii=False))
