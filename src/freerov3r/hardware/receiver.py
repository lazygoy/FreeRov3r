"""Adapter receive worker and bounded CAN frame batching.

This module owns adapter I/O on a dedicated Qt thread. UI code communicates
with the worker through queued request methods and Qt signals.
"""

import queue
import time

from PySide6.QtCore import QThread, Signal


class FrameBatcher:
    """Collect CAN frames until a size or elapsed-time threshold is reached."""

    def __init__(self, max_frames=64, interval=0.05):
        self.max_frames = max(1, int(max_frames))
        self.interval = max(0.0, float(interval))
        self.frames = []
        self.last_emit = time.monotonic()

    def add(self, frame):
        self.frames.append(frame)

    def should_flush(self, now=None):
        if not self.frames:
            return False
        now = time.monotonic() if now is None else now
        return len(self.frames) >= self.max_frames or now - self.last_emit >= self.interval

    def take(self, now=None):
        batch = self.frames
        self.frames = []
        self.last_emit = time.monotonic() if now is None else now
        return batch


class Receiver(QThread):
    frame_received = Signal(object)
    frames_received = Signal(object)
    FRAME_BATCH_SIZE = 64
    FRAME_BATCH_INTERVAL = 0.05
    status = Signal(str)
    dtcs_completed = Signal(object)
    dtcs_failed = Signal(str)
    readiness_completed = Signal(object)
    readiness_failed = Signal(str)
    freeze_frame_completed = Signal(object)
    freeze_frame_failed = Signal(str)
    vehicle_info_completed = Signal(object)
    vehicle_info_failed = Signal(str)
    monitor_tests_completed = Signal(object)
    monitor_tests_failed = Signal(str)

    def __init__(self, adapter):
        super().__init__()
        self.adapter = adapter
        self.running = True
        self._commands = queue.Queue()
        self._dtc_request_pending = False
        self._readiness_request_pending = False
        self._freeze_frame_request_pending = False
        self._vehicle_info_request_pending = False
        self._monitor_tests_request_pending = False

    def request_dtcs(self):
        """Queue a DTC read for execution by the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_dtcs", None)):
            return False
        if self._dtc_request_pending:
            return False
        self._dtc_request_pending = True
        self._commands.put("read_dtcs")
        return True

    def request_readiness(self):
        """Queue a readiness read on the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_readiness", None)):
            return False
        if self._readiness_request_pending:
            return False
        self._readiness_request_pending = True
        self._commands.put("read_readiness")
        return True

    def request_freeze_frame(self, pids, frame_number=0):
        """Queue a Mode 02 read on the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_freeze_frame", None)):
            return False
        if self._freeze_frame_request_pending:
            return False
        self._freeze_frame_request_pending = True
        self._commands.put(("read_freeze_frame", tuple(pids), int(frame_number)))
        return True

    def request_vehicle_info(self, pids=(0x02, 0x04, 0x06, 0x0A)):
        """Queue a read-only Mode 09 request on the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_vehicle_info", None)):
            return False
        if self._vehicle_info_request_pending:
            return False
        self._vehicle_info_request_pending = True
        self._commands.put(("read_vehicle_info", tuple(pids)))
        return True

    def request_monitor_tests(self):
        """Queue a read-only Mode 06 acquisition on the adapter-owning thread."""
        if not self.isRunning() or not callable(getattr(self.adapter, "read_monitor_tests", None)):
            return False
        if self._monitor_tests_request_pending:
            return False
        self._monitor_tests_request_pending = True
        self._commands.put("read_monitor_tests")
        return True

    def run(self):
        batcher = FrameBatcher(self.FRAME_BATCH_SIZE, self.FRAME_BATCH_INTERVAL)
        try:
            self.adapter.open()
            self.status.emit(f"Connected: {self.adapter.description}")
            while self.running:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == "read_dtcs":
                    try:
                        self.dtcs_completed.emit(self.adapter.read_dtcs())
                    except Exception as exc:
                        self.dtcs_failed.emit(str(exc))
                    finally:
                        self._dtc_request_pending = False
                    continue
                if isinstance(command, tuple) and command[0] == "read_freeze_frame":
                    try:
                        self.freeze_frame_completed.emit(
                            self.adapter.read_freeze_frame(command[1], command[2])
                        )
                    except Exception as exc:
                        self.freeze_frame_failed.emit(str(exc))
                    finally:
                        self._freeze_frame_request_pending = False
                    continue
                if isinstance(command, tuple) and command[0] == "read_vehicle_info":
                    try:
                        self.vehicle_info_completed.emit(
                            self.adapter.read_vehicle_info(command[1])
                        )
                    except Exception as exc:
                        self.vehicle_info_failed.emit(str(exc))
                    finally:
                        self._vehicle_info_request_pending = False
                    continue
                if command == "read_monitor_tests":
                    try:
                        self.monitor_tests_completed.emit(self.adapter.read_monitor_tests())
                    except Exception as exc:
                        self.monitor_tests_failed.emit(str(exc))
                    finally:
                        self._monitor_tests_request_pending = False
                    continue
                if command == "read_readiness":
                    try:
                        self.readiness_completed.emit(self.adapter.read_readiness())
                    except Exception as exc:
                        self.readiness_failed.emit(str(exc))
                    finally:
                        self._readiness_request_pending = False
                    continue
                try:
                    frame = self.adapter.receive(
                        self.FRAME_BATCH_INTERVAL if batcher.frames else 0.15
                    )
                except Exception as exc:
                    reconnect = getattr(self.adapter, "reconnect", None)
                    if not callable(reconnect):
                        raise
                    reason = str(exc)
                    self.status.emit(f"ESP32 disconnected: {reason}. Reconnecting...")
                    attempt = 0
                    while self.running:
                        attempt += 1
                        delay = min(15.0, 0.5 * (2 ** min(attempt - 1, 5)))
                        # Sleep in short slices so Stop remains responsive.
                        deadline = time.monotonic() + delay
                        while self.running and time.monotonic() < deadline:
                            time.sleep(min(0.1, deadline - time.monotonic()))
                        if not self.running:
                            break
                        try:
                            reconnect()
                            self.status.emit(
                                f"Reconnected: {self.adapter.description} "
                                f"(attempt {attempt}); capture continued with a gap"
                            )
                            break
                        except Exception as reconnect_error:
                            if hasattr(self.adapter, "last_error"):
                                self.adapter.last_error = str(reconnect_error)
                            self.status.emit(
                                f"ESP32 reconnect attempt {attempt} failed: "
                                f"{reconnect_error}"
                            )
                    continue
                if frame is not None:
                    self.frame_received.emit(frame)  # Preserve the per-frame adapter signal.
                    batcher.add(frame)
                if batcher.should_flush():
                    self.frames_received.emit(batcher.take())
        except Exception as exc:
            if hasattr(self.adapter, "last_error"):
                self.adapter.last_error = str(exc)
            self.status.emit(f"Adapter error: {exc}")
            if self._dtc_request_pending:
                self.dtcs_failed.emit(str(exc))
            if self._readiness_request_pending:
                self.readiness_failed.emit(str(exc))
            if self._freeze_frame_request_pending:
                self.freeze_frame_failed.emit(str(exc))
            if self._vehicle_info_request_pending:
                self.vehicle_info_failed.emit(str(exc))
            if self._monitor_tests_request_pending:
                self.monitor_tests_failed.emit(str(exc))
        finally:
            if batcher.frames:
                self.frames_received.emit(batcher.take())
            try:
                self.adapter.close()
            except Exception:
                pass
            self._dtc_request_pending = False
            self._readiness_request_pending = False
            self._freeze_frame_request_pending = False
            self._vehicle_info_request_pending = False
            self._monitor_tests_request_pending = False

    def stop(self):
        self.running = False
        self.wait(2500)
