import time

from freerov3r.hardware import esp32_dual_framed_adapter as module


class FakeFramedAdapter:
    def __init__(self, port, baudrate=921600, timeout=0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.channel_names = {}
        self.connected = False
        self.frames = 0
        self.clock_calibration = None

    @property
    def diagnostics(self):
        return {
            "connected": self.connected,
            "frames_received": self.frames,
            "receiver_state": "receiving" if self.connected else "disconnected",
            "clock_calibration": self.clock_calibration,
        }

    def open(self):
        self.connected = True

    def receive(self, timeout=0.1):
        time.sleep(min(timeout, 0.01))
        return None

    def request_clock_sync(self, timeout=1.0):
        return {"round_trip_seconds": 0.001}

    def close(self):
        self.connected = False


def test_dual_framed_adapter_opens_both_receivers_and_reports_channels(monkeypatch):
    monkeypatch.setattr(module, "Esp32FramedSerialAdapter", FakeFramedAdapter)
    adapter = module.Esp32DualFramedSerialAdapter(
        ["COM4", "COM5"], channel_names=("HS-CAN", "MS-CAN")
    )
    adapter.open()
    try:
        report = adapter.diagnostics
        assert report["connected"] is True
        assert [item["channel"] for item in report["channels"]] == [
            "HS-CAN", "MS-CAN"
        ]
        assert all(item["connected"] for item in report["channels"])
        assert adapter.adapters[0].channel_names == {0: "HS-CAN", 1: "HS-CAN"}
        assert adapter.adapters[1].channel_names == {0: "MS-CAN", 1: "MS-CAN"}
    finally:
        adapter.close()
    assert adapter.diagnostics["connected"] is False


def test_dual_framed_adapter_rejects_duplicate_ports():
    try:
        module.Esp32DualFramedSerialAdapter(["COM4", "com4"])
    except ValueError as exc:
        assert "different COM ports" in str(exc)
    else:
        raise AssertionError("duplicate ports must be rejected")


def test_dual_framed_adapter_requires_two_channel_names():
    try:
        module.Esp32DualFramedSerialAdapter(["COM4", "COM5"], channel_names=("HS-CAN",))
    except ValueError as exc:
        assert "two channel names" in str(exc)
    else:
        raise AssertionError("invalid channel mapping must be rejected")
