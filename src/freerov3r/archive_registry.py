"""Persistent local register of firmware archive and verification history.

The register is an index, not a substitute for either archived copy or its
manifest. Losing this file does not invalidate the archives themselves.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArchiveRegistryError(Exception):
    """Raised when the local archive register cannot be safely read or written."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_archive_records(registry_path: str | Path) -> list[dict[str, Any]]:
    path = Path(registry_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveRegistryError(f"Cannot read backup register {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != "freerov3r-archive-register-v1":
        raise ArchiveRegistryError(f"Unsupported or malformed backup register: {path}")
    records = data.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ArchiveRegistryError(f"Malformed backup register records: {path}")
    return records


def _write_records(registry_path: str | Path, records: list[dict[str, Any]]) -> None:
    path = Path(registry_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "freerov3r-archive-register-v1",
            "updated_at_utc": _timestamp(),
            "records": records,
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    except (OSError, TypeError, ValueError) as exc:
        raise ArchiveRegistryError(f"Cannot update backup register {path}: {exc}") from exc


def record_archive(registry_path: str | Path, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or not result.get("verified"):
        raise ArchiveRegistryError("Only a successfully verified dual archive can be registered.")
    manifest = result.get("manifest")
    files = result.get("files")
    if not isinstance(manifest, dict) or not isinstance(files, list) or not files:
        raise ArchiveRegistryError("Archive result is missing its manifest or file verification details.")
    metadata = manifest.get("files", [{}])[0].get("metadata", {})
    first = files[0]
    internal_copy = first.get("copies", {}).get("internal", {})
    record = {
        "timestamp_utc": _timestamp(),
        "last_verified_utc": _timestamp(),
        "status": "verified",
        "vin": metadata.get("vin", "unknown") if isinstance(metadata, dict) else "unknown",
        "module": metadata.get("module", "unknown") if isinstance(metadata, dict) else "unknown",
        "hardware_id": metadata.get("hardware_id", "unknown") if isinstance(metadata, dict) else "unknown",
        "software_id": metadata.get("software_id", "unknown") if isinstance(metadata, dict) else "unknown",
        "calibration_id": metadata.get("calibration_id", "unknown") if isinstance(metadata, dict) else "unknown",
        "file_name": Path(first.get("path", "unknown")).name,
        "sha256": internal_copy.get("sha256", "unknown"),
        "internal_archive": result.get("internal_archive", ""),
        "removable_archive": result.get("removable_archive", ""),
        "file_count": len(files),
    }
    records = load_archive_records(registry_path)
    records.append(record)
    _write_records(registry_path, records)
    return record


def record_verification(
    registry_path: str | Path,
    internal_archive: str | Path,
    removable_archive: str | Path,
    result: dict[str, Any],
) -> None:
    records = load_archive_records(registry_path)
    internal = str(Path(internal_archive))
    removable = str(Path(removable_archive))
    matches = [
        item for item in records
        if item.get("internal_archive") == internal and item.get("removable_archive") == removable
    ]
    if not matches:
        if result.get("verified"):
            record_archive(registry_path, result)
        return
    timestamp = _timestamp()
    for item in matches:
        item["last_verified_utc"] = timestamp
        item["status"] = "verified" if result.get("verified") else "verification_failed"
    _write_records(registry_path, records)
