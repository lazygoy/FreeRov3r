"""Live and simulated CAN capture workspace."""

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)


class CaptureTab(QWidget):
    def __init__(
        self,
        mode_label,
        settings,
        refresh_serial_ports,
        toggle_capture,
        refresh_can_display,
        export_capture,
        clear_capture_display,
        back_to_tasks,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(mode_label)

        self.status = QLabel("Not connected")
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        self.backend = QComboBox()
        self.backend.addItem("Virtual CAN (no hardware)", ("virtual", "freerov3r"))
        self.backend.addItem("Dual-channel CAN simulator (offline)", ("dual_simulator", "offline"))
        self.backend.addItem("Capture replay (JSONL, offline)", ("capture_replay", ""))
        self.backend.addItem("Simulated vehicle (synthetic OBD-II)", ("simulator", "L319-DEMO"))
        self.backend.addItem("ESP32 framed USB (binary, receive-only)", ("esp32_framed_usb", "COM3"))
        self.backend.addItem("Dual ESP32 framed USB (clock calibration)", ("esp32_framed_dual_usb", "COM3,COM4"))
        self.backend.addItem("ESP32 framed Wi-Fi TCP (binary, receive-only)", ("esp32_framed_wifi", ""))
        self.backend.addItem("ESP32 serial adapter (legacy text)", ("esp32", "COM3"))
        self.backend.addItem("ESP32 dual serial (two CAN buses)", ("esp32_dual", "COM3,COM4"))
        self.backend.addItem("ELM327 raw CAN monitor", ("elm327", ""))
        self.backend.addItem("ELM327 active OBD-II polling", ("elm327_obd", ""))
        self.backend.addItem("SocketCAN", ("socketcan", "can0"))
        self.backend.addItem("SLCAN", ("slcan", "COM3"))
        self.backend.addItem("J2534 Pass-Thru (registered driver, CAN receive)", ("j2534", ""))
        controls.addWidget(QLabel("Connection:"))
        controls.addWidget(self.backend)

        self.channel_edit = QComboBox()
        self.channel_edit.setEditable(True)
        self.channel_edit.setInsertPolicy(QComboBox.NoInsert)
        self.channel_edit.setPlaceholderText("COM port, Wi-Fi IP[:port], or CAN channel")
        self.channel_edit.setToolTip(
            "Binary ESP32 USB: select a COM port. Binary ESP32 Wi-Fi: enter the device IP "
            "or IP:port (default TCP port 3333). Legacy serial/SLCAN: select a COM port. "
            "For dual ESP32 capture, enter two different COM ports separated by a comma; "
            "first is HS-CAN, second is MS-CAN. Discovery only lists serial metadata; it "
            "does not probe devices or transmit on CAN."
        )
        controls.addWidget(self.channel_edit)

        refresh_ports_btn = QPushButton("Detect interfaces")
        refresh_ports_btn.setToolTip(
            "List USB and paired Bluetooth serial adapters without opening or probing them."
        )
        refresh_ports_btn.clicked.connect(refresh_serial_ports)
        controls.addWidget(refresh_ports_btn)

        self.bitrate = QComboBox()
        self.bitrate.addItems(["125000", "250000", "500000", "1000000"])
        controls.addWidget(QLabel("Bitrate:"))
        controls.addWidget(self.bitrate)
        layout.addLayout(controls)

        hardware_notice = QLabel(
            "ⓘ  Full diagnostic functionality requires the recommended ESP32 CAN interface. "
            "ELM327 Bluetooth/Wi-Fi and other adapters may provide limited access and may not "
            "support complete CAN monitoring, all vehicle modules, or advanced diagnostic functions."
        )
        hardware_notice.setObjectName("hardwareCompatibilityNotice")
        hardware_notice.setWordWrap(True)
        hardware_notice.setToolTip(
            "The ESP32 CAN interface is the recommended hardware for full FreeRov3r functionality."
        )
        layout.addWidget(hardware_notice)

        self.connect_btn = QPushButton("Start listening")
        self.connect_btn.clicked.connect(toggle_capture)
        layout.addWidget(self.connect_btn)

        stats = QHBoxLayout()
        self.frame_count_label = QLabel("Frames: 0")
        self.rate_label = QLabel("Rate: 0 fps")
        stats.addWidget(self.frame_count_label)
        stats.addWidget(self.rate_label)
        stats.addStretch()
        layout.addLayout(stats)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("CAN ID filter (hex / range):"))
        self.can_id_filter = QLineEdit()
        self.can_id_filter.setPlaceholderText("e.g. 7E8 or 700-7FF; blank = all")
        self.can_id_filter.setToolTip("Hexadecimal arbitration ID or inclusive range. Filtering affects display only, not capture/export.")
        self.can_id_filter.textChanged.connect(refresh_can_display)
        filter_row.addWidget(self.can_id_filter)
        self.can_format_filter = QComboBox()
        self.can_format_filter.addItems(["All", "Standard", "Extended"])
        self.can_format_filter.currentTextChanged.connect(refresh_can_display)
        filter_row.addWidget(self.can_format_filter)
        self.can_data_filter = QLineEdit()
        self.can_data_filter.setPlaceholderText("Payload bytes, e.g. 01 0A FF")
        self.can_data_filter.setToolTip(
            "Hex byte sequence matched anywhere in the payload. Display only; capture/export remain unchanged."
        )
        self.can_data_filter.textChanged.connect(refresh_can_display)
        filter_row.addWidget(self.can_data_filter)
        layout.addLayout(filter_row)

        self.monitor_summary = QLabel("Recent traffic: no frames")
        layout.addWidget(self.monitor_summary)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(settings.get("max_log_lines", 5000))
        layout.addWidget(self.log)

        export_row = QHBoxLayout()
        export_btn = QPushButton("Export capture")
        export_btn.clicked.connect(export_capture)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(clear_capture_display)
        back_btn = QPushButton("← Back to tasks")
        back_btn.clicked.connect(back_to_tasks)
        export_row.addWidget(export_btn)
        export_row.addWidget(clear_btn)
        export_row.addStretch()
        export_row.addWidget(back_btn)
        layout.addLayout(export_row)
