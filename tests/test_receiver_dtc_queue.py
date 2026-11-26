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



class VehicleInfoCapableFakeAdapter(DtcCapableFakeAdapter):
    description = "fake vehicle-info adapter"

    def __init__(self):
        super().__init__()
        self.vehicle_info_thread = None

    def read_vehicle_info(self, pids=(0x02, 0x04, 0x06, 0x0A)):
        self.vehicle_info_thread = threading.get_ident()
        self.read_called.set()
        return [{"service": "09", "pid": 0x02, "items": [
            {"type": "vin", "value": "1GNEK13Z54R123456"}
        ]}]


def test_receiver_runs_mode09_request_on_adapter_owner_thread():
    adapter = VehicleInfoCapableFakeAdapter()
    receiver = Receiver(adapter)
    receiver.start()
    try:
        deadline = time.monotonic() + 1
        while not receiver.isRunning() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert receiver.request_vehicle_info((0x02,))
        assert adapter.read_called.wait(1)
        assert adapter.vehicle_info_thread == adapter.open_thread
    finally:
        receiver.stop()
    assert adapter.closed



class MonitorTestsCapableFakeAdapter(DtcCapableFakeAdapter):
    description = "fake Mode 06 adapter"

    def __init__(self):
        super().__init__()
        self.monitor_tests_thread = None

    def read_monitor_tests(self):
        self.monitor_tests_thread = threading.get_ident()
        self.read_called.set()
        return {
            "supported_monitor_ids": [0x01],
            "responses": [{
                "monitor_id": 0x01,
                "results": [{
                    "test_id": 0x80,
                    "unit_scaling_id": 0x24,
                    "value_raw": 100,
                    "minimum_raw": 0,
                    "maximum_raw": 200,
                    "status": "within_limits",
                }],
            }],
        }


def test_receiver_runs_mode06_request_on_adapter_owner_thread():
    adapter = MonitorTestsCapableFakeAdapter()
    receiver = Receiver(adapter)
    receiver.start()
    try:
        deadline = time.monotonic() + 1
        while not receiver.isRunning() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert receiver.request_monitor_tests()
        assert adapter.read_called.wait(1)
        assert adapter.monitor_tests_thread == adapter.open_thread
    finally:
        receiver.stop()
    assert adapter.closed
