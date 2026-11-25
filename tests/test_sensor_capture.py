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


def test_jsonl_and_markdown_exports_use_real_line_breaks(tmp_path):
    capture = SensorCapture()
    capture.add(SensorSample(1.0, "rpm", "Engine speed", 800,
                             "rpm", "ecu"))
    capture.add(SensorSample(2.0, "rpm", "Engine speed", 900,
                             "rpm", "ecu"))

    jsonl_path = tmp_path / "multiple.jsonl"
    report_path = tmp_path / "report.md"
    capture.export_jsonl(jsonl_path)
    capture.export_llm_report(report_path)

    jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 2
    assert all('"sensor_id": "rpm"' in line for line in jsonl_lines)
    report = report_path.read_text(encoding="utf-8")
    assert "\\n" not in report
    assert "# FreeRov3r sensor capture analysis\n\n" in report



def test_sensor_capture_bounds_memory_and_tracks_absolute_sample_indexes():
    capture = SensorCapture(max_samples=3)
    for index in range(5):
        capture.add(SensorSample(
            float(index), "rpm", "Engine speed", 800 + index,
            "rpm", "ecu",
        ))

    assert len(capture.samples) == 3
    assert capture.total_samples_added == 5
    assert capture.dropped_samples == 2
    assert [sample.value for sample in capture.samples_since(3)] == [803, 804]
    assert [sample.value for sample in capture.samples_since(0)] == [802, 803, 804]


def test_sensor_capture_rejects_zero_capacity():
    import pytest

    with pytest.raises(ValueError, match="max_samples"):
        SensorCapture(max_samples=0)
