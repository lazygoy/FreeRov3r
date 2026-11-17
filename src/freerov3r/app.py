import sys
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QLabel, QMainWindow,
                               QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget)
from .hardware.python_can_adapter import PythonCanAdapter
from .hardware.esp32_serial_adapter import Esp32SerialAdapter
from .session import CaptureSession

class Receiver(QThread):
    frame_received = Signal(object)
    status = Signal(str)
    def __init__(self, adapter):
        super().__init__()
        self.adapter, self.running = adapter, True
    def run(self):
        try:
            self.adapter.open()
            self.status.emit("Connected: " + self.adapter.description)
            while self.running:
                frame = self.adapter.receive(0.15)
                if frame is not None:
                    self.frame_received.emit(frame)
        except Exception as exc:
            self.status.emit(f"Adapter error: {exc}")
        finally:
            self.adapter.close()
    def stop(self):
        self.running = False
        self.wait(1500)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreeRov3r | Vehicle Diagnostics")
        self.resize(1050, 680)
        self.session, self.receiver = CaptureSession(), None
        tabs, home, layout = QTabWidget(), QWidget(), QVBoxLayout()
        layout.addWidget(QLabel("FreeRov3r development build | L319 initial target"))
        self.status = QLabel("Disconnected. Receive-only mode.")
        layout.addWidget(self.status)
        self.backend = QComboBox()
        self.backend.addItem("Virtual CAN (synthetic/dev)", ("virtual", "freerov3r"))
        self.backend.addItem("SocketCAN (Linux)", ("socketcan", "can0"))
        self.backend.addItem("FreeRov3r ESP32 serial (COM3)", ("esp32", "COM3"))
        self.backend.addItem("SLCAN adapter (COM3)", ("slcan", "COM3"))
        layout.addWidget(self.backend)
        self.connect_btn = QPushButton("Start passive capture")
        self.connect_btn.clicked.connect(self.toggle_capture)
        layout.addWidget(self.connect_btn)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        export = QPushButton("Export capture for SavvyCAN")
        export.clicked.connect(self.export_capture)
        layout.addWidget(export)
        home.setLayout(layout)
        tabs.addTab(home, "Capture")
        vehicle, vlayout = QWidget(), QVBoxLayout()
        vlayout.addWidget(QLabel("L319 profile is deliberately unpopulated pending verified vehicle data."))
        vlayout.addWidget(QLabel("Diagnostic requests, coding, adaptations and programming are not enabled."))
        vehicle.setLayout(vlayout)
        tabs.addTab(vehicle, "Vehicle")
        self.setCentralWidget(tabs)

    def toggle_capture(self):
        if self.receiver and self.receiver.isRunning():
            self.receiver.stop()
            self.receiver = None
            self.connect_btn.setText("Start passive capture")
            self.status.setText("Disconnected")
            return
        interface, channel = self.backend.currentData()
        adapter = (Esp32SerialAdapter(port=channel) if interface == "esp32"
                   else PythonCanAdapter(interface, channel))
        self.receiver = Receiver(adapter)
        self.receiver.frame_received.connect(self.on_frame)
        self.receiver.status.connect(self.status.setText)
        self.receiver.start()
        self.connect_btn.setText("Stop capture")

    def on_frame(self, frame):
        self.session.add(frame)
        self.log.appendPlainText(f"{frame.timestamp or 0:.6f}  {frame.arbitration_id:08X}  {frame.data.hex(' ').upper()}")

    def export_capture(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CAN capture", "capture.csv",
                                               "CSV (*.csv);;candump (*.log)")
        if not path:
            return
        self.session.export_candump(path) if path.lower().endswith(".log") else self.session.export_csv(path)
        self.status.setText(f"Exported {len(self.session.frames)} frames")

    def closeEvent(self, event):
        if self.receiver and self.receiver.isRunning():
            self.receiver.stop()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
