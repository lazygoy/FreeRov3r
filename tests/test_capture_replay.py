import json

import pytest

from freerov3r.capture_replay import (
    compare_captures,
    list_capture_archives,
    load_capture,
)


def _capture(path, frames, samples=None, duration=1.0):
    path.write_text(json.dumps({
        "interface": "test",
        "duration_seconds": duration,
        "frames": frames,
        "sensor_samples": samples or [],
    }), encoding="utf-8")
    return path


def test_list_archives_is_vin_scoped_and_newest_first(tmp_path):
    root = tmp_path / "vehicles"
    a = root / "SALXXXXXXXXXXXX1" / "captures"
    b = root / "SALYYYYYYYYYYYY2" / "captures"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    older = a / "capture_20260101T000000Z.json"
    newer = a / "capture_20260102T000000Z.json"
    other = b / "capture_20260103T000000Z.json"
    for item in (older, newer, other):
        item.write_text("{}", encoding="utf-8")
    paths = list_capture_archives(tmp_path / "vehicle_history.json", "SALXXXXXXXXXXXX1")
    assert paths == [newer, older]
    assert list_capture_archives(tmp_path / "vehicle_history.json", "UNASSIGNED") == []


def test_load_capture_normalizes_and_validates_frames(tmp_path):
    path = _capture(tmp_path / "capture.json", [
        {"timestamp": 1.25, "arbitration_id": 2024, "extended": False, "data": "010203"}
    ])
    capture = load_capture(path)
    assert capture["frames"][0]["data"] == "010203"
    assert capture["frames"][0]["timestamp"] == 1.25


@pytest.mark.parametrize("frame", [
    {"arbitration_id": -1, "data": "00"},
    {"arbitration_id": 0x20000000, "data": "00"},
    {"arbitration_id": 100, "data": "xyz"},
    {"arbitration_id": 100, "data": "00" * 65},
])
def test_load_capture_rejects_invalid_frames(tmp_path, frame):
    path = _capture(tmp_path / "bad.json", [frame])
    with pytest.raises(ValueError):
        load_capture(path)


def test_compare_captures_reports_id_and_sensor_deltas(tmp_path):
    left = load_capture(_capture(tmp_path / "left.json", [
        {"arbitration_id": 100, "data": "01"},
        {"arbitration_id": 100, "data": "02"},
        {"arbitration_id": 200, "data": "03"},
    ], [{"sensor_id": "rpm", "value": 1000, "unit": "rpm"},
        {"sensor_id": "rpm", "value": 1200, "unit": "rpm"}]))
    right = load_capture(_capture(tmp_path / "right.json", [
        {"arbitration_id": 100, "data": "01"},
        {"arbitration_id": 300, "data": "04"},
    ], [{"sensor_id": "rpm", "value": 1500, "unit": "rpm"}]))
    result = compare_captures(left, right)
    by_id = {row["arbitration_id"]: row for row in result["frame_ids"]}
    assert by_id[100]["delta"] == -1
    assert by_id[200]["right_count"] == 0
    assert by_id[300]["left_count"] == 0
    assert result["sensors"][0]["mean_delta"] == 400
    payloads = [row for row in result["payloads"] if row["arbitration_id"] == 100]
    assert len(payloads) == 2
    assert sum(row["left_count"] for row in payloads) == 2
    assert sum(row["right_count"] for row in payloads) == 1
