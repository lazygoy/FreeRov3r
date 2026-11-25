"""Integrity-checked dual-location archive for original ECU firmware files.

This module only manages local files. It does not communicate with vehicle ECUs
or claim that a stored file is sufficient to recover a module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = "freerov3r-recovery-manifest.json"
CHUNK_SIZE = 1024 * 1024


class ArchiveError(Exception):
    """Raised when a recovery archive cannot be safely created or verified."""


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a readable file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distinct_destinations(internal_root: Path, removable_root: Path) -> None:
    internal = internal_root.resolve()
    removable = removable_root.resolve()
    if internal == removable or internal in removable.parents or removable in internal.parents:
        raise ArchiveError("Internal and removable archive locations must be separate, non-nested destinations.")


def _test_writable(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ArchiveError(f"Archive destination is not a directory: {root}")
    try:
        with tempfile.NamedTemporaryFile(prefix=".freerov3r-write-test-", dir=root, delete=True) as handle:
            handle.write(b"FreeRov3r archive write/read test")
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            if handle.read() != b"FreeRov3r archive write/read test":
                raise ArchiveError(f"Write/read verification failed: {root}")
    except OSError as exc:
        raise ArchiveError(f"Archive destination is not writable: {root}: {exc}") from exc


def _safe_relative_path(value: str | Path) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or any(part in ("..", "") for part in relative.parts):
        raise ArchiveError("Archive file paths must be relative and cannot escape the archive directory.")
    return relative


def _read_manifest(archive: Path) -> dict[str, Any]:
    manifest_path = archive / MANIFEST_NAME
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"Cannot read archive manifest at {manifest_path}: {exc}") from exc
    if data.get("format") != "freerov3r-recovery-archive-v1" or not isinstance(data.get("files"), list):
        raise ArchiveError(f"Unsupported or malformed archive manifest: {manifest_path}")
    return data


def create_dual_backup(
    source_file: str | Path,
    internal_root: str | Path,
    removable_root: str | Path,
    *,
    archive_subdir: str | Path = "FreeRov3r/recovery",
    relative_file_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy one original file to two destinations and verify both by read-back.

    Existing archive files or manifests are never overwritten. A failed second
    copy may leave the first verified copy in place; the returned exception
    makes no claim that the operation completed successfully.
    """
    source = Path(source_file)
    if not source.is_file():
        raise ArchiveError(f"Source firmware file does not exist: {source}")
    try:
        source_hash = sha256_file(source)
        source_size = source.stat().st_size
    except OSError as exc:
        raise ArchiveError(f"Source firmware file cannot be read: {exc}") from exc

    internal = Path(internal_root).expanduser()
    removable = Path(removable_root).expanduser()
    _distinct_destinations(internal, removable)
    _test_writable(internal)
    _test_writable(removable)

    subdir = _safe_relative_path(archive_subdir)
    file_relative = _safe_relative_path(relative_file_path or Path("original") / source.name)
    internal_archive = internal / subdir
    removable_archive = removable / subdir
    internal_target = internal_archive / file_relative
    removable_target = removable_archive / file_relative
    internal_manifest = internal_archive / MANIFEST_NAME
    removable_manifest = removable_archive / MANIFEST_NAME

    for target in (internal_target, removable_target, internal_manifest, removable_manifest):
        if target.exists():
            raise ArchiveError(f"Refusing to overwrite existing recovery data: {target}")

    entry = {
        "path": file_relative.as_posix(),
        "size_bytes": source_size,
        "sha256": source_hash,
        "source_name": source.name,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metadata": metadata or {},
    }
    manifest = {
        "format": "freerov3r-recovery-archive-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [entry],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    try:
        for target in (internal_target, removable_target):
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".freerov3r-tmp")
            if temporary.exists():
                raise ArchiveError(f"Temporary archive path already exists: {temporary}")
            shutil.copyfile(source, temporary)
            if temporary.stat().st_size != source_size or sha256_file(temporary) != source_hash:
                temporary.unlink(missing_ok=True)
                raise ArchiveError(f"Read-back verification failed while copying to {target.parent}")
            temporary.replace(target)

        for manifest_path in (internal_manifest, removable_manifest):
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("xb") as handle:
                handle.write(manifest_bytes)
                handle.flush()
                os.fsync(handle.fileno())

        result = verify_dual_backup(internal_archive, removable_archive)
        if not result["verified"]:
            raise ArchiveError("Dual-location archive failed final verification.")
        return result
    except OSError as exc:
        raise ArchiveError(f"Unable to complete dual-location archive: {exc}") from exc


def verify_dual_backup(
    internal_archive: str | Path,
    removable_archive: str | Path,
) -> dict[str, Any]:
    """Reopen both manifests and all archived files, then compare hashes."""
    internal = Path(internal_archive)
    removable = Path(removable_archive)
    _distinct_destinations(internal, removable)
    internal_manifest = _read_manifest(internal)
    removable_manifest = _read_manifest(removable)
    if internal_manifest != removable_manifest:
        raise ArchiveError("Internal and removable archive manifests do not match.")

    file_results = []
    for entry in internal_manifest["files"]:
        relative = _safe_relative_path(entry.get("path", ""))
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ArchiveError(f"Invalid SHA-256 entry for {relative}")
        copies = {}
        for label, root in (("internal", internal), ("removable", removable)):
            path = root / relative
            try:
                actual_size = path.stat().st_size
                actual_hash = sha256_file(path)
                readable = True
            except OSError:
                actual_size = None
                actual_hash = None
                readable = False
            copies[label] = {
                "path": str(path),
                "readable": readable,
                "size_bytes": actual_size,
                "sha256": actual_hash,
                "matches_manifest": readable and actual_size == expected_size and actual_hash == expected_hash,
            }
        file_results.append({
            "path": relative.as_posix(),
            "verified": all(copy["matches_manifest"] for copy in copies.values()),
            "copies": copies,
        })

    return {
        "verified": bool(file_results) and all(item["verified"] for item in file_results),
        "internal_archive": str(internal),
        "removable_archive": str(removable),
        "files": file_results,
        "manifest": internal_manifest,
    }
