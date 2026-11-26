"""Two-port ESP32 receiver for simultaneous, independent Classical-CAN capture.

Each ESP32 has its own TWAI controller and SN65HVD230 transceiver. A worker
thread reads each serial port independently and places frames on one bounded
queue. The adapter itself never transmits serial commands or CAN traffic.
"""
import queue
import threading
from collections import Counter

from .esp32_serial_adapter import Esp32SerialAdapter


class Esp32DualSerialAdapter:
    """Multiplex two independent ESP32 serial receivers into one CAN adapter."""

    DEFAULT_QUEUE_CAPACITY = 10_000

    def __init__(
        self,
        ports,
        *,
        channel_names=("HS-CAN", "MS-CAN"),
        baudrate=921600,
        timeout=0.1,
        queue_capacity=DEFAULT_QUEUE_CAPACITY,
    ):
        if isinstance(ports, str):
            ports = [part.strip() for part in ports.split(",") if part.strip()]
        self.ports = list(ports or [])
        if len(self.ports) != 2 or self.ports[0] == self.ports[1]:
            raise ValueError("Dual ESP32 capture requires two different serial ports")
        if len(channel_names) != 2:
            raise ValueError("Exactly two CAN channel names are required")
        if (
            isinstance(queue_capacity, bool)
            or not isinstance(queue_capacity, int)
            or queue_capacity < 1
        ):
            raise ValueError("queue_capacity must be a positive integer")

        self.channel_names = tuple(channel_names)
        self.adapters = [
            Esp32SerialAdapter(port=port, baudrate=baudrate, timeout=timeout)
            for port in self.ports
        ]
        self.queue_capacity = queue_capacity
        self._frames = queue.Queue(maxsize=queue_capacity)
        self._stats_lock = threading.Lock()
        self._queue_dropped_by_channel = Counter()
        self._queue_high_water_mark = 0
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
        with self._stats_lock:
            worker_errors = dict(self._worker_errors)
            dropped_by_channel = dict(self._queue_dropped_by_channel)
            high_water_mark = self._queue_high_water_mark

        channels = []
        for name, adapter in zip(self.channel_names, self.adapters):
            item = dict(adapter.diagnostics)
            item["channel"] = name
            if adapter.port in worker_errors:
                item["connected"] = False
                item["receiver_state"] = "disconnected/error"
                item["last_error"] = worker_errors[adapter.port]
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
            "queue_depth": self._frames.qsize(),
            "queue_capacity": self.queue_capacity,
            "queue_high_water_mark": high_water_mark,
            "queue_dropped_frames": sum(dropped_by_channel.values()),
            "queue_dropped_by_channel": dropped_by_channel,
        }

    def _clear_pending_frames(self):
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break

    def _queue_frame(self, frame):
        """Queue without blocking serial readers; account for every overflow."""
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            channel = frame.channel or "unspecified"
            with self._stats_lock:
                self._queue_dropped_by_channel[channel] += 1
            return False

        depth = self._frames.qsize()
        with self._stats_lock:
            self._queue_high_water_mark = max(self._queue_high_water_mark, depth)
        return True

    def open(self):
        if self._opened:
            return
        self._stop_event.clear()
        self._clear_pending_frames()
        with self._stats_lock:
            self._worker_errors.clear()
            self._queue_dropped_by_channel.clear()
            self._queue_high_water_mark = 0

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
                if not self._stop_event.is_set():
                    with self._stats_lock:
                        self._worker_errors[adapter.port] = str(exc)
                break
            if frame is not None:
                self._queue_frame(frame)

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
                with self._stats_lock:
                    self._worker_errors[adapter.port] = str(exc)
        for thread in self._threads:
            thread.join(timeout=0.5)
        self._threads.clear()
        self._opened = False
