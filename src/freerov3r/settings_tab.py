"""Application settings workspace."""

from .connection_options import populate_connection_combo, select_connection_backend

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


class SettingsTab(QWidget):
    def __init__(
        self,
        toggle_dark_mode,
        show_about_dialog,
        save_settings,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        connection_group = QGroupBox("Default connection")
        connection_form = QFormLayout(connection_group)
        self.settings_backend = QComboBox()
        populate_connection_combo(self.settings_backend)
        self.settings_channel = QLineEdit()
        self.settings_channel.setPlaceholderText("COM port or CAN channel")
        self.settings_bitrate = QComboBox()
        self.settings_bitrate.addItems(["125000", "250000", "500000", "1000000"])
        connection_form.addRow("Interface:", self.settings_backend)
        connection_form.addRow("Channel / port:", self.settings_channel)
        connection_form.addRow("CAN bitrate:", self.settings_bitrate)
        self.show_advanced_interfaces = QCheckBox("Show advanced interfaces")
        self.show_advanced_interfaces.toggled.connect(self._refresh_backend_options)
        connection_form.addRow(self.show_advanced_interfaces)
        self._refresh_backend_options()
        self.settings_backend.currentIndexChanged.connect(self._update_connection_fields)
        self._update_connection_fields()
        layout.addWidget(connection_group)

        compatibility_group = QGroupBox("Hardware compatibility")
        compatibility_layout = QVBoxLayout(compatibility_group)
        compatibility_notice = QLabel(
            "Full diagnostic functionality is available only with the recommended ESP32 CAN interface. "
            "Bluetooth ELM327, Wi-Fi, and other third-party adapters are supported on a limited basis "
            "where their hardware and protocols allow. They may not provide complete CAN traffic, "
            "full module coverage, or advanced diagnostic functions."
        )
        compatibility_notice.setObjectName("hardwareCompatibilityNotice")
        compatibility_notice.setWordWrap(True)
        compatibility_layout.addWidget(compatibility_notice)
        preferred_hardware = QLabel("Preferred interface: ESP32 CAN adapter")
        preferred_hardware.setObjectName("preferredHardwareLabel")
        compatibility_layout.addWidget(preferred_hardware)
        layout.addWidget(compatibility_group)

        display_group = QGroupBox("Display and logging")
        display_layout = QVBoxLayout(display_group)
        self.dark_mode_cb = QCheckBox("Dark mode")
        self.dark_mode_cb.toggled.connect(toggle_dark_mode)
        display_layout.addWidget(self.dark_mode_cb)
        row = QHBoxLayout()
        row.addWidget(QLabel("Maximum log lines:"))
        self.max_log_spin = QSpinBox()
        self.max_log_spin.setRange(500, 50000)
        row.addWidget(self.max_log_spin)
        display_layout.addLayout(row)
        layout.addWidget(display_group)

        graph_group = QGroupBox("Graphing")
        graph_layout = QFormLayout(graph_group)
        self.auto_refresh_graph_cb = QCheckBox("Refresh graph while listening")
        self.graph_refresh_spin = QSpinBox()
        self.graph_refresh_spin.setRange(250, 5000)
        self.graph_refresh_spin.setSingleStep(250)
        self.graph_refresh_spin.setSuffix(" ms")
        graph_layout.addRow(self.auto_refresh_graph_cb)
        graph_layout.addRow("Graph refresh interval:", self.graph_refresh_spin)
        layout.addWidget(graph_group)

        about_group = QGroupBox("About")
        about_layout = QVBoxLayout(about_group)
        about_btn = QPushButton("About FreeRov3r")
        about_btn.setToolTip("Software information and project attribution")
        about_btn.clicked.connect(show_about_dialog)
        about_layout.addWidget(about_btn)
        layout.addWidget(about_group)

        layout.addStretch()
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(save_settings)
        layout.addWidget(save_btn)

    def _refresh_backend_options(self, enabled=False):
        populate_connection_combo(
            self.settings_backend, include_advanced=bool(enabled)
        )
        self._update_connection_fields()

    def select_backend(self, interface):
        return select_connection_backend(
            self.settings_backend, self.show_advanced_interfaces, interface
        )

    def _update_connection_fields(self, *_args):
        data = self.settings_backend.currentData()
        interface = data[0] if data else ""
        if interface == "elm327_obd":
            self.settings_channel.setPlaceholderText("ELM327 USB / Bluetooth serial COM port")
            self.settings_bitrate.setEnabled(False)
        elif interface == "esp32_framed_dual_wifi":
            self.settings_channel.setPlaceholderText("ESP32 #1 IP[:port], ESP32 #2 IP[:port]")
            self.settings_bitrate.setEnabled(True)
        elif interface == "esp32_framed_dual_usb":
            self.settings_channel.setPlaceholderText("ESP32 #1 COM port, ESP32 #2 COM port")
            self.settings_bitrate.setEnabled(True)
        else:
            self.settings_channel.setPlaceholderText("COM port or CAN channel")
            self.settings_bitrate.setEnabled(True)
