from freerov3r.models import CanFrame, DiagnosticEvent
from freerov3r.session import CaptureSession

def test_csv_export(tmp_path):
    s = CaptureSession()
    s.add(CanFrame(
        0x123, b"\\x01\\x02", timestamp=1.25, channel="HS-CAN",
        timestamp_clock_domain="host_monotonic",
        timestamp_source="esp32_serial_receive",
        device_timestamp_us=123456,
        device_timestamp_clock_domain="device_uptime",
    ))
    out = tmp_path / "capture.csv"
    s.export_csv(out)
    text = out.read_text()
    assert "123" in text
    assert "timestamp_clock_domain" in text
    assert "host_monotonic" in text
    assert "esp32_serial_receive" in text
    assert "device_uptime" in text
    assert "HS-CAN" in text
    assert "123456" in text



def test_diagnostic_events_remain_separate_and_export_as_jsonl(tmp_path):
    import json

    session = CaptureSession()
    event = DiagnosticEvent(
        source="D-PDU:Test_API",
        item_type=0x1300,
        timestamp_us=123456,
        timestamp_clock_domain="dpdu_api",
        module_handle=17,
        logical_link_handle=91,
        cop_handle=700,
        payload=bytes.fromhex("62 F1 90"),
        acceptance_id=9,
        unique_response_identifier=0x123,
    )
    session.add_diagnostic_event(event)

    assert session.frames == []
    assert session.diagnostic_events == [event]

    output = tmp_path / "diagnostic-events.jsonl"
    session.export_diagnostic_jsonl(output)
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert rows == [event.to_dict()]
    assert rows[0]["payload_hex"] == "62f190"
    assert rows[0]["payload_length"] == 3
    assert rows[0]["timestamp_clock_domain"] == "dpdu_api"


def test_diagnostic_event_store_rejects_non_event_objects():
    import pytest

    session = CaptureSession()
    with pytest.raises(TypeError, match="DiagnosticEvent"):
        session.add_diagnostic_event({"item_type": 0x1300})



def test_diagnostic_event_buffer_is_bounded_and_uses_absolute_indices():
    session = CaptureSession(max_diagnostic_events=3)

    def make_event(index):
        return DiagnosticEvent(
            source="D-PDU",
            item_type=0x1300,
            timestamp_us=index,
            timestamp_clock_domain="dpdu_api",
            module_handle=1,
            logical_link_handle=2,
            payload=bytes([index]),
        )

    for index in range(5):
        session.add_diagnostic_event(make_event(index))

    assert session.total_diagnostic_events_added == 5
    assert session.dropped_diagnostic_events == 2
    assert [event.timestamp_us for event in session.diagnostic_events] == [2, 3, 4]
    assert [event.timestamp_us for event in session.diagnostic_events_since(0)] == [2, 3, 4]
    assert [event.timestamp_us for event in session.diagnostic_events_since(3)] == [3, 4]
