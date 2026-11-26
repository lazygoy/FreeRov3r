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
