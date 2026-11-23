import pytest

from freerov3r.isotp import reassemble_isotp


def frame(can_id, timestamp, data, *, extended=False, channel="can0"):
    return {
        "arbitration_id": can_id,
        "timestamp": timestamp,
        "data": data,
        "extended": extended,
        "channel": channel,
    }


def test_reassembles_multiframe_uds_message():
    frames = [
        frame(0x7E8, 1.0, "10 0A 62 F1 90 31 32 33"),
        frame(0x7E8, 1.01, "21 34 35 36 37 38 39 30"),
    ]
    messages = reassemble_isotp(frames)
    assert len(messages) == 1
    assert messages[0]["status"] == "complete"
    assert messages[0]["payload"] == "62f19031323334353637383930"
    assert messages[0]["frame_count"] == 2
    assert messages[0]["started_at"] == 1.0
    assert messages[0]["completed_at"] == 1.01


def test_single_frame_extracts_only_declared_payload():
    messages = reassemble_isotp([frame(0x7E8, 2.0, "03 62 F1 90 AA BB CC DD")])
    assert len(messages) == 1
    assert messages[0]["payload"] == "62f190"
    assert messages[0]["status"] == "complete"


def test_flow_control_is_not_reported_as_application_message():
    frames = [
        frame(0x7E0, 1.0, "10 0A 62 F1 90 31 32 33"),
        frame(0x7E8, 1.001, "30 00 00"),
        frame(0x7E0, 1.01, "21 34 35 36 37 38 39 30"),
    ]
    messages = reassemble_isotp(frames)
    assert len(messages) == 1
    assert messages[0]["status"] == "complete"


def test_reports_sequence_number_error():
    frames = [
        frame(0x7E8, 1.0, "10 0A 62 F1 90 31 32 33"),
        frame(0x7E8, 1.01, "22 34 35 36 37 38 39 30"),
    ]
    messages = reassemble_isotp(frames)
    assert len(messages) == 1
    assert messages[0]["status"] == "incomplete"
    assert "Sequence error" in messages[0]["detail"]


def test_reports_transfer_left_incomplete_at_end_of_capture():
    messages = reassemble_isotp([
        frame(0x7E8, 1.0, "10 14 62 F1 F0 01 02 03")
    ])
    assert len(messages) == 1
    assert messages[0]["status"] == "incomplete"
    assert "Capture ended" in messages[0]["detail"]


def test_reports_timeout_before_later_frame():
    frames = [
        frame(0x7E8, 1.0, "10 0A 62 F1 90 31 32 33"),
        frame(0x123, 3.0, "01 AA"),
    ]
    messages = reassemble_isotp(frames, timeout=0.5)
    assert len(messages) == 2
    assert messages[0]["status"] == "incomplete"
    assert "Timed out" in messages[0]["detail"]


def test_sequence_number_wraps_after_f():
    payload = bytes(range(1, 26))
    first = bytes([0x10, len(payload)]) + payload[:6]
    rest = payload[6:]
    cf_frames = []
    sequence = 1
    timestamp = 1.01
    while rest:
        chunk, rest = rest[:7], rest[7:]
        cf_frames.append(frame(
            0x7E8, timestamp,
            (bytes([0x20 | sequence]) + chunk).hex()
        ))
        sequence = (sequence + 1) & 0x0F
        timestamp += 0.01
    messages = reassemble_isotp([
        frame(0x7E8, 1.0, first.hex()), *cf_frames
    ])
    assert messages[0]["status"] == "complete"
    assert messages[0]["payload"] == payload.hex()


def test_reassembles_extended_length_first_frame():
    payload = bytes(range(1, 31))
    first = bytes.fromhex("10 00") + len(payload).to_bytes(4, "big") + payload[:2]
    rest = payload[2:]
    frames = [frame(0x7E8, 1.0, first.hex())]
    sequence = 1
    timestamp = 1.01
    while rest:
        chunk, rest = rest[:7], rest[7:]
        frames.append(frame(
            0x7E8, timestamp,
            (bytes([0x20 | sequence]) + chunk).hex()
        ))
        sequence = (sequence + 1) & 0x0F
        timestamp += 0.01
    messages = reassemble_isotp(frames, max_payload=1024)
    assert messages[0]["status"] == "complete"
    assert messages[0]["payload"] == payload.hex()


def test_separates_same_can_id_by_channel():
    frames = [
        frame(0x7E8, 1.0, "10 0A 62 F1 90 31 32 33", channel="can0"),
        frame(0x7E8, 1.01, "21 34 35 36 37 38 39 30", channel="can1"),
    ]
    messages = reassemble_isotp(frames)
    assert len(messages) == 2
    assert all(item["status"] == "incomplete" for item in messages)


def test_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        reassemble_isotp([], timeout=-1)
    with pytest.raises(ValueError):
        reassemble_isotp([], max_payload=0)
