"""Serial line adapter for the FreeRov3r ESP32 firmware prototype.

Expected line format: arbitration_id_hex,DLC,HEXDATA
Example: 00000123,2,0102
The current firmware emits Classical CAN frames only.
"""
import serial
from .base import CanAdapter
from ..models import CanFrame

class Esp32SerialAdapter(CanAdapter):
    def __init__(self, port="COM3", baudrate=115200, timeout=0.2):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.connection = None

    @property
    def description(self):
        return f"FreeRov3r ESP32 serial: {self.port} @ {self.baudrate}"

    def open(self):
        self.connection = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def receive(self, timeout=0.2):
        if self.connection is None:
            raise RuntimeError("ESP32 serial adapter is not open")
        self.connection.timeout = timeout
        raw = self.connection.readline()
        if not raw:
            return None
        try:
            parts = raw.decode("ascii", errors="strict").strip().split(",")
            if len(parts) != 3:
                return None  # Ignore boot messages and diagnostic text.
            arbitration_id = int(parts[0], 16)
            dlc = int(parts[1], 10)
            data = bytes.fromhex(parts[2])
            if not 0 <= dlc <= 8 or len(data) != dlc:
                return None
            return CanFrame(arbitration_id, data,
                            is_extended_id=arbitration_id > 0x7FF,
                            channel=self.port)
        except (UnicodeDecodeError, ValueError):
            return None
