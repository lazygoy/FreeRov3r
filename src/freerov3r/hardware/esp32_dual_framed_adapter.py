"""Two framed ESP32 USB receivers with independent timestamp calibration."""
import queue
import threading

from .esp32_stream_adapter import Esp32FramedSerialAdapter


class Esp32DualFramedSerialAdapter:
    """Multiplex two framed USB receivers while preserving per-device clocks."""

    def __init__(self, ports, *, channel_names=("HS-CAN", "MS-CAN"),
                 baudrate=921600, timeout=0.1, queue_capacity=10000, adapters=None):
        if isinstance(ports, str):
            ports = [part.strip() for part in ports.split(",") if part.strip()]
        if len(ports or []) != 2 or str(ports[0]).casefold() == str(ports[1]).casefold():
            raise ValueError("Dual framed ESP32 capture requires two different COM ports")
        if len(channel_names) != 2:
            raise ValueError("Exactly two channel names are required")
        self.ports = [str(port) for port in ports]
        self.channel_names = tuple(channel_names)
        self.adapters = list(adapters) if adapters is not None else [
            Esp32FramedSerialAdapter(port, baudrate, timeout)
            for port in self.ports
        ]
        if len(self.adapters) != 2:
            raise ValueError("Exactly two framed ESP32 adapters are required")
        self._frames = queue.Queue(maxsize=max(1, int(queue_capacity)))
        self._stop = threading.Event()
        self._threads = []
        self._errors = {}
        self._lock = threading.Lock()
        self._opened = False
        self.queue_dropped_frames = 0

    @property
    def description(self):
        return "Dual framed ESP32 USB: " + " + ".join(self.ports)

    @property
    def diagnostics(self):
        channels = []
        for name, adapter in zip(self.channel_names, self.adapters):
            item = dict(adapter.diagnostics)
            item["channel"] = name
            with self._lock:
                error = self._errors.get(self._adapter_key(adapter))
            if error:
                item["connected"] = False
                item["receiver_state"] = "disconnected/error"
                item["last_error"] = error
            channels.append(item)
        return {
            "mode": "dual framed receive-only",
            "connected": self._opened and all(item["connected"] for item in channels),
            "channels": channels,
            "frames_received": sum(item["frames_received"] for item in channels),
            "queue_depth": self._frames.qsize(),
            "queue_capacity": self._frames.maxsize,
            "queue_dropped_frames": self.queue_dropped_frames,
        }

    @staticmethod
    def _adapter_key(adapter):
        host = getattr(adapter, "host", None)
        port = getattr(adapter, "port", None)
        if host:
            return f"{host}:{port or 3333}"
        if port is not None:
            return str(port)
        return str(getattr(adapter, "description", "ESP32 receiver"))

    def open(self):
        if self._opened:
            return
        opened = []
        try:
            for adapter, channel in zip(self.adapters, self.channel_names):
                adapter.channel_names = {0: channel, 1: channel}
                adapter.open()
                opened.append(adapter)
        except Exception:
            for adapter in reversed(opened):
                adapter.close()
            raise
        self._stop.clear()
        self._errors.clear()
        self.queue_dropped_frames = 0
        self._threads = []
        for adapter in self.adapters:
            thread = threading.Thread(
                target=self._read_loop, args=(adapter,),
                name=f"FreeRov3r-framed-{self._adapter_key(adapter)}", daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        self._opened = True

    def _read_loop(self, adapter):
        while not self._stop.is_set():
            try:
                frame = adapter.receive(timeout=0.1)
            except Exception as exc:
                if not self._stop.is_set():
                    with self._lock:
                        self._errors[self._adapter_key(adapter)] = str(exc)
                return
            if frame is not None:
                try:
                    self._frames.put_nowait(frame)
                except queue.Full:
                    with self._lock:
                        self.queue_dropped_frames += 1

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("Dual framed ESP32 adapter is not open")
        try:
            return self._frames.get(timeout=max(0.0, float(timeout)))
        except queue.Empty:
            return None

    def close(self):
        self._stop.set()
        for adapter in self.adapters:
            try:
                adapter.close()
            except Exception as exc:
                with self._lock:
                    self._errors[self._adapter_key(adapter)] = str(exc)
        for thread in self._threads:
            thread.join(timeout=0.5)
        self._threads.clear()
        self._opened = False
