"""Crash-safe local storage helpers for CAN research captures."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class CaptureStorageError(Exception):
    """Raised when a capture archive cannot be safely written."""


def write_json_atomic(path: str | Path, payload: Any) -> Path:
    """Write JSON beside its destination, then atomically replace the destination.

    The temporary file is flushed and fsynced before replacement. A failed
    serialization or write leaves any existing destination untouched.
    """
    destination = Path(path)
    temporary_name = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            encoder = json.JSONEncoder(indent=2, ensure_ascii=False)
            for chunk in encoder.iterencode(payload):
                handle.write(chunk)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
        return destination
    except (OSError, TypeError, ValueError) as exc:
        raise CaptureStorageError(
            f"Could not safely save capture to {destination}: {exc}"
        ) from exc
    finally:
        if temporary_name and os.path.exists(temporary_name):
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
