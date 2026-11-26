import json
import time

import pytest

from freerov3r.hardware.capture_replay_adapter import (
    CaptureReplayAdapter, CaptureReplayError,
)


def _write_capture(path, records):
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    return path


def test_replay_reads_frames_incrementally_and_preserves_source_time(tmp_path):
    path = _write_capture(tmp_path / "capture.jsonl", [
        {"record_type": "metadata", "metadata": {"session_name": "test"}},
        {"record_type": "frame", "arbitration_id": 0x123, "data": "0102",
         "timestamp": 12.5, "channel": "HS-CAN"},
        {"record_type": "frame", "arbitration_id": 0x456, "data": "AABB",
         "timestamp": 12.6, "channel": "MS-CAN"},
    ])
    adapter = CaptureReplayAdapter(path, speed=10000)
    adapter.open()
    try:
        first = adapter.receive(timeout=0.1)
        second = adapter.receive(timeout=0.1)
        assert (first.arbitration_id, first.data, first.channel) == (0x123, b"\x01\x02", "HS-CAN")
        assert (second.arbitration_id, second.data, second.channel) == (0x456, b"\xaa\xbb", "MS-CAN")
        assert first.timestamp_source == "capture_replay"
        assert first.timestamp_clock_domain == "host_monotonic"
        assert first.source_timestamp == 12.5
        assert first.source_timestamp_clock_domain == "capture"
        assert first.timestamp <= second.timestamp
        assert adapter.receive(timeout=0) is None
        assert adapter.frames_replayed == 2
    finally:
        adapter.close()


def test_replay_respects_recorded_timing_and_retains_pending_frame(tmp_path):
    path = _write_capture(tmp_path / "timed.jsonl", [
        {"record_type": "frame", "arbitration_id": 1, "data": "01", "timestamp": 1.0},
        {"record_type": "frame", "arbitration_id": 2, "data": "02", "timestamp": 1.15},
    ])
    adapter = CaptureReplayAdapter(path)
    adapter.open()
    try:
        assert adapter.receive(timeout=0.1).arbitration_id == 1
        assert adapter.receive(timeout=0.001) is None
        assert adapter.receive(timeout=0.3).arbitration_id == 2
    finally:
        adapter.close()


def test_replay_loop_restarts_at_eof(tmp_path):
    path = _write_capture(tmp_path / "loop.jsonl", [
        {"record_type": "frame", "arbitration_id": 0x321, "data": "AA", "timestamp": 4.0},
    ])
    adapter = CaptureReplayAdapter(path, loop=True)
    adapter.open()
    try:
        assert adapter.receive(timeout=0.1).arbitration_id == 0x321
        assert adapter.receive(timeout=0.1).arbitration_id == 0x321
        assert adapter.frames_replayed == 2
    finally:
        adapter.close()


def test_empty_loop_does_not_spin_forever(tmp_path):
    path = _write_capture(tmp_path / "empty.jsonl", [
        {"record_type": "metadata", "metadata": {}},
    ])
    adapter = CaptureReplayAdapter(path, loop=True)
    adapter.open()
    try:
        assert adapter.receive(timeout=0) is None
    finally:
        adapter.close()


def test_replay_skips_malformed_records_and_counts_them(tmp_path):
    path = tmp_path / "damaged.jsonl"
    path.write_text(
        "{broken json\n"
        + json.dumps({"record_type": "frame", "arbitration_id": 0x123, "data": "GG"})
        + "\n"
        + json.dumps({"record_type": "frame", "arbitration_id": 0x123, "data": "0102"})
        + "\n",
        encoding="utf-8",
    )
    adapter = CaptureReplayAdapter(path)
    adapter.open()
    try:
        frame = adapter.receive(timeout=0.1)
        assert frame.data == b"\x01\x02"
        assert adapter.malformed_records == 2
    finally:
        adapter.close()


@pytest.mark.parametrize("speed", [0, -1, float("inf"), float("nan"), True])
def test_replay_rejects_invalid_speed(tmp_path, speed):
    with pytest.raises(ValueError, match="Replay speed"):
        CaptureReplayAdapter(tmp_path / "unused.jsonl", speed=speed)


def test_replay_requires_existing_file(tmp_path):
    adapter = CaptureReplayAdapter(tmp_path / "missing.jsonl")
    with pytest.raises(CaptureReplayError, match="does not exist"):
        adapter.open()
