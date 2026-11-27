import socket

import pytest

from freerov3r.hardware.device_protocol import (
    MessageType,
    ProtocolMessage,
    encode_can_frame_payload,
    encode_message,
)
from freerov3r.hardware.esp32_stream_adapter import (
    Esp32FramedSerialAdapter,
    Esp32WifiAdapter,
)


def frame_message(sequence, *, channel=0, arbitration_id=0x123, data=b"\x01\x02"):
    payload = encode_can_frame_payload(
        channel=channel,
        arbitration_id=arbitration_id,
        data=data,
        device_timestamp_us=987654,
    )
    return encode_message(ProtocolMessage(MessageType.FRAME_RX, sequence, payload))


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.timeout = 0.1
        self.is_open = True
        self.read_calls = 0

    def read(self, size):
        self.read_calls += 1
        return next(self.chunks, b"")

    def close(self):
        self.is_open = False


def test_usb_adapter_decodes_frame_and_preserves_timestamps():
    adapter = Esp32FramedSerialAdapter(port="COM8", channel_names={0: "HS-CAN"})
    adapter.connection = FakeSerial([frame_message(1)])
    adapter._opened = True

    frame = adapter.receive(timeout=0.1)

    assert frame.arbitration_id == 0x123
    assert frame.data == b"\x01\x02"
    assert frame.channel == "HS-CAN"
    assert frame.device_timestamp_us == 987654
    assert frame.timestamp_clock_domain == "host_monotonic"
    assert frame.timestamp_source == "esp32_USB serial COM8"
    assert adapter.diagnostics["frames_received"] == 1
    adapter.close()
    assert adapter.connection is None


def test_usb_adapter_handles_fragmented_stream_and_multiple_frames():
    first = frame_message(10, arbitration_id=0x100)
    second = frame_message(11, arbitration_id=0x101)
    adapter = Esp32FramedSerialAdapter()
    fake = FakeSerial([first[:7], first[7:] + second])
    adapter.connection = fake
    adapter._opened = True

    a = adapter.receive(timeout=0.1)
    reads_after_decode = fake.read_calls
    b = adapter.receive(timeout=0.1)

    assert (a.arbitration_id, b.arbitration_id) == (0x100, 0x101)
    assert fake.read_calls == reads_after_decode
    assert adapter.diagnostics["decoder_buffered_bytes"] == 0


def test_adapter_ignores_control_messages_and_counts_sequence_gaps():
    control = encode_message(ProtocolMessage(MessageType.DEVICE_STATUS, 1, b"ok"))
    adapter = Esp32FramedSerialAdapter()
    adapter.connection = FakeSerial([control + frame_message(3)])
    adapter._opened = True

    frame = adapter.receive(timeout=0.1)

    assert frame is not None
    assert adapter.diagnostics["ignored_messages"] == 1
    assert adapter.diagnostics["sequence_gaps"] == 1


def test_adapter_rejects_invalid_can_payload_without_crashing():
    bad = encode_message(ProtocolMessage(MessageType.FRAME_RX, 1, b"bad"))
    adapter = Esp32FramedSerialAdapter()
    adapter.connection = FakeSerial([bad])
    adapter._opened = True

    assert adapter.receive(timeout=0.01) is None
    assert adapter.diagnostics["invalid_can_payloads"] == 1


def test_adapter_requires_open_before_receive():
    with pytest.raises(RuntimeError):
        Esp32FramedSerialAdapter().receive()


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        item = next(self.chunks, b"")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_wifi_adapter_uses_same_protocol_and_closes_socket(monkeypatch):
    fake = FakeSocket([frame_message(22, channel=1, arbitration_id=0x456)])
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout: fake)
    adapter = Esp32WifiAdapter(
        "192.168.4.1",
        channel_names={1: "MS-CAN"},
    )

    adapter.open()
    frame = adapter.receive(timeout=0.1)

    assert frame.arbitration_id == 0x456
    assert frame.channel == "MS-CAN"
    assert frame.timestamp_source == "esp32_Wi-Fi TCP 192.168.4.1:3333"
    adapter.close()
    assert fake.closed


def test_wifi_adapter_reports_remote_disconnect(monkeypatch):
    fake = FakeSocket([b""])
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout: fake)
    adapter = Esp32WifiAdapter("192.168.4.1")
    adapter.open()

    with pytest.raises(ConnectionError, match="closed the connection"):
        adapter.receive(timeout=0.1)

    assert adapter.diagnostics["connected"] is False
    assert "closed the connection" in adapter.diagnostics["last_error"]


def test_wifi_adapter_validates_tcp_port():
    adapter = Esp32WifiAdapter("192.168.4.1", port=70000)
    with pytest.raises(ValueError, match="valid ESP32 Wi-Fi"):
        adapter.open()
