import pytest

from freerov3r.hardware.esp32_stream_adapter import Esp32FramedSerialAdapter


class FakeConnection:
    is_open = True

    def close(self):
        self.is_open = False


def test_reconnect_preserves_capture_counters_and_records_gap():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    opened = []

    def open_transport():
        opened.append(True)
        adapter.connection = FakeConnection()

    adapter._open_transport = open_transport
    adapter._close_transport = lambda: (
        adapter.connection.close() if adapter.connection is not None else None
    )

    adapter.open()
    adapter.frames_received = 12
    adapter.messages_received = 15
    adapter.sequence_gaps = 2
    adapter.last_sequence = 100
    adapter.device_info = {"protocol": "1"}

    adapter.connection_events.append({
        "event": "disconnected",
        "wall_time": 123.0,
        "monotonic": 45.0,
        "generation": 1,
        "reason": "USB cable removed",
    })
    adapter._opened = False

    adapter.reconnect()

    status = adapter.diagnostics
    assert adapter.connected is True
    assert adapter.frames_received == 12
    assert adapter.messages_received == 15
    assert adapter.sequence_gaps == 2
    assert adapter.last_sequence == 100
    assert status["device_info"] == {"protocol": "1"}
    assert status["reconnect_attempts"] == 1
    assert status["connection_generation"] == 2
    assert [event["event"] for event in status["connection_events"]] == [
        "connected", "disconnected", "reconnected"
    ]
    assert len(opened) == 2
    adapter.close()


def test_reconnect_resets_partial_protocol_buffer():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    adapter._open_transport = lambda: setattr(adapter, "connection", FakeConnection())
    adapter._close_transport = lambda: None
    adapter.open()
    adapter.decoder._buffer.extend(b"partial-frame")

    adapter.reconnect()

    assert adapter.diagnostics["decoder_buffered_bytes"] == 0
    adapter.close()


def test_reconnect_failure_leaves_adapter_disconnected():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    adapter._open_transport = lambda: (_ for _ in ()).throw(OSError("port busy"))
    adapter._close_transport = lambda: None
    adapter._opened = False

    with pytest.raises(OSError, match="port busy"):
        adapter.reconnect()

    assert adapter.connected is False
