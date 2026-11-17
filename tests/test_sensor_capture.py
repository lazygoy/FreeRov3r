from freerov3r.sensors.models import SensorSample
from freerov3r.sensors.capture import SensorCapture

def test_capture_exports_and_llm_report(tmp_path):
    capture = SensorCapture(vehicle_context={"platform": "L319"})
    capture.add(SensorSample(1.0, "coolant", "Coolant temperature", 88.5,
                             "degC", "ecu", ecu="PCM"))
    csv_path = tmp_path / "sensors.csv"
    jsonl_path = tmp_path / "sensors.jsonl"
    md_path = tmp_path / "analysis.md"
    capture.export_csv(csv_path)
    capture.export_jsonl(jsonl_path)
    capture.export_llm_report(md_path)
    assert "88.5" in csv_path.read_text()
    assert '"value": 88.5' in jsonl_path.read_text()
    assert "L319" in md_path.read_text()
