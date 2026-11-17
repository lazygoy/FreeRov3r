from freerov3r.models import CanFrame
from freerov3r.session import CaptureSession

def test_csv_export(tmp_path):
    s = CaptureSession()
    s.add(CanFrame(0x123, b"\\x01\\x02", timestamp=1.25))
    out = tmp_path / "capture.csv"
    s.export_csv(out)
    assert "123" in out.read_text()
