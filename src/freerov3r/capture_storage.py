"""Crash-safe local storage helpers for CAN research captures."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CaptureStorageError(Exception):
    """Raised when a capture archive cannot be safely written."""


class StreamingCaptureWriter:
    """Append-only JSONL writer for long-running CAN research captures.

    Each frame is written as it arrives. Data is flushed and fsynced at a
    bounded interval. A final metadata record contains the frame count and
    SHA-256 digest, allowing imports to distinguish complete archives from
    recordings interrupted by a crash or power loss.
    """

    FORMAT = "freerov3r-research-jsonl-v1"

    def __init__(self, path: str | Path, *, flush_interval_seconds: float = 1.0):
        if flush_interval_seconds <= 0:
            raise ValueError("Flush interval must be greater than zero.")
        self.path = Path(path)
        self.flush_interval_seconds = float(flush_interval_seconds)
        self._handle = None
        self._last_flush = 0.0
        self._frame_count = 0
        self._digest = hashlib.sha256()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def is_open(self) -> bool:
        return self._handle is not None and not self._handle.closed

    def _write_record(self, record: dict[str, Any]) -> bytes:
        encoded = json.dumps(
            record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        self._handle.write(encoded.decode("utf-8") + "\n")
        return encoded

    def _flush(self, *, force: bool = False) -> None:
        if not self.is_open:
            return
        now = time.monotonic()
        if force or now - self._last_flush >= self.flush_interval_seconds:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._last_flush = now

    def start(self, metadata: dict[str, Any] | None = None) -> Path:
        if self.is_open:
            raise CaptureStorageError("Streaming capture is already open.")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("x", encoding="utf-8", newline="\n")
            self._write_record({
                "record_type": "metadata",
                "metadata": {
                    **(metadata or {}),
                    "streaming_capture": {
                        "format": self.FORMAT,
                        "status": "recording",
                    },
                },
            })
            self._flush(force=True)
            return self.path
        except (OSError, TypeError, ValueError) as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise CaptureStorageError(
                f"Could not start streaming capture at {self.path}: {exc}"
            ) from exc

    def append_frame(self, frame: dict[str, Any]) -> None:
        if not self.is_open:
            raise CaptureStorageError("Streaming capture is not open.")
        if not isinstance(frame, dict):
            raise CaptureStorageError("A captured frame must be a dictionary.")
        try:
            record = {"record_type": "frame", **frame}
            encoded = self._write_record(record)
            self._digest.update(encoded + b"\n")
            self._frame_count += 1
            self._flush()
        except (OSError, TypeError, ValueError) as exc:
            raise CaptureStorageError(
                f"Could not append frame to streaming capture {self.path}: {exc}"
            ) from exc

    def finish(self, metadata: dict[str, Any] | None = None) -> Path:
        if not self.is_open:
            raise CaptureStorageError("Streaming capture is not open.")
        try:
            details = {
                **(metadata or {}),
                "streaming_capture": {
                    "format": self.FORMAT,
                    "status": "complete",
                    "frame_count": self._frame_count,
                    "frames_sha256": self._digest.hexdigest(),
                    "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            }
            self._write_record({"record_type": "metadata", "metadata": details})
            self._flush(force=True)
            self._handle.close()
            self._handle = None
            return self.path
        except (OSError, TypeError, ValueError) as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise CaptureStorageError(
                f"Could not finalize streaming capture {self.path}: {exc}"
            ) from exc

    def close_incomplete(self) -> None:
        """Close the file without a completion marker, preserving recovery evidence."""
        if not self.is_open:
            return
        error = None
        try:
            self._flush(force=True)
        except OSError as exc:
            error = exc
        try:
            self._handle.close()
        except OSError as exc:
            error = error or exc
        finally:
            self._handle = None
        if error is not None:
            raise CaptureStorageError(
                f"Could not cleanly close incomplete capture {self.path}: {error}"
            ) from error


class AsyncStreamingCaptureWriter:
    """Bounded background-thread wrapper around StreamingCaptureWriter.

    Frame ordering and archive integrity are preserved. Producers apply
    backpressure only if the bounded queue fills; disk I/O and JSON encoding
    normally happen entirely on the writer thread.
    """

    QUEUE_CAPACITY = 8192
    _STOP = object()

    def __init__(self, path: str | Path, *, flush_interval_seconds: float = 1.0):
        import queue
        import threading

        self.path = Path(path)
        self._writer = StreamingCaptureWriter(
            path, flush_interval_seconds=flush_interval_seconds
        )
        self._queue = queue.Queue(maxsize=self.QUEUE_CAPACITY)
        self._threading = threading
        self._thread = None
        self._error = None
        self._result = None
        self._frame_count = 0
        self._state_lock = threading.Lock()
        self._started = False
        self._closed = False

    @property
    def frame_count(self) -> int:
        with self._state_lock:
            return self._frame_count

    @property
    def is_open(self) -> bool:
        return self._started and not self._closed

    def _check_error(self):
        if self._error is not None:
            raise CaptureStorageError(
                f"Background capture writer failed for {self.path}: {self._error}"
            ) from self._error

    def _enqueue(self, item):
        import queue
        while True:
            self._check_error()
            if self._thread is None or not self._thread.is_alive():
                self._check_error()
                raise CaptureStorageError("Background capture writer is not running.")
            try:
                self._queue.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def start(self, metadata: dict[str, Any] | None = None) -> Path:
        if self._started and not self._closed:
            raise CaptureStorageError("Streaming capture is already open.")
        path = self._writer.start(metadata)
        self._error = None
        self._result = None
        self._frame_count = 0
        self._closed = False
        self._started = True
        self._thread = self._threading.Thread(
            target=self._run, name="FreeRov3rCaptureWriter", daemon=True
        )
        self._thread.start()
        return path

    def append_frame(self, frame: dict[str, Any]) -> None:
        if not self.is_open:
            raise CaptureStorageError("Streaming capture is not open.")
        if not isinstance(frame, dict):
            raise CaptureStorageError("A captured frame must be a dictionary.")
        snapshot = dict(frame)
        self._enqueue(("frame", snapshot))
        with self._state_lock:
            self._frame_count += 1

    def _run(self):
        failed = False
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    break
                operation, payload = item
                if operation == "frame":
                    if not failed:
                        try:
                            self._writer.append_frame(payload)
                        except Exception as exc:
                            self._error = exc
                            failed = True
                            try:
                                self._writer.close_incomplete()
                            except Exception:
                                pass
                elif operation == "finish":
                    if not failed:
                        try:
                            self._result = self._writer.finish(payload)
                        except Exception as exc:
                            self._error = exc
                            failed = True
                            try:
                                self._writer.close_incomplete()
                            except Exception:
                                pass
                    break
                elif operation == "incomplete":
                    if not failed:
                        try:
                            self._writer.close_incomplete()
                        except Exception as exc:
                            self._error = exc
                    break
            finally:
                self._queue.task_done()
        # A failed writer drains queued items until the caller's stop command,
        # preventing a producer from deadlocking on a full queue.

    def _stop_and_join(self, command):
        self._enqueue(command)
        self._thread.join()
        self._closed = True
        self._check_error()

    def finish(self, metadata: dict[str, Any] | None = None) -> Path:
        if not self.is_open:
            raise CaptureStorageError("Streaming capture is not open.")
        self._stop_and_join(("finish", metadata or {}))
        if self._result is None:
            raise CaptureStorageError("Background capture writer did not finalize the archive.")
        return self._result

    def close_incomplete(self) -> None:
        if not self.is_open:
            return
        self._stop_and_join(("incomplete", None))


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
