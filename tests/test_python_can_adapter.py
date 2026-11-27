import time

import pytest

from freerov3r.hardware import python_can_adapter as adapter_module
from freerov3r.models import CanFrame


class FakeMessage:
    arbitration_id = 0x123
    data = b"\\x01\\x02"
    is_extended_id = False
    is_remote_frame = False
    is_error_frame = False
    channel = "vcan0"
    timestamp = 1_700_000_000.25


class FakeBus:
    def __init__(self, message=None):
        self.message = message
        self.sent = []
        self.shutdown_called = False

    def recv(self, timeout):
        return self.message

    def send(self, message, timeout=None):
        self.sent.append((message, timeout))

    def shutdown(self):
        self.shutdown_called = True


def test_python_can_normalizes_host_timestamp_and_preserves_backend_timestamp(monkeypatch):
    monkeypatch.setattr(
        adapter_module.can, "Bus",
        lambda **kwargs: FakeBus(FakeMessage()),
    )
    adapter = adapter_module.PythonCanAdapter()
    adapter.open()
    try:
        before = time.monotonic()
        frame = adapter.receive()
        after = time.monotonic()
    finally:
        adapter.close()

    assert before <= frame.timestamp <= after
    assert frame.timestamp_clock_domain == "host_monotonic"
    assert frame.timestamp_source == "python_can_receive"
    assert frame.source_timestamp == FakeMessage.timestamp
    assert frame.source_timestamp_clock_domain == "unix_epoch"
    assert frame.channel == "vcan0"


def test_python_can_send_requires_explicit_per_frame_authorization(monkeypatch):
    bus = FakeBus()
    monkeypatch.setattr(adapter_module.can, "Bus", lambda **kwargs: bus)
    adapter = adapter_module.PythonCanAdapter(interface="socketcan", channel="vcan0")
    adapter.open()
    frame = CanFrame(0x7E0, bytes.fromhex("02 01 0C"))

    try:
        with pytest.raises(TypeError, match="authorization callback"):
            adapter.send_frame(frame, None)
        with pytest.raises(PermissionError, match="denied"):
            adapter.send_frame(frame, lambda candidate: False)
        assert bus.sent == []
    finally:
        adapter.close()


def test_python_can_send_transmits_only_after_authorization(monkeypatch):
    bus = FakeBus()
    sent_messages = []

    def make_message(**kwargs):
        sent_messages.append(kwargs)
        return kwargs

    monkeypatch.setattr(adapter_module.can, "Bus", lambda **kwargs: bus)
    monkeypatch.setattr(adapter_module.can, "Message", make_message)
    adapter = adapter_module.PythonCanAdapter(interface="socketcan", channel="vcan0")
    adapter.open()
    frame = CanFrame(0x18DAF110, bytes.fromhex("03 22 F1 90"), is_extended_id=True)
    approvals = []

    try:
        assert adapter.send_frame(
            frame,
            lambda candidate: approvals.append(candidate) or True,
            timeout=0.4,
        )
    finally:
        adapter.close()

    assert approvals == [frame]
    assert sent_messages == [{
        "arbitration_id": 0x18DAF110,
        "data": bytes.fromhex("03 22 F1 90"),
        "is_extended_id": True,
        "is_remote_frame": False,
        "is_error_frame": False,
        "check": True,
    }]
    assert bus.sent == [(sent_messages[0], 0.4)]


@pytest.mark.parametrize(
    "frame",
    [
        CanFrame(0x7E0, b""),
        CanFrame(0x7E0, bytes(9)),
        CanFrame(0x800, b"\\x01"),
        CanFrame(0x7E0, b"\\x01", is_remote_frame=True),
        CanFrame(0x7E0, b"\\x01", is_error_frame=True),
    ],
)
def test_python_can_send_rejects_invalid_classic_can_frames(monkeypatch, frame):
    bus = FakeBus()
    monkeypatch.setattr(adapter_module.can, "Bus", lambda **kwargs: bus)
    adapter = adapter_module.PythonCanAdapter(interface="socketcan", channel="vcan0")
    adapter.open()
    try:
        with pytest.raises(ValueError):
            adapter.send_frame(frame, lambda candidate: True)
        assert bus.sent == []
    finally:
        adapter.close()


def test_python_can_transmit_capability_is_declared_only_for_socketcan():
    socketcan = adapter_module.PythonCanAdapter(interface="socketcan")
    other = adapter_module.PythonCanAdapter(interface="virtual")

    assert socketcan.capabilities.raw_can_transmit
    assert socketcan.capabilities.raw_can_transmit_implemented
    assert not socketcan.capabilities.uds_active_requests
    assert not other.capabilities.raw_can_transmit
