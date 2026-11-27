"""Vehicle identity and sensor data workspace."""

from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)


class SensorsTab(QWidget):
    def __init__(
        self,
        add_or_update_vehicle,
        set_current_vehicle,
        on_vehicle_selected,
        export_llm_report,
        export_sensor_csv,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        vehicle_group = QGroupBox("Vehicle")
        vlayout = QVBoxLayout(vehicle_group)
        form = QFormLayout()
        self.vin_edit = QLineEdit()
        self.nickname_edit = QLineEdit()
        form.addRow("VIN:", self.vin_edit)
        form.addRow("Nickname:", self.nickname_edit)
        vlayout.addLayout(form)

        vbtn = QHBoxLayout()
        add_btn = QPushButton("Save vehicle")
        add_btn.clicked.connect(add_or_update_vehicle)
        set_btn = QPushButton("Use selected")
        set_btn.clicked.connect(set_current_vehicle)
        vbtn.addWidget(add_btn)
        vbtn.addWidget(set_btn)
        vlayout.addLayout(vbtn)

        self.vehicle_list = QListWidget()
        self.vehicle_list.itemClicked.connect(on_vehicle_selected)
        vlayout.addWidget(self.vehicle_list)
        self.current_vehicle_label = QLabel("No vehicle selected")
        vlayout.addWidget(self.current_vehicle_label)
        layout.addWidget(vehicle_group)

        actions = QHBoxLayout()
        llm_btn = QPushButton("Export LLM report")
        llm_btn.clicked.connect(export_llm_report)
        csv_btn = QPushButton("Export CSV")
        csv_btn.clicked.connect(export_sensor_csv)
        actions.addWidget(llm_btn)
        actions.addWidget(csv_btn)
        layout.addLayout(actions)

        self.sensor_log = QPlainTextEdit()
        self.sensor_log.setReadOnly(True)
        self.sensor_log.setMaximumBlockCount(2000)
        layout.addWidget(self.sensor_log)
