"""Integrity-checked dual-location archive for original ECU firmware files.

This module only manages local files. It does not communicate with vehicle ECUs
or claim that a stored file is sufficient to recover a module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any


MANIFEST_NAME = "freerov3r-recovery-manifest.json"
CHUNK_SIZE = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
    try:
        internal = internal_root.resolve()
        removable = removable_root.resolve()
    except OSError as exc:
        raise ArchiveError(f"Cannot resolve archive destinations: {exc}") from exc
    if internal == removable or internal in removable.parents or removable in internal.parents:
        raise ArchiveError("Internal and removable archive locations must be separate, non-nested destinations.")


def inspect_destination(root: str | Path, *, required_bytes: int = 0, test_write: bool = False) -> dict[str, Any]:
    """Report destination capacity and optionally perform a write/read probe."""
    destination = Path(root).expanduser()
    if isinstance(required_bytes, bool) or not isinstance(required_bytes, int) or required_bytes < 0:
        raise ArchiveError("Required archive space must be a non-negative integer.")
    try:
        if not destination.exists() or not destination.is_dir():
            raise ArchiveError(f"Archive destination is missing or is not a directory: {destination}")
        usage = shutil.disk_usage(destination)
    except OSError as exc:
        raise ArchiveError(f"Cannot inspect archive destination {destination}: {exc}") from exc
    if usage.free < required_bytes:
        raise ArchiveError(
            f"Insufficient free space at {destination}: "
            f"{usage.free} bytes free, {required_bytes} bytes required."
        )
    if test_write:
        _test_writable(destination)
    return {
        "path": str(destination.resolve()),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "required_bytes": required_bytes,
        "enough_space": True,
        "write_test_passed": bool(test_write),
    }


def _test_writable(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise ArchiveError(f"Archive destination is not a directory: {root}")
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
    raw = str(value)
    windows_path = PureWindowsPath(raw)
    relative = Path(raw)
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or relative.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or not relative.parts
        or any(part in ("..", "") for part in relative.parts)
    ):
        raise ArchiveError("Archive file paths must be relative and cannot escape the archive directory.")
    return relative


def _archive_target(root: Path, relative: Path) -> Path:
    """Return a contained target while rejecting symlinks in every path component."""
    if root.is_symlink():
        raise ArchiveError(f"Archive directory cannot be a symbolic link: {root}")
    try:
        resolved_root = root.resolve()
        candidate = root / relative
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ArchiveError(f"Symbolic links are not allowed in archive paths: {current}")
        if not candidate.resolve().is_relative_to(resolved_root):
            raise ArchiveError("Archive file path resolves outside the archive directory.")
    except OSError as exc:
        raise ArchiveError(f"Cannot safely resolve archive path: {exc}") from exc
    return candidate


def _read_manifest(archive: Path) -> dict[str, Any]:
    manifest_path = _archive_target(archive, Path(MANIFEST_NAME))
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"Cannot read archive manifest at {manifest_path}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("format") != "freerov3r-recovery-archive-v1"
        or not isinstance(data.get("files"), list)
    ):
        raise ArchiveError(f"Unsupported or malformed archive manifest: {manifest_path}")
    for entry in data["files"]:
        if not isinstance(entry, dict):
            raise ArchiveError(f"Malformed file entry in archive manifest: {manifest_path}")
        relative = _safe_relative_path(entry.get("path", ""))
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ArchiveError(f"Invalid SHA-256 entry for {relative}")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ArchiveError(f"Invalid file size entry for {relative}")
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
    inspect_destination(internal, required_bytes=source_size)
    inspect_destination(removable, required_bytes=source_size)

    subdir = _safe_relative_path(archive_subdir)
    file_relative = _safe_relative_path(relative_file_path or Path("original") / source.name)
    internal_archive = internal / subdir
    removable_archive = removable / subdir
    internal_target = _archive_target(internal_archive, file_relative)
    removable_target = _archive_target(removable_archive, file_relative)
    internal_manifest = _archive_target(internal_archive, Path(MANIFEST_NAME))
    removable_manifest = _archive_target(removable_archive, Path(MANIFEST_NAME))

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
    try:
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchiveError(f"Archive metadata must be JSON-serializable: {exc}") from exc

    try:
        for root, target in ((internal_archive, internal_target), (removable_archive, removable_target)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target = _archive_target(root, file_relative)
            temporary = target.with_name(target.name + ".freerov3r-tmp")
            if temporary.exists() or temporary.is_symlink():
                raise ArchiveError(f"Temporary archive path already exists: {temporary}")
            shutil.copyfile(source, temporary)
            if temporary.stat().st_size != source_size or sha256_file(temporary) != source_hash:
                temporary.unlink(missing_ok=True)
                raise ArchiveError(f"Read-back verification failed while copying to {target.parent}")
            temporary.replace(target)

        for archive, manifest_path in (
            (internal_archive, internal_manifest),
            (removable_archive, removable_manifest),
        ):
            archive.mkdir(parents=True, exist_ok=True)
            manifest_path = _archive_target(archive, Path(MANIFEST_NAME))
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



def create_dual_backup_bundle(
    source_files: list[dict[str, Any]],
    internal_root: str | Path,
    removable_root: str | Path,
    *,
    archive_subdir: str | Path = "FreeRov3r/recovery",
) -> dict[str, Any]:
    """Archive multiple original files to two destinations and verify read-back.

    Each item must contain source_file and may contain relative_file_path
    and metadata. All inputs and destination capacity are checked before
    any archive file is written. Existing archive data is never overwritten.
    """
    if not isinstance(source_files, list) or not source_files:
        raise ArchiveError("A recovery bundle must contain at least one source file.")

    prepared = []
    seen_paths = set()
    total_size = 0
    for item in source_files:
        if not isinstance(item, dict) or "source_file" not in item:
            raise ArchiveError("Each recovery bundle item must identify a source_file.")
        source = Path(item["source_file"])
        if not source.is_file():
            raise ArchiveError(f"Source firmware file does not exist: {source}")
        relative = _safe_relative_path(
            item.get("relative_file_path") or Path("original") / source.name
        )
        relative_key = relative.as_posix().casefold()
        if relative_key in seen_paths:
            raise ArchiveError(f"Recovery bundle contains a duplicate archive path: {relative}")
        seen_paths.add(relative_key)
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ArchiveError("Recovery bundle metadata must be a dictionary.")
        try:
            json.dumps(metadata)
            digest = sha256_file(source)
            size = source.stat().st_size
        except (OSError, TypeError, ValueError) as exc:
            raise ArchiveError(f"Cannot read or describe source file {source}: {exc}") from exc
        prepared.append({
            "source": source,
            "relative": relative,
            "metadata": metadata,
            "sha256": digest,
            "size_bytes": size,
        })
        total_size += size

    internal = Path(internal_root).expanduser()
    removable = Path(removable_root).expanduser()
    _distinct_destinations(internal, removable)
    _test_writable(internal)
    _test_writable(removable)
    inspect_destination(internal, required_bytes=total_size)
    inspect_destination(removable, required_bytes=total_size)

    subdir = _safe_relative_path(archive_subdir)
    internal_archive = internal / subdir
    removable_archive = removable / subdir
    entries = []
    for item in prepared:
        entries.append({
            "path": item["relative"].as_posix(),
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
            "source_name": item["source"].name,
            "acquired_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metadata": item["metadata"],
        })
    manifest = {
        "format": "freerov3r-recovery-archive-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": entries,
    }
    try:
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchiveError(f"Archive metadata must be JSON-serializable: {exc}") from exc

    targets = []
    for archive in (internal_archive, removable_archive):
        manifest_target = _archive_target(archive, Path(MANIFEST_NAME))
        if manifest_target.exists():
            raise ArchiveError(f"Refusing to overwrite existing recovery data: {manifest_target}")
        for item in prepared:
            target = _archive_target(archive, item["relative"])
            if target.exists():
                raise ArchiveError(f"Refusing to overwrite existing recovery data: {target}")
            targets.append((archive, target, item))

    try:
        for archive, target, item in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = _archive_target(archive, item["relative"])
            temporary = target.with_name(target.name + ".freerov3r-tmp")
            if temporary.exists() or temporary.is_symlink():
                raise ArchiveError(f"Temporary archive path already exists: {temporary}")
            shutil.copyfile(item["source"], temporary)
            if temporary.stat().st_size != item["size_bytes"] or sha256_file(temporary) != item["sha256"]:
                temporary.unlink(missing_ok=True)
                raise ArchiveError(f"Read-back verification failed while copying to {target.parent}")
            temporary.replace(target)

        for archive in (internal_archive, removable_archive):
            archive.mkdir(parents=True, exist_ok=True)
            manifest_target = _archive_target(archive, Path(MANIFEST_NAME))
            with manifest_target.open("xb") as handle:
                handle.write(manifest_bytes)
                handle.flush()
                os.fsync(handle.fileno())

        result = verify_dual_backup(internal_archive, removable_archive)
        if not result["verified"]:
            raise ArchiveError("Dual-location recovery bundle failed final verification.")
        return result
    except OSError as exc:
        raise ArchiveError(f"Unable to complete dual-location recovery bundle: {exc}") from exc

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
        relative = _safe_relative_path(entry["path"])
        expected_hash = entry["sha256"]
        expected_size = entry["size_bytes"]
        copies = {}
        for label, root in (("internal", internal), ("removable", removable)):
            path = _archive_target(root, relative)
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
