import pytest

from freerov3r.isotp import pair_uds_transactions, reassemble_isotp


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
        frame(0x7E8, 1.0, "10 0D 62 F1 90 31 32 33"),
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
    payload = bytes(range(1, 121))
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



def test_interleaved_messages_are_returned_by_start_timestamp():
    frames = [
        frame(0x7E0, 1.0, "10 0A 62 F1 90 31 32 33"),
        frame(0x7E8, 1.005, "03 62 F1 90"),
        frame(0x7E0, 1.01, "21 34 35 36 37 38 39 30"),
    ]
    messages = reassemble_isotp(frames)
    assert [item["arbitration_id"] for item in messages] == [0x7E0, 0x7E8]
    assert [item["status"] for item in messages] == ["complete", "complete"]



def test_pairs_uds_request_and_positive_response_with_latency():
    messages = [
        {
            "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
            "started_at": 10.0, "payload": "22f190", "status": "complete",
        },
        {
            "arbitration_id": 0x7E8, "extended": False, "channel": "can0",
            "started_at": 10.025, "payload": "62f1904c5234", "status": "complete",
        },
    ]
    pairs = pair_uds_transactions(messages)
    assert len(pairs) == 1
    assert pairs[0]["confidence"] == "probable"
    assert pairs[0]["response_kind"] == "positive"
    assert pairs[0]["latency_seconds"] == pytest.approx(0.025)
    assert pairs[0]["addressing_hint"].endswith("(+0x8)")


def test_pairs_uds_negative_response_to_original_service():
    messages = [
        {
            "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
            "started_at": 2.0, "payload": "2e1234aabb", "status": "complete",
        },
        {
            "arbitration_id": 0x7E8, "extended": False, "channel": "can0",
            "started_at": 2.1, "payload": "7f2e13", "status": "complete",
        },
    ]
    pairs = pair_uds_transactions(messages)
    assert len(pairs) == 1
    assert pairs[0]["response_kind"] == "negative"
    assert pairs[0]["request_service"] == 0x2E


def test_does_not_pair_same_can_id_or_different_channels():
    messages = [
        {
            "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
            "started_at": 1.0, "payload": "22f190", "status": "complete",
        },
        {
            "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
            "started_at": 1.1, "payload": "62f190", "status": "complete",
        },
        {
            "arbitration_id": 0x7E8, "extended": False, "channel": "can1",
            "started_at": 1.2, "payload": "62f190", "status": "complete",
        },
    ]
    pairs = pair_uds_transactions(messages)
    assert all(pair["confidence"] == "unmatched" for pair in pairs)


def test_does_not_pair_response_outside_time_window():
    messages = [
        {
            "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
            "started_at": 1.0, "payload": "22f190", "status": "complete",
        },
        {
            "arbitration_id": 0x7E8, "extended": False, "channel": "can0",
            "started_at": 4.0, "payload": "62f190", "status": "complete",
        },
    ]
    pairs = pair_uds_transactions(messages, response_window=1.0)
    assert all(pair["confidence"] == "unmatched" for pair in pairs)



def test_pairs_positive_response_for_service_above_0x7e():
    messages = [
        {
            "arbitration_id": 0x700, "extended": False, "channel": "can0",
            "started_at": 1.0, "payload": "8501", "status": "complete",
        },
        {
            "arbitration_id": 0x708, "extended": False, "channel": "can0",
            "started_at": 1.1, "payload": "c501", "status": "complete",
        },
    ]
    pairs = pair_uds_transactions(messages)
    assert len(pairs) == 1
    assert pairs[0]["response_kind"] == "positive"


def test_summarizes_repeated_address_pairs_without_claiming_ecu_identity():
    from freerov3r.isotp import summarize_ecu_address_pairs

    request = {
        "arbitration_id": 0x7E0, "extended": False, "channel": "can0",
        "started_at": 1.0, "payload": "22f190", "status": "complete",
    }
    response = {
        "arbitration_id": 0x7E8, "extended": False, "channel": "can0",
        "started_at": 1.02, "payload": "62f190", "status": "complete",
    }
    transactions = [
        {"confidence": "probable", "request": request, "response": response,
         "request_service": 0x22, "response_kind": "positive", "latency_seconds": 0.02},
        {"confidence": "probable", "request": request, "response": response,
         "request_service": 0x19, "response_kind": "negative", "latency_seconds": 0.04},
        {"confidence": "unmatched", "request": None, "response": response},
    ]
    result = summarize_ecu_address_pairs(transactions)
    assert len(result) == 1
    item = result[0]
    assert item["request_id"] == 0x7E0
    assert item["response_id"] == 0x7E8
    assert item["pair_count"] == 2
    assert item["positive_count"] == 1
    assert item["negative_count"] == 1
    assert item["services"] == [0x19, 0x22]
    assert item["average_latency_seconds"] == pytest.approx(0.03)
    assert item["addressing_hint"] == "Common 11-bit +0x8 pattern"
    assert item["interpretation"].endswith("identity unknown")


def test_address_summary_keeps_channels_and_id_formats_separate():
    from freerov3r.isotp import summarize_ecu_address_pairs

    def pair(channel, extended):
        request = {"arbitration_id": 0x700, "extended": extended, "channel": channel}
        response = {"arbitration_id": 0x708, "extended": extended, "channel": channel}
        return {"confidence": "probable", "request": request, "response": response,
                "request_service": 0x22, "response_kind": "positive", "latency_seconds": 0.01}

    result = summarize_ecu_address_pairs([
        pair("can0", False), pair("can1", False), pair("can0", True)
    ])
    assert len(result) == 3
    assert {item["channel"] for item in result} == {"can0", "can1"}
    assert sum(item["extended"] for item in result) == 1


def test_address_summary_ignores_unmatched_and_invalid_pairs():
    from freerov3r.isotp import summarize_ecu_address_pairs

    assert summarize_ecu_address_pairs([
        {"confidence": "unmatched"},
        {"confidence": "probable", "request": {}, "response": {},
         "request_service": 0x22, "latency_seconds": 0.1},
    ]) == []
