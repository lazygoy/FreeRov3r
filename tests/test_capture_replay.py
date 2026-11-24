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


def test_load_capture_rejects_extended_id_marked_as_standard(tmp_path):
    path = _capture(tmp_path / "bad_standard.json", [
        {"arbitration_id": 0x1234, "extended": False, "data": "00"}
    ])
    with pytest.raises(ValueError, match="marked standard"):
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


from freerov3r.capture_replay import build_replay_timeline, filter_capture_frames


def test_filter_capture_frames_keeps_original_indices_and_supports_hex_id():
    frames = [
        {"timestamp": 1, "arbitration_id": 0x123, "extended": False, "data": "AABB"},
        {"timestamp": 2, "arbitration_id": 0x123, "extended": True, "data": "CCDD"},
        {"timestamp": 3, "arbitration_id": 0x456, "extended": False, "data": "AACC"},
    ]
    matches = filter_capture_frames(frames, "0x123", "Standard", "aa")
    assert matches == [(0, frames[0])]


@pytest.mark.parametrize("filters", [
    {"can_id": "not-an-id"},
    {"can_id": "0x20000000"},
    {"frame_format": "CAN-FD"},
    {"payload_contains": "GG"},
])
def test_filter_capture_frames_rejects_invalid_filters(filters):
    with pytest.raises(ValueError):
        filter_capture_frames([], **filters)


def test_build_replay_timeline_merges_frames_and_sensor_samples_by_timestamp():
    capture = {
        "frames": [
            {"timestamp": 2.0, "arbitration_id": 100, "extended": False, "data": "01"},
            {"timestamp": 1.0, "arbitration_id": 200, "extended": False, "data": "02"},
        ],
        "sensor_samples": [
            {"timestamp": 1.0, "sensor_id": "rpm", "value": 900, "unit": "rpm"},
            {"timestamp": 1.5, "sensor_id": "coolant", "value": 88, "unit": "C"},
            {"timestamp": -1, "sensor_id": "bad", "value": 1},
            {"timestamp": 1.2, "sensor_id": "invalid", "value": "not numeric"},
        ],
    }
    timeline = build_replay_timeline(capture)
    assert [(event["kind"], event["timestamp"]) for event in timeline] == [
        ("frame", 1.0), ("sensor", 1.0), ("sensor", 1.5), ("frame", 2.0)
    ]
    assert timeline[0]["source_index"] == 1
    assert timeline[1]["sample"]["sensor_id"] == "rpm"


def test_replay_timeline_filters_frames_without_dropping_sensor_samples():
    capture = {
        "frames": [
            {"timestamp": 1.0, "arbitration_id": 100, "extended": False, "data": "0102"},
            {"timestamp": 2.0, "arbitration_id": 200, "extended": False, "data": "0304"},
        ],
        "sensor_samples": [
            {"timestamp": 1.5, "sensor_id": "rpm", "value": 1000, "unit": "rpm"}
        ],
    }
    timeline = build_replay_timeline(capture, can_id="100")
    assert [event["kind"] for event in timeline] == ["frame", "sensor"]
    assert timeline[0]["frame"]["arbitration_id"] == 100


def test_loaded_capture_and_timeline_preserve_archive_vin(tmp_path):
    vin = "SALXXXXXXXXXXXX1"
    folder = tmp_path / "vehicles" / vin / "captures"
    folder.mkdir(parents=True)
    path = _capture(folder / "capture_test.json", [
        {"timestamp": 1.0, "arbitration_id": 100, "extended": False, "data": "01"}
    ], [{"timestamp": 1.1, "sensor_id": "rpm", "value": 900, "unit": "rpm"}])
    capture = load_capture(path)
    timeline = build_replay_timeline(capture)
    assert capture["vin"] == vin
    assert {event["vin"] for event in timeline} == {vin}
