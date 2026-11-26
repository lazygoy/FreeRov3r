import json

import pytest

from freerov3r.capture_storage import (
    CaptureStorageError,
    write_json_atomic,
)


def test_write_json_atomic_creates_parent_and_valid_archive(tmp_path):
    destination = tmp_path / "captures" / "session.json"
    payload = {
        "format": "freerov3r-research-v1",
        "frames": [{"arbitration_id": 0x123, "data": "0102"}],
    }

    result = write_json_atomic(destination, payload)

    assert result == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert list(destination.parent.iterdir()) == [destination]


def test_write_json_atomic_preserves_existing_file_on_replace_failure(
    tmp_path, monkeypatch
):
    import freerov3r.capture_storage as storage

    destination = tmp_path / "session.json"
    destination.write_text('{"previous": true}', encoding="utf-8")

    def fail_replace(source, target):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)

    with pytest.raises(CaptureStorageError, match="simulated replacement failure"):
        write_json_atomic(destination, {"new": True})

    assert destination.read_text(encoding="utf-8") == '{"previous": true}'
    assert list(tmp_path.iterdir()) == [destination]


def test_write_json_atomic_preserves_existing_file_on_serialization_failure(tmp_path):
    destination = tmp_path / "session.json"
    destination.write_text('{"previous": true}', encoding="utf-8")

    with pytest.raises(CaptureStorageError):
        write_json_atomic(destination, {"not_json": object()})

    assert destination.read_text(encoding="utf-8") == '{"previous": true}'
    assert list(tmp_path.iterdir()) == [destination]


def test_streaming_writer_writes_recoverable_jsonl_with_integrity(tmp_path):
    import hashlib

    from freerov3r.capture_storage import StreamingCaptureWriter

    destination = tmp_path / "captures" / "session.jsonl"
    writer = StreamingCaptureWriter(destination, flush_interval_seconds=60)
    writer.start({"session_name": "test"})
    frames = [
        {"arbitration_id": 0x123, "data": "0102", "timestamp": 1.0},
        {"arbitration_id": 0x456, "data": "AABB", "timestamp": 2.0},
    ]
    for frame in frames:
        writer.append_frame(frame)
    writer.finish({"notes": "complete"})

    lines = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["metadata"]["streaming_capture"]["status"] == "recording"
    assert [item["record_type"] for item in lines] == ["metadata", "frame", "frame", "metadata"]
    footer = lines[-1]["metadata"]["streaming_capture"]
    assert footer["status"] == "complete"
    assert footer["frame_count"] == 2
    expected = b"".join(
        json.dumps({"record_type": "frame", **frame}, ensure_ascii=False,
                   separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\\n"
        for frame in frames
    )
    assert footer["frames_sha256"] == hashlib.sha256(expected).hexdigest()
    assert writer.is_open is False


def test_streaming_writer_leaves_incomplete_archive_recoverable(tmp_path):
    from freerov3r.capture_storage import StreamingCaptureWriter

    destination = tmp_path / "interrupted.jsonl"
    writer = StreamingCaptureWriter(destination)
    writer.start({"session_name": "interrupted"})
    writer.append_frame({"arbitration_id": 0x123, "data": "0102"})
    writer.close_incomplete()

    lines = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["metadata"]["streaming_capture"]["status"] == "recording"
    assert lines[1]["record_type"] == "frame"
    assert writer.is_open is False


def test_streaming_writer_refuses_to_overwrite_existing_file(tmp_path):
    from freerov3r.capture_storage import StreamingCaptureWriter

    destination = tmp_path / "existing.jsonl"
    destination.write_text("preserve me", encoding="utf-8")
    writer = StreamingCaptureWriter(destination)

    with pytest.raises(CaptureStorageError, match="Could not start streaming capture"):
        writer.start()

    assert destination.read_text(encoding="utf-8") == "preserve me"
