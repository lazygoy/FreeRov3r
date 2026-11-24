"""Two-port ESP32 receiver for simultaneous, independent Classical-CAN capture.

Each ESP32 has its own TWAI controller and SN65HVD230 transceiver. A worker
thread reads each serial port independently and places frames on one queue.
The adapter itself never transmits serial commands or CAN traffic.
"""
import queue
import threading

from .esp32_serial_adapter import Esp32SerialAdapter


class Esp32DualSerialAdapter:
    """Multiplex two independent ESP32 serial receivers into one CAN adapter."""

    def __init__(
        self,
        ports,
        *,
        channel_names=("HS-CAN", "MS-CAN"),
        baudrate=921600,
        timeout=0.1,
    ):
        if isinstance(ports, str):
            ports = [part.strip() for part in ports.split(",") if part.strip()]
        self.ports = list(ports or [])
        if len(self.ports) != 2 or self.ports[0] == self.ports[1]:
            raise ValueError("Dual ESP32 capture requires two different serial ports")
        if len(channel_names) != 2:
            raise ValueError("Exactly two CAN channel names are required")

        self.channel_names = tuple(channel_names)
        self.adapters = [
            Esp32SerialAdapter(port=port, baudrate=baudrate, timeout=timeout)
            for port in self.ports
        ]
        self._frames = queue.Queue()
        self._stop_event = threading.Event()
        self._threads = []
        self._worker_errors = {}
        self._opened = False

    @property
    def description(self):
        return (
            f"Dual ESP32 receive-only CAN: "
            f"{self.channel_names[0]} ({self.ports[0]}) + "
            f"{self.channel_names[1]} ({self.ports[1]})"
        )

    @property
    def diagnostics(self):
        channels = []
        for name, adapter in zip(self.channel_names, self.adapters):
            item = dict(adapter.diagnostics)
            item["channel"] = name
            if adapter.port in self._worker_errors:
                item["connected"] = False
                item["receiver_state"] = "disconnected/error"
                item["last_error"] = self._worker_errors[adapter.port]
            channels.append(item)

        return {
            "mode": "dual receive-only",
            "connected": self._opened and all(item["connected"] for item in channels),
            "receiver_state": (
                "receiving" if any(item["receiver_state"] == "receiving" for item in channels)
                else "connected/silent" if any(item["connected"] for item in channels)
                else "disconnected/error" if any("error" in item["receiver_state"] for item in channels)
                else "disconnected"
            ),
            "channels": channels,
            "frames_received": sum(item["frames_received"] for item in channels),
            "invalid_lines": sum(item["invalid_lines"] for item in channels),
            "alert_count": sum(item["alert_count"] for item in channels),
            "firmware_error_count": sum(item["firmware_error_count"] for item in channels),
        }

    def open(self):
        if self._opened:
            return
        self._stop_event.clear()
        opened = []
        try:
            for adapter, channel_name in zip(self.adapters, self.channel_names):
                adapter.channel_name = channel_name
                adapter.open()
                opened.append(adapter)
        except Exception:
            for adapter in reversed(opened):
                adapter.close()
            raise

        self._worker_errors.clear()
        self._threads = []
        for adapter in self.adapters:
            thread = threading.Thread(
                target=self._read_loop,
                args=(adapter,),
                name=f"FreeRov3r-{adapter.port}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        self._opened = True

    def _read_loop(self, adapter):
        while not self._stop_event.is_set():
            try:
                frame = adapter.receive(timeout=0.1)
            except Exception as exc:
                self._worker_errors[adapter.port] = str(exc)
                break
            if frame is not None:
                self._frames.put(frame)

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("Dual ESP32 adapter is not open")
        try:
            return self._frames.get(timeout=max(0.0, float(timeout)))
        except queue.Empty:
            return None

    def close(self):
        self._stop_event.set()
        for adapter in self.adapters:
            try:
                adapter.close()
            except Exception as exc:
                self._worker_errors[adapter.port] = str(exc)
        for thread in self._threads:
            thread.join(timeout=0.5)
        self._threads.clear()
        self._opened = False
