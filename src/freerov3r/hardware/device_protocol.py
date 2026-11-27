"""Versioned, transport-independent FreeRov3r device message framing.

USB serial and Wi-Fi TCP carry this byte stream directly. A BLE transport may
fragment/reassemble the same complete messages at the GATT layer. This module
does not open transports or enable CAN transmission.

Wire frame (network byte order):
    magic[2] | version:u8 | type:u8 | flags:u8 | sequence:u32 |
    payload_length:u16 | payload | crc16:u16

CRC is CRC-16/CCITT-FALSE over the header and payload. Unknown message types
are preserved as integers so newer firmware can interoperate with older hosts.
"""
from dataclasses import dataclass
from enum import IntEnum
import struct


MAGIC = b"FR"
PROTOCOL_VERSION = 1
MAX_PAYLOAD_LENGTH = 4096
_HEADER = struct.Struct(">2sBBBIH")
_CRC = struct.Struct(">H")
_CAN_FRAME_HEADER = struct.Struct(">BBBIQ")
_NO_DEVICE_TIMESTAMP = 0xFFFFFFFFFFFFFFFF


class MessageType(IntEnum):
    HELLO = 0x01
    GET_CAPABILITIES = 0x02
    CONFIG = 0x03
    START_RX = 0x04
    STOP_RX = 0x05
    SEND_FRAME = 0x06
    ACK = 0x10
    NACK = 0x11
    DEVICE_STATUS = 0x12
    FRAME_RX = 0x20
    TX_RESULT = 0x21
    TIME_SYNC_REQ = 0x30
    TIME_SYNC_RESP = 0x31


@dataclass(frozen=True)
class ProtocolMessage:
    message_type: int
    sequence: int
    payload: bytes = b""
    version: int = PROTOCOL_VERSION
    flags: int = 0


@dataclass(frozen=True)
class CanFramePayload:
    channel: int
    arbitration_id: int
    data: bytes
    is_extended_id: bool
    is_remote_frame: bool
    device_timestamp_us: int | None = None
    dlc: int | None = None


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """Return CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection)."""
    crc = initial & 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_message(message: ProtocolMessage) -> bytes:
    """Encode one complete message, rejecting invalid or oversized fields."""
    if not 0 <= int(message.version) <= 0xFF:
        raise ValueError("Protocol version must fit in one byte")
    if not 0 <= int(message.message_type) <= 0xFF:
        raise ValueError("Message type must fit in one byte")
    if not 0 <= int(message.flags) <= 0xFF:
        raise ValueError("Message flags must fit in one byte")
    if not 0 <= int(message.sequence) <= 0xFFFFFFFF:
        raise ValueError("Sequence number must fit in four bytes")
    payload = bytes(message.payload)
    if len(payload) > MAX_PAYLOAD_LENGTH:
        raise ValueError(f"Payload exceeds {MAX_PAYLOAD_LENGTH} bytes")

    header = _HEADER.pack(
        MAGIC,
        int(message.version),
        int(message.message_type),
        int(message.flags),
        int(message.sequence),
        len(payload),
    )
    body = header + payload
    return body + _CRC.pack(crc16_ccitt(body))


class MessageStreamDecoder:
    """Incremental decoder for arbitrary stream chunks, with resynchronization."""

    def __init__(self, max_payload_length: int = MAX_PAYLOAD_LENGTH):
        if not 0 <= max_payload_length <= MAX_PAYLOAD_LENGTH:
            raise ValueError("max_payload_length is outside the supported range")
        self.max_payload_length = max_payload_length
        self._buffer = bytearray()
        self.frames_received = 0
        self.frames_rejected = 0
        self.bytes_discarded = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[ProtocolMessage]:
        if data:
            self._buffer.extend(data)
        messages = []

        while True:
            start = self._buffer.find(MAGIC)
            if start < 0:
                # Retain a possible first byte of a split magic marker.
                keep = 1 if self._buffer.endswith(MAGIC[:1]) else 0
                discard = len(self._buffer) - keep
                if discard:
                    del self._buffer[:discard]
                    self.bytes_discarded += discard
                break

            if start:
                del self._buffer[:start]
                self.bytes_discarded += start

            if len(self._buffer) < _HEADER.size:
                break

            _, version, message_type, flags, sequence, payload_length = _HEADER.unpack_from(self._buffer)
            if payload_length > self.max_payload_length:
                self.frames_rejected += 1
                del self._buffer[0]
                self.bytes_discarded += 1
                continue

            frame_length = _HEADER.size + payload_length + _CRC.size
            if len(self._buffer) < frame_length:
                break

            frame = self._buffer[:frame_length]
            expected_crc = _CRC.unpack_from(frame, frame_length - _CRC.size)[0]
            actual_crc = crc16_ccitt(frame[:-_CRC.size])
            if actual_crc != expected_crc:
                self.frames_rejected += 1
                del self._buffer[0]
                self.bytes_discarded += 1
                continue

            payload = bytes(frame[_HEADER.size:-_CRC.size])
            messages.append(
                ProtocolMessage(
                    message_type=message_type,
                    sequence=sequence,
                    payload=payload,
                    version=version,
                    flags=flags,
                )
            )
            del self._buffer[:frame_length]
            self.frames_received += 1

        return messages

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)


def encode_can_frame_payload(
    *,
    channel: int,
    arbitration_id: int,
    data: bytes,
    is_extended_id: bool = False,
    is_remote_frame: bool = False,
    device_timestamp_us: int | None = None,
    dlc: int | None = None,
) -> bytes:
    """Encode a Classical-CAN frame payload for a FRAME_RX message."""
    payload_data = bytes(data)
    if not 0 <= channel <= 0xFF:
        raise ValueError("CAN channel must fit in one byte")
    maximum_id = 0x1FFFFFFF if is_extended_id else 0x7FF
    if not 0 <= arbitration_id <= maximum_id:
        raise ValueError("CAN arbitration ID is invalid for the selected frame format")
    if len(payload_data) > 8:
        raise ValueError("Classical CAN payload cannot exceed 8 bytes")
    frame_dlc = len(payload_data) if dlc is None else dlc
    if not 0 <= frame_dlc <= 8:
        raise ValueError("CAN DLC must be between 0 and 8")
    if is_remote_frame:
        if payload_data:
            raise ValueError("Remote CAN frames cannot contain data bytes")
    elif frame_dlc != len(payload_data):
        raise ValueError("CAN DLC must match the data length")
    timestamp = _NO_DEVICE_TIMESTAMP if device_timestamp_us is None else device_timestamp_us
    if not 0 <= timestamp <= _NO_DEVICE_TIMESTAMP:
        raise ValueError("Device timestamp must be a non-negative 64-bit value")
    flags = (0x01 if is_extended_id else 0) | (0x02 if is_remote_frame else 0)
    return _CAN_FRAME_HEADER.pack(
        channel, flags, frame_dlc, arbitration_id, timestamp
    ) + payload_data


def decode_can_frame_payload(payload: bytes) -> CanFramePayload:
    """Decode and validate a FRAME_RX payload."""
    raw = bytes(payload)
    if len(raw) < _CAN_FRAME_HEADER.size:
        raise ValueError("CAN frame payload is shorter than its header")
    channel, flags, dlc, arbitration_id, timestamp = _CAN_FRAME_HEADER.unpack_from(raw)
    if flags & ~0x03:
        raise ValueError("CAN frame payload contains unsupported flag bits")
    is_extended = bool(flags & 0x01)
    is_remote = bool(flags & 0x02)
    maximum_id = 0x1FFFFFFF if is_extended else 0x7FF
    if arbitration_id > maximum_id:
        raise ValueError("CAN arbitration ID is invalid for the selected frame format")
    if dlc > 8:
        raise ValueError("Classical CAN DLC must be between 0 and 8")
    data = raw[_CAN_FRAME_HEADER.size:]
    if is_remote:
        if data:
            raise ValueError("Remote CAN frame unexpectedly contains data bytes")
    elif len(data) != dlc:
        raise ValueError("CAN data length does not match DLC")

    return CanFramePayload(
        channel=channel,
        arbitration_id=arbitration_id,
        data=data,
        is_extended_id=is_extended,
        is_remote_frame=is_remote,
        device_timestamp_us=None if timestamp == _NO_DEVICE_TIMESTAMP else timestamp,
        dlc=dlc,
    )



_CLOCK_SYNC_REQUEST = struct.Struct(">IQ")
_CLOCK_SYNC_RESPONSE = struct.Struct(">IQQQ")


@dataclass(frozen=True)
class ClockSyncRequest:
    sync_id: int
    host_send_time_ns: int


@dataclass(frozen=True)
class ClockSyncResponse:
    sync_id: int
    host_send_time_ns: int
    device_receive_time_us: int
    device_send_time_us: int


def encode_clock_sync_request(sync_id: int, host_send_time_ns: int) -> bytes:
    """Encode the only currently supported host-to-device control request."""
    if not 0 <= sync_id <= 0xFFFFFFFF:
        raise ValueError("Clock sync ID must fit in four bytes")
    if not 0 <= host_send_time_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("Host monotonic timestamp must fit in eight bytes")
    return _CLOCK_SYNC_REQUEST.pack(sync_id, host_send_time_ns)


def decode_clock_sync_request(payload: bytes) -> ClockSyncRequest:
    raw = bytes(payload)
    if len(raw) != _CLOCK_SYNC_REQUEST.size:
        raise ValueError("Clock sync request payload has an invalid length")
    return ClockSyncRequest(*_CLOCK_SYNC_REQUEST.unpack(raw))


def encode_clock_sync_response(
    sync_id: int,
    host_send_time_ns: int,
    device_receive_time_us: int,
    device_send_time_us: int,
) -> bytes:
    values = (sync_id, host_send_time_ns, device_receive_time_us, device_send_time_us)
    limits = (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
    if any(value < 0 or value > limit for value, limit in zip(values, limits)):
        raise ValueError("Clock sync response field is outside its wire range")
    if device_send_time_us < device_receive_time_us:
        raise ValueError("Device send timestamp precedes receive timestamp")
    return _CLOCK_SYNC_RESPONSE.pack(*values)


def decode_clock_sync_response(payload: bytes) -> ClockSyncResponse:
    raw = bytes(payload)
    if len(raw) != _CLOCK_SYNC_RESPONSE.size:
        raise ValueError("Clock sync response payload has an invalid length")
    response = ClockSyncResponse(*_CLOCK_SYNC_RESPONSE.unpack(raw))
    if response.device_send_time_us < response.device_receive_time_us:
        raise ValueError("Device send timestamp precedes receive timestamp")
    return response
