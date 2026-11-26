import json

from freerov3r.sensors.capture import SensorCapture
from freerov3r.sensors.models import SensorSample


def sample():
    return SensorSample(
        timestamp=1234.5, sensor_id="obd_0C", name="Engine speed",
        value=812.5, unit="rpm", source="ecu", ecu="ECM",
        signal="Mode 01 PID 0C", quality="valid",
        metadata={"vin": "TESTVIN", "can_id": 2024},
        monotonic_timestamp=99.25,
    )


def test_jsonl_round_trip_preserves_sensor_provenance_and_metadata(tmp_path):
    original = SensorCapture(samples=[sample()])
    path = tmp_path / "samples.jsonl"
    original.export_jsonl(path)
    restored = SensorCapture()
    assert restored.import_jsonl(path) == 1
    imported = restored.samples[0]
    assert imported.sensor_id == "obd_0C"
    assert imported.value == 812.5
    assert imported.source == "ecu"
    assert imported.ecu == "ECM"
    assert imported.signal == "Mode 01 PID 0C"
    assert imported.metadata == {"vin": "TESTVIN", "can_id": 2024}
    assert imported.monotonic_timestamp == 99.25


def test_jsonl_import_skips_malformed_and_non_finite_rows(tmp_path):
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        json.dumps({"sensor_id": "rpm", "timestamp": 1, "value": 800}) + "\n"
        + "{broken json\n"
        + json.dumps({"sensor_id": "bad", "timestamp": 2, "value": float("nan")}) + "\n",
        encoding="utf-8",
    )
    capture = SensorCapture()
    assert capture.import_jsonl(path, default_vin="VIN-X") == 1
    assert capture.samples[0].metadata["vin"] == "VIN-X"
    assert capture.samples[0].source == "imported"


def test_csv_import_preserves_vin_and_numeric_fields(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text(
        "vin,timestamp,sensor_id,name,value,unit,source,ecu,signal,quality,monotonic_timestamp\n"
        "VIN-A,10,obd_05,Coolant,88,degC,ecu,ECM,PID05,valid,20\n",
        encoding="utf-8",
    )
    capture = SensorCapture()
    assert capture.import_csv(path) == 1
    imported = capture.samples[0]
    assert imported.metadata["vin"] == "VIN-A"
    assert imported.name == "Coolant"
    assert imported.value == 88
    assert imported.monotonic_timestamp == 20


def test_imported_csv_uses_default_vin_when_missing(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text(
        "timestamp,sensor_id,value\n"
        "10,obd_0C,700\n",
        encoding="utf-8",
    )
    capture = SensorCapture()
    assert capture.import_csv(path, default_vin="VIN-DEFAULT") == 1
    assert capture.samples[0].metadata["vin"] == "VIN-DEFAULT"
