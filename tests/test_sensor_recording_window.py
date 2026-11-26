import csv
import json

from freerov3r.sensors.capture import SensorCapture
from freerov3r.sensors.models import SensorSample


def make_sample(index, vin="VIN-A"):
    return SensorSample(
        timestamp=1000 + index, sensor_id="obd_0C", name="Engine speed",
        value=700 + index, unit="rpm", source="ecu",
        metadata={"vin": vin}, monotonic_timestamp=50 + index,
    )


def test_samples_since_uses_absolute_capture_sequence():
    capture = SensorCapture(max_samples=3)
    for index in range(5):
        capture.add(make_sample(index))
    assert [sample.value for sample in capture.samples_since(3)] == [703, 704]


def test_csv_export_can_limit_to_recording_window_and_vin(tmp_path):
    capture = SensorCapture(samples=[
        make_sample(0, "VIN-A"), make_sample(1, "VIN-B"), make_sample(2, "VIN-A")
    ])
    path = tmp_path / "recording.csv"
    capture.export_csv(path, vin="VIN-A", samples=capture.samples[1:])
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["value"] == "702"
    assert rows[0]["vin"] == "VIN-A"


def test_jsonl_export_can_limit_to_recording_window_and_vin(tmp_path):
    capture = SensorCapture(samples=[
        make_sample(0, "VIN-A"), make_sample(1, "VIN-B"), make_sample(2, "VIN-A")
    ])
    path = tmp_path / "recording.jsonl"
    capture.export_jsonl(path, samples=capture.samples[1:], vin="VIN-A")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["value"] == 702
    assert rows[0]["metadata"]["vin"] == "VIN-A"


def test_export_defaults_still_include_full_capture(tmp_path):
    capture = SensorCapture(samples=[make_sample(0), make_sample(1)])
    csv_path = tmp_path / "all.csv"
    jsonl_path = tmp_path / "all.jsonl"
    capture.export_csv(csv_path)
    capture.export_jsonl(jsonl_path)
    assert len(list(csv.DictReader(csv_path.open(encoding="utf-8")))) == 2
    assert len(jsonl_path.read_text(encoding="utf-8").splitlines()) == 2
