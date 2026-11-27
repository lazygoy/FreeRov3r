import queue
import threading
import time

from freerov3r.hardware.device_protocol import (
    MessageStreamDecoder,
    MessageType,
    ProtocolMessage,
    decode_clock_sync_request,
    encode_clock_sync_response,
    encode_message,
)
from freerov3r.hardware.esp32_stream_adapter import Esp32FramedSerialAdapter


class SyncSerial:
    def __init__(self):
        self.timeout = 0.05
        self.is_open = True
        self.incoming = queue.Queue()
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        messages = MessageStreamDecoder().feed(data)
        assert len(messages) == 1
        request = messages[0]
        assert request.message_type == MessageType.TIME_SYNC_REQ
        decoded = decode_clock_sync_request(request.payload)
        device_receive_us = 10_000_000
        response = ProtocolMessage(
            MessageType.TIME_SYNC_RESP,
            1,
            encode_clock_sync_response(
                decoded.sync_id,
                decoded.host_send_time_ns,
                device_receive_us,
                device_receive_us + 50,
            ),
        )
        self.incoming.put(encode_message(response))
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        try:
            return self.incoming.get(timeout=max(0.001, self.timeout))
        except queue.Empty:
            return b""

    def close(self):
        self.is_open = False


def test_usb_adapter_performs_restricted_clock_sync_exchange():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    fake = SyncSerial()
    adapter._open_transport = lambda: setattr(adapter, "connection", fake)
    adapter.open()

    receiver = threading.Thread(
        target=lambda: adapter.receive(timeout=1.0),
        daemon=True,
    )
    receiver.start()
    sample = adapter.request_clock_sync(timeout=1.0)
    receiver.join(timeout=1.0)

    assert sample["sync_id"] == 1
    assert sample["device_receive_time_us"] == 10_000_000
    assert sample["device_send_time_us"] == 10_000_050
    assert len(fake.writes) == 1
    adapter.close()


def test_clock_sync_requires_connected_adapter_and_positive_timeout():
    adapter = Esp32FramedSerialAdapter(port="COM8")
    try:
        adapter.request_clock_sync()
        assert False, "disconnected adapter should reject clock sync"
    except RuntimeError:
        pass
    adapter._open_transport = lambda: setattr(adapter, "connection", SyncSerial())
    adapter.open()
    try:
        adapter.request_clock_sync(timeout=0)
        assert False, "zero timeout should be rejected"
    except ValueError:
        pass
    adapter.close()
