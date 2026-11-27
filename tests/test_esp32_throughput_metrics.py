import time

from freerov3r.hardware.device_protocol import (
    MessageType,
    ProtocolMessage,
    encode_can_frame_payload,
    encode_message,
)
from freerov3r.hardware.esp32_stream_adapter import Esp32FramedSerialAdapter


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.timeout = 0.1
        self.is_open = True

    def read(self, size):
        return next(self.chunks, b"")

    def close(self):
        self.is_open = False


def encoded_frame(sequence=1):
    payload = encode_can_frame_payload(
        channel=0,
        arbitration_id=0x123,
        data=b"\x01\x02\x03",
        device_timestamp_us=1000000,
    )
    return encode_message(ProtocolMessage(MessageType.FRAME_RX, sequence, payload))


def test_stream_adapter_reports_byte_and_frame_throughput():
    payload = encoded_frame()
    adapter = Esp32FramedSerialAdapter(port="COM8")
    adapter._open_transport = lambda: setattr(
        adapter, "connection", FakeSerial([payload])
    )

    adapter.open()
    time.sleep(0.01)
    frame = adapter.receive(timeout=0.1)
    metrics = adapter.diagnostics

    assert frame is not None
    assert metrics["bytes_received"] == len(payload)
    assert metrics["frames_received"] == 1
    assert metrics["capture_elapsed_seconds"] > 0
    assert metrics["average_frames_per_second"] > 0
    assert metrics["average_bytes_per_second"] > 0
    assert metrics["last_byte_age_seconds"] is not None
    adapter.close()


def test_stream_metrics_reset_for_new_capture_session():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    adapter._open_transport = lambda: setattr(
        adapter, "connection", FakeSerial([])
    )

    adapter.open()
    adapter.bytes_received = 100
    adapter.frames_received = 5
    adapter.close()
    adapter.open()

    metrics = adapter.diagnostics
    assert metrics["bytes_received"] == 0
    assert metrics["frames_received"] == 0
    assert metrics["average_bytes_per_second"] == 0
    adapter.close()
