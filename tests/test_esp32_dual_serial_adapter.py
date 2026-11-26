import time

import pytest

from freerov3r.hardware import esp32_dual_serial_adapter as dual_module
from freerov3r.models import CanFrame


class FakeAdapter:
    def __init__(self, port, baudrate=921600, timeout=0.1):
        self.port = port
        self.channel_name = port
        self.timeout = timeout
        self.connection = None
        self.frames_received = 0
        self.invalid_lines = 0
        self.alert_count = 0
        self.firmware_error_count = 0
        self.last_error = None
        self._sent = False

    @property
    def diagnostics(self):
        return {
            "connected": self.connection is not None,
            "receiver_state": "receiving" if self.frames_received else "connected/silent",
            "frames_received": self.frames_received,
            "invalid_lines": self.invalid_lines,
            "alert_count": self.alert_count,
            "firmware_error_count": self.firmware_error_count,
            "last_error": self.last_error,
            "port": self.port,
        }

    def open(self):
        self.connection = True

    def receive(self, timeout=0.1):
        if not self._sent:
            self._sent = True
            self.frames_received += 1
            return CanFrame(0x123, b"\\x01", channel=self.channel_name)
        time.sleep(min(timeout, 0.005))
        return None

    def close(self):
        self.connection = None


def test_dual_adapter_reads_two_independent_channels(monkeypatch):
    monkeypatch.setattr(dual_module, "Esp32SerialAdapter", FakeAdapter)
    adapter = dual_module.Esp32DualSerialAdapter(
        "COM4, COM5", channel_names=("HS-CAN", "MS-CAN")
    )
    adapter.open()
    try:
        frames = [adapter.receive(timeout=0.5), adapter.receive(timeout=0.5)]
        assert {frame.channel for frame in frames if frame is not None} == {
            "HS-CAN", "MS-CAN"
        }
        diagnostics = adapter.diagnostics
        assert diagnostics["connected"] is True
        assert diagnostics["frames_received"] == 2
        assert [item["channel"] for item in diagnostics["channels"]] == [
            "HS-CAN", "MS-CAN"
        ]
    finally:
        adapter.close()


def test_dual_adapter_requires_two_distinct_ports():
    with pytest.raises(ValueError, match="two different serial ports"):
        dual_module.Esp32DualSerialAdapter(["COM4", "COM4"])
    with pytest.raises(ValueError, match="two different serial ports"):
        dual_module.Esp32DualSerialAdapter(["COM4"])


def test_dual_adapter_rejects_receive_before_open():
    adapter = dual_module.Esp32DualSerialAdapter(["COM4", "COM5"])
    with pytest.raises(RuntimeError, match="not open"):
        adapter.receive()


def test_dual_adapter_queue_is_bounded_and_reports_drops_by_channel(monkeypatch):
    monkeypatch.setattr(dual_module, "Esp32SerialAdapter", FakeAdapter)
    adapter = dual_module.Esp32DualSerialAdapter(
        ["COM4", "COM5"], queue_capacity=2
    )

    assert adapter._queue_frame(CanFrame(0x100, b"\\x01", channel="HS-CAN"))
    assert adapter._queue_frame(CanFrame(0x200, b"\\x02", channel="MS-CAN"))
    assert not adapter._queue_frame(CanFrame(0x101, b"\\x03", channel="HS-CAN"))

    diagnostics = adapter.diagnostics
    assert diagnostics["queue_depth"] == 2
    assert diagnostics["queue_capacity"] == 2
    assert diagnostics["queue_high_water_mark"] == 2
    assert diagnostics["queue_dropped_frames"] == 1
    assert diagnostics["queue_dropped_by_channel"] == {"HS-CAN": 1}
    # Inspect the internal FIFO directly: public receive() correctly requires
    # an opened adapter, while this test isolates queue overflow behavior.
    assert adapter._frames.get_nowait().arbitration_id == 0x100
    assert adapter._frames.get_nowait().arbitration_id == 0x200


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, "10"])
def test_dual_adapter_rejects_invalid_queue_capacity(capacity):
    with pytest.raises(ValueError, match="positive integer"):
        dual_module.Esp32DualSerialAdapter(
            ["COM4", "COM5"], queue_capacity=capacity
        )


def test_open_clears_stale_queue_and_overflow_counters(monkeypatch):
    class SilentAdapter(FakeAdapter):
        def receive(self, timeout=0.1):
            time.sleep(min(timeout, 0.005))
            return None

    monkeypatch.setattr(dual_module, "Esp32SerialAdapter", SilentAdapter)
    adapter = dual_module.Esp32DualSerialAdapter(
        ["COM4", "COM5"], queue_capacity=1
    )
    adapter._queue_frame(CanFrame(0x100, b"\\x01", channel="HS-CAN"))
    adapter._queue_frame(CanFrame(0x101, b"\\x02", channel="HS-CAN"))
    adapter.open()
    try:
        diagnostics = adapter.diagnostics
        assert diagnostics["queue_depth"] == 0
        assert diagnostics["queue_dropped_frames"] == 0
        assert diagnostics["queue_high_water_mark"] == 0
    finally:
        adapter.close()
