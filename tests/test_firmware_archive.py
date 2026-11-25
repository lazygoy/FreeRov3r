from __future__ import annotations

import hashlib
import json

import pytest

from freerov3r.firmware_archive import (
    ArchiveError,
    MANIFEST_NAME,
    create_dual_backup,
    sha256_file,
    verify_dual_backup,
)


def test_dual_backup_copies_and_verifies_original(tmp_path):
    source = tmp_path / "stock_read.bin"
    source.write_bytes(bytes(range(256)) * 8)
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"

    result = create_dual_backup(
        source,
        internal,
        removable,
        metadata={"vin": "TESTVIN", "module": "ECM"},
    )

    assert result["verified"] is True
    assert len(result["files"]) == 1
    assert result["files"][0]["verified"] is True
    assert result["files"][0]["copies"]["internal"]["sha256"] == sha256_file(source)
    assert result["files"][0]["copies"]["removable"]["sha256"] == sha256_file(source)
    assert (internal / "FreeRov3r/recovery" / MANIFEST_NAME).is_file()
    assert (removable / "FreeRov3r/recovery" / MANIFEST_NAME).is_file()


def test_verification_detects_changed_copy(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"original firmware")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    archived = removable / "FreeRov3r/recovery/original/stock.bin"
    archived.write_bytes(b"modified or corrupted")

    result = verify_dual_backup(
        internal / "FreeRov3r/recovery",
        removable / "FreeRov3r/recovery",
    )
    assert result["verified"] is False
    assert result["files"][0]["copies"]["removable"]["matches_manifest"] is False


def test_verification_detects_unlisted_archive_files(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"original firmware")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    extra_internal = internal / "FreeRov3r/recovery/untracked/notes.txt"
    extra_removable = removable / "FreeRov3r/recovery/untracked/notes.txt"
    extra_internal.parent.mkdir(parents=True)
    extra_removable.parent.mkdir(parents=True)
    extra_internal.write_text("untracked internal file", encoding="utf-8")
    extra_removable.write_text("untracked removable file", encoding="utf-8")

    result = verify_dual_backup(
        internal / "FreeRov3r/recovery",
        removable / "FreeRov3r/recovery",
    )

    assert result["verified"] is False
    assert result["unexpected_files"] == {
        "internal": ["untracked/notes.txt"],
        "removable": ["untracked/notes.txt"],
    }


def test_existing_original_is_never_overwritten(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"first")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    source.write_bytes(b"second")
    with pytest.raises(ArchiveError, match="Refusing to overwrite"):
        create_dual_backup(source, internal, removable)

    assert (internal / "FreeRov3r/recovery/original/stock.bin").read_bytes() == b"first"


def test_same_or_nested_destinations_are_rejected(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    root = tmp_path / "archive"
    with pytest.raises(ArchiveError, match="separate"):
        create_dual_backup(source, root, root / "usb")


def test_manifest_path_traversal_is_rejected_even_when_manifests_match(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    for root in (internal, removable):
        manifest_path = root / "FreeRov3r/recovery" / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../../outside.bin"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArchiveError, match="relative"):
        verify_dual_backup(
            internal / "FreeRov3r/recovery",
            removable / "FreeRov3r/recovery",
        )


def test_manifest_rejects_non_hex_sha256(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    for root in (internal, removable):
        manifest_path = root / "FreeRov3r/recovery" / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["sha256"] = "z" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArchiveError, match="SHA-256"):
        verify_dual_backup(
            internal / "FreeRov3r/recovery",
            removable / "FreeRov3r/recovery",
        )


def test_archive_rejects_symlinked_file_parent(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    create_dual_backup(source, internal, removable)

    archive = internal / "FreeRov3r/recovery"
    original = archive / "original"
    outside = tmp_path / "outside"
    outside.mkdir()
    original.rename(archive / "original_saved")
    original.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArchiveError, match="Symbolic links"):
        verify_dual_backup(
            archive,
            removable / "FreeRov3r/recovery",
        )


def test_windows_absolute_and_backslash_paths_are_rejected(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    for unsafe in (r"C:\outside.bin", r"..\\outside.bin"):
        with pytest.raises(ArchiveError, match="relative"):
            create_dual_backup(
                source,
                tmp_path / "internal",
                tmp_path / "usb",
                relative_file_path=unsafe,
            )


def test_non_json_metadata_is_reported_as_archive_error(tmp_path):
    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware")
    with pytest.raises(ArchiveError, match="JSON-serializable"):
        create_dual_backup(
            source,
            tmp_path / "internal",
            tmp_path / "usb",
            metadata={"not_json": object()},
        )


def test_inspect_destination_reports_capacity_and_write_probe(tmp_path):
    from freerov3r.firmware_archive import inspect_destination

    destination = tmp_path / "storage"
    destination.mkdir()
    result = inspect_destination(destination, required_bytes=10, test_write=True)

    assert result["enough_space"] is True
    assert result["required_bytes"] == 10
    assert result["free_bytes"] > 0
    assert result["write_test_passed"] is True


def test_dual_backup_rejects_insufficient_destination_space(tmp_path, monkeypatch):
    from collections import namedtuple
    from pathlib import Path
    from freerov3r import firmware_archive

    source = tmp_path / "stock.bin"
    source.write_bytes(b"firmware payload")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    internal.mkdir()
    removable.mkdir()
    usage = namedtuple("Usage", "total used free")

    def disk_usage(path):
        if Path(path) == internal:
            return usage(1000, 999, 1)
        return usage(1000, 0, 1000)

    monkeypatch.setattr(firmware_archive.shutil, "disk_usage", disk_usage)
    with pytest.raises(ArchiveError, match="Insufficient free space"):
        create_dual_backup(source, internal, removable)
    assert not (internal / "FreeRov3r/recovery").exists()


def test_archive_registry_persists_and_updates_verification(tmp_path):
    from freerov3r.archive_registry import (
        load_archive_records,
        record_archive,
        record_verification,
    )

    source = tmp_path / "stock.bin"
    source.write_bytes(b"original calibration")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    result = create_dual_backup(
        source, internal, removable,
        metadata={"vin": "TESTVIN", "module": "ECM", "hardware_id": "HW1"},
    )
    registry = tmp_path / "register.json"

    record = record_archive(registry, result)
    assert record["vin"] == "TESTVIN"
    assert record["module"] == "ECM"
    assert record["hardware_id"] == "HW1"
    assert record["status"] == "verified"

    records = load_archive_records(registry)
    assert len(records) == 1
    assert records[0]["sha256"] == result["files"][0]["copies"]["internal"]["sha256"]

    record_verification(
        registry,
        internal / "FreeRov3r/recovery",
        removable / "FreeRov3r/recovery",
        result,
    )
    assert load_archive_records(registry)[0]["last_verified_utc"]


def test_archive_registry_preserves_each_file_identity(tmp_path):
    from freerov3r.archive_registry import record_archive
    from freerov3r.firmware_archive import create_dual_backup_bundle

    source = tmp_path / "stock.bin"
    second_source = tmp_path / "tcm.bin"
    source.write_bytes(b"original engine calibration")
    second_source.write_bytes(b"original transmission calibration")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"
    result = create_dual_backup_bundle(
        [
            {
                "source_file": source,
                "metadata": {"vin": "TESTVIN", "module": "ECM"},
            },
            {
                "source_file": second_source,
                "metadata": {
                    "vin": "TESTVIN",
                    "module": "TCM",
                    "hardware_id": "TCM-HW2",
                },
            },
        ],
        internal,
        removable,
    )

    assert result["verified"] is True
    assert len(result["files"]) == 2
    assert all(item["verified"] for item in result["files"])
    assert (internal / "FreeRov3r/recovery/original/stock.bin").read_bytes() == source.read_bytes()
    assert (removable / "FreeRov3r/recovery/original/tcm.bin").read_bytes() == second_source.read_bytes()

    record = record_archive(tmp_path / "register.json", result)

    assert record["file_count"] == 2
    assert [item["file_name"] for item in record["files"]] == [
        "stock.bin",
        "tcm.bin",
    ]
    assert record["files"][1]["metadata"]["module"] == "TCM"
    assert record["files"][1]["metadata"]["hardware_id"] == "TCM-HW2"
    assert record["files"][1]["internal"]["matches_manifest"] is True
    assert record["files"][1]["removable"]["matches_manifest"] is True


def test_dual_backup_bundle_rejects_duplicate_archive_paths(tmp_path):
    from freerov3r.firmware_archive import create_dual_backup_bundle

    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with pytest.raises(ArchiveError, match="duplicate archive path"):
        create_dual_backup_bundle(
            [
                {"source_file": first, "relative_file_path": "original/shared.bin"},
                {"source_file": second, "relative_file_path": "original/shared.bin"},
            ],
            tmp_path / "internal",
            tmp_path / "usb",
        )

    assert not (tmp_path / "internal/FreeRov3r/recovery").exists()


def test_dual_backup_bundle_rejects_file_directory_path_conflicts(tmp_path):
    from freerov3r.firmware_archive import create_dual_backup_bundle

    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with pytest.raises(ArchiveError, match="conflicting archive paths"):
        create_dual_backup_bundle(
            [
                {"source_file": first, "relative_file_path": "original/module"},
                {"source_file": second, "relative_file_path": "original/module/child.bin"},
            ],
            tmp_path / "internal",
            tmp_path / "usb",
        )

    assert not (tmp_path / "internal/FreeRov3r/recovery").exists()

def test_archive_registry_rejects_malformed_register(tmp_path):
    from freerov3r.archive_registry import ArchiveRegistryError, load_archive_records

    registry = tmp_path / "register.json"
    registry.write_text('{"format":"wrong","records":[]}', encoding="utf-8")
    with pytest.raises(ArchiveRegistryError, match="malformed"):
        load_archive_records(registry)
