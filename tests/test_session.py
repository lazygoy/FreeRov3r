from freerov3r.models import CanFrame
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
