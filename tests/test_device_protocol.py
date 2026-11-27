import pytest

from freerov3r.hardware.device_protocol import (
    CanFramePayload,
    MessageStreamDecoder,
    MessageType,
    ProtocolMessage,
    crc16_ccitt,
    decode_can_frame_payload,
    encode_can_frame_payload,
    encode_clock_sync_request,
    decode_clock_sync_request,
    encode_clock_sync_response,
    decode_clock_sync_response,
    encode_message,
)


def test_crc16_ccitt_false_reference_vector():
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_message_round_trip_preserves_header_and_unknown_types():
    original = ProtocolMessage(
        message_type=0xE1,
        sequence=0x12345678,
        payload=b"payload",
        version=1,
        flags=0x04,
    )
    decoder = MessageStreamDecoder()

    decoded = decoder.feed(encode_message(original))

    assert decoded == [original]
    assert decoder.frames_received == 1
    assert decoder.frames_rejected == 0


def test_stream_decoder_handles_partial_and_concatenated_messages():
    first = encode_message(ProtocolMessage(MessageType.HELLO, 1, b""))
    second = encode_message(ProtocolMessage(MessageType.DEVICE_STATUS, 2, b"status"))
    decoder = MessageStreamDecoder()

    assert decoder.feed(first[:5]) == []
    assert decoder.buffered_bytes == 5
    assert decoder.feed(first[5:] + second) == [
        ProtocolMessage(MessageType.HELLO, 1, b""),
        ProtocolMessage(MessageType.DEVICE_STATUS, 2, b"status"),
    ]
    assert decoder.buffered_bytes == 0


def test_stream_decoder_discards_noise_and_recovers_after_bad_crc():
    good = encode_message(ProtocolMessage(MessageType.ACK, 8, b"ok"))
    corrupt = bytearray(encode_message(ProtocolMessage(MessageType.HELLO, 7, b"bad")))
    corrupt[-1] ^= 0xFF
    decoder = MessageStreamDecoder()

    messages = decoder.feed(b"noise" + corrupt + good)

    assert messages == [ProtocolMessage(MessageType.ACK, 8, b"ok")]
    assert decoder.frames_rejected >= 1
    assert decoder.bytes_discarded >= len(b"noise")


def test_stream_decoder_rejects_payload_length_above_limit_and_resynchronizes():
    valid = encode_message(ProtocolMessage(MessageType.HELLO, 9, b""))
    oversized_header = b"FR" + bytes((1, int(MessageType.HELLO), 0)) + (10).to_bytes(4, "big") + (4097).to_bytes(2, "big")
    decoder = MessageStreamDecoder(max_payload_length=128)

    messages = decoder.feed(oversized_header + valid)

    assert messages == [ProtocolMessage(MessageType.HELLO, 9, b"")]
    assert decoder.frames_rejected == 1


def test_message_encoder_rejects_invalid_sequence_and_oversized_payload():
    with pytest.raises(ValueError):
        encode_message(ProtocolMessage(MessageType.HELLO, -1))
    with pytest.raises(ValueError):
        encode_message(ProtocolMessage(MessageType.HELLO, 1, b"x" * 4097))


def test_can_frame_payload_round_trip_standard_and_extended_frames():
    for extended, arbitration_id in ((False, 0x7DF), (True, 0x18DAF110)):
        payload = encode_can_frame_payload(
            channel=1,
            arbitration_id=arbitration_id,
            data=bytes.fromhex("02010C0000000000"),
            is_extended_id=extended,
            device_timestamp_us=123456789,
        )
        decoded = decode_can_frame_payload(payload)

        assert decoded == CanFramePayload(
            channel=1,
            arbitration_id=arbitration_id,
            data=bytes.fromhex("02010C0000000000"),
            is_extended_id=extended,
            is_remote_frame=False,
            device_timestamp_us=123456789,
            dlc=8,
        )


def test_can_frame_payload_supports_remote_frames_and_missing_timestamp():
    payload = encode_can_frame_payload(
        channel=0,
        arbitration_id=0x123,
        data=b"",
        is_remote_frame=True,
        dlc=8,
    )

    decoded = decode_can_frame_payload(payload)

    assert decoded.is_remote_frame
    assert decoded.dlc == 8
    assert decoded.device_timestamp_us is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channel": 256, "arbitration_id": 0x123, "data": b""},
        {"channel": 0, "arbitration_id": 0x800, "data": b""},
        {"channel": 0, "arbitration_id": 0x123, "data": b"123456789"},
        {"channel": 0, "arbitration_id": 0x123, "data": b"123", "dlc": 2},
        {"channel": 0, "arbitration_id": 0x123, "data": b"x", "is_remote_frame": True},
    ],
)
def test_can_frame_encoder_rejects_invalid_classical_can_fields(kwargs):
    with pytest.raises(ValueError):
        encode_can_frame_payload(**kwargs)


def test_can_frame_decoder_rejects_malformed_payload():
    with pytest.raises(ValueError):
        decode_can_frame_payload(b"short")
    payload = bytearray(
        encode_can_frame_payload(channel=0, arbitration_id=0x123, data=b"")
    )
    payload[1] |= 0x80
    with pytest.raises(ValueError):
        decode_can_frame_payload(payload)



def test_clock_sync_request_and_response_payload_round_trip():
    request_payload = encode_clock_sync_request(7, 1234567890123)
    assert decode_clock_sync_request(request_payload).sync_id == 7
    assert decode_clock_sync_request(request_payload).host_send_time_ns == 1234567890123

    response_payload = encode_clock_sync_response(7, 1234567890123, 456, 460)
    response = decode_clock_sync_response(response_payload)
    assert response.sync_id == 7
    assert response.host_send_time_ns == 1234567890123
    assert response.device_receive_time_us == 456
    assert response.device_send_time_us == 460


def test_clock_sync_payloads_reject_invalid_lengths_and_timestamp_order():
    with pytest.raises(ValueError, match="invalid length"):
        decode_clock_sync_request(b"short")
    with pytest.raises(ValueError, match="invalid length"):
        decode_clock_sync_response(b"short")
    with pytest.raises(ValueError, match="precedes"):
        encode_clock_sync_response(1, 2, 10, 9)


def test_clock_sync_messages_round_trip_through_framed_stream():
    payload = encode_clock_sync_request(42, 987654321)
    wire = encode_message(ProtocolMessage(MessageType.TIME_SYNC_REQ, 3, payload))
    decoded = MessageStreamDecoder().feed(wire)
    assert decoded == [ProtocolMessage(MessageType.TIME_SYNC_REQ, 3, payload)]
