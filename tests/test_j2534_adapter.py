import ctypes

import pytest

from freerov3r.hardware.j2534_adapter import (
    J2534Connection,
    J2534DeviceRegistration,
    J2534CanAdapter,
    J2534_ERR_BUFFER_EMPTY,
    J2534_PROTOCOL_CAN,
    J2534_CAN_29BIT_ID,
    PassThruError,
    PassThruMessage,
)


class FakeJ2534Library:
    def __init__(self, *, connect_status=0, read_status=0, frames=None):
        self.connect_status = connect_status
        self.read_status = read_status
        self.frames = list(frames or [])
        self.calls = []
        self.next_device = 42
        self.next_channel = 7

    def PassThruOpen(self, name, device_id):
        self.calls.append(("open", name))
        ctypes.cast(device_id, ctypes.POINTER(ctypes.c_uint32))[0] = self.next_device
        return 0

    def PassThruClose(self, device_id):
        self.calls.append(("close", device_id))
        return 0

    def PassThruConnect(self, device_id, protocol, flags, baud, channel_id):
        self.calls.append(("connect", device_id, protocol, flags, baud))
        ctypes.cast(channel_id, ctypes.POINTER(ctypes.c_uint32))[0] = self.next_channel
        return self.connect_status

    def PassThruDisconnect(self, channel_id):
        self.calls.append(("disconnect", channel_id))
        return 0

    def PassThruStartMsgFilter(self, channel_id, filter_type, mask_ptr, pattern_ptr, flow_ptr, filter_id):
        self.calls.append(("start_filter", channel_id, filter_type))
        ctypes.cast(filter_id, ctypes.POINTER(ctypes.c_uint32))[0] = 99
        return 0

    def PassThruStopMsgFilter(self, channel_id, filter_id):
        self.calls.append(("stop_filter", channel_id, filter_id))
        return 0

    def PassThruReadMsgs(self, channel_id, message_ptr, count_ptr, timeout_ms):
        self.calls.append(("read", channel_id, timeout_ms))
        count = ctypes.cast(count_ptr, ctypes.POINTER(ctypes.c_uint32))
        if self.read_status:
            count[0] = 0
            return self.read_status
        if not self.frames:
            count[0] = 0
            return J2534_ERR_BUFFER_EMPTY
        frame = self.frames.pop(0)
        message = ctypes.cast(message_ptr, ctypes.POINTER(PassThruMessage))[0]
        message.ProtocolID = J2534_PROTOCOL_CAN
        message.RxStatus = J2534_CAN_29BIT_ID if frame.get("extended") else 0
        message.Timestamp = frame.get("timestamp", 1234)
        payload = frame["can_id"].to_bytes(4, "big") + frame["data"]
        message.DataSize = len(payload)
        for index, byte in enumerate(payload):
            message.Data[index] = byte
        count[0] = 1
        return 0


@pytest.fixture
def registration():
    return J2534DeviceRegistration(
        name="Mock Pass-Thru",
        vendor="Test Vendor",
        function_library="mock-j2534.dll",
        api_version="04.04",
        registry_key="test",
    )


def test_j2534_message_abi_layout_is_stable():
    assert ctypes.sizeof(PassThruMessage) == 4 * 6 + 4128


def test_adapter_opens_and_connects_classic_can(registration):
    library = FakeJ2534Library()
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)

    adapter.open()

    assert adapter.is_open
    assert ("open", None) in library.calls
    assert ("connect", 42, J2534_PROTOCOL_CAN, 0, 500_000) in library.calls
    assert ("start_filter", 7, 0x01) in library.calls

    adapter.close()
    assert not adapter.is_open
    assert ("stop_filter", 7, 99) in library.calls
    assert ("disconnect", 7) in library.calls
    assert ("close", 42) in library.calls


def test_receive_decodes_11_bit_can_and_device_timestamp(registration):
    library = FakeJ2534Library(frames=[{
        "can_id": 0x7E8,
        "data": bytes.fromhex("03 41 0C 1A"),
        "timestamp": 2500,
    }])
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)
    adapter.open()

    frame = adapter.receive(timeout=0.125)

    assert frame.arbitration_id == 0x7E8
    assert frame.data == bytes.fromhex("03 41 0C 1A")
    assert frame.is_extended_id is False
    assert frame.channel == "J2534 CAN"
    assert frame.device_timestamp_us == 2_500_000
    assert frame.timestamp_clock_domain == "j2534_device"
    adapter.close()


def test_receive_decodes_29_bit_can(registration):
    library = FakeJ2534Library(frames=[{
        "can_id": 0x18DAF110,
        "data": bytes.fromhex("02 10 03"),
        "extended": True,
    }])
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)
    adapter.open()

    frame = adapter.receive()

    assert frame.arbitration_id == 0x18DAF110
    assert frame.is_extended_id is True
    adapter.close()


def test_empty_receive_buffer_returns_none(registration):
    library = FakeJ2534Library()
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)
    adapter.open()

    assert adapter.receive(timeout=0.01) is None
    adapter.close()


def test_receive_requires_explicit_open(registration):
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: None)

    with pytest.raises(RuntimeError, match="not open"):
        adapter.receive()


def test_failed_connect_closes_open_device(registration):
    library = FakeJ2534Library(connect_status=3)
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)

    with pytest.raises(PassThruError, match="PassThruConnect"):
        adapter.open()

    assert ("close", 42) in library.calls
    assert not adapter.is_open


def test_adapter_rejects_non_classic_can_protocol(registration):
    with pytest.raises(ValueError, match="classic CAN"):
        J2534CanAdapter(
            registration,
            J2534Connection(protocol_id=6),
            library_loader=lambda _path: None,
        )


def test_receive_rejects_malformed_can_identifier(registration):
    library = FakeJ2534Library(frames=[{
        "can_id": 0x1800,
        "data": b"\x01",
        "extended": False,
    }])
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)
    adapter.open()

    with pytest.raises(PassThruError, match="11-bit CAN identifier"):
        adapter.receive()
    adapter.close()


def test_driver_status_error_is_reported(registration):
    library = FakeJ2534Library(read_status=9)
    adapter = J2534CanAdapter(registration, library_loader=lambda _path: library)
    adapter.open()

    with pytest.raises(PassThruError, match="0x09"):
        adapter.receive()
    adapter.close()
