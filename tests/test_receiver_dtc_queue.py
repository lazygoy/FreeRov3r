import threading
import time

from freerov3r.app import Receiver


class DtcCapableFakeAdapter:
    description = "fake DTC adapter"

    def __init__(self):
        self.open_thread = None
        self.read_thread = None
        self.read_called = threading.Event()
        self.closed = False

    def open(self):
        self.open_thread = threading.get_ident()

    def receive(self, timeout=0.15):
        time.sleep(min(timeout, 0.01))
        return None

    def read_dtcs(self):
        self.read_thread = threading.get_ident()
        self.read_called.set()
        return [{"code": "P0133", "status": "Stored"}]

    def close(self):
        self.closed = True


def test_receiver_runs_dtc_request_on_adapter_owner_thread():
    adapter = DtcCapableFakeAdapter()
    receiver = Receiver(adapter)
    receiver.start()
    try:
        deadline = time.monotonic() + 1
        while not receiver.isRunning() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert receiver.request_dtcs()
        assert adapter.read_called.wait(1)
        assert adapter.read_thread == adapter.open_thread
    finally:
        receiver.stop()
    assert adapter.closed
