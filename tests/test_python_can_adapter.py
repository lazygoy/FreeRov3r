import time

from freerov3r.hardware import python_can_adapter as adapter_module


class FakeMessage:
    arbitration_id = 0x123
    data = b"\\x01\\x02"
    is_extended_id = False
    is_remote_frame = False
    is_error_frame = False
    channel = "vcan0"
    timestamp = 1_700_000_000.25


class FakeBus:
    def __init__(self, message):
        self.message = message

    def recv(self, timeout):
        return self.message

    def shutdown(self):
        pass


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
