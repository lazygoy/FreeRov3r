from freerov3r.vehicle_history import VehicleHistoryStore


def test_history_is_persistent_and_grouped_by_vin(tmp_path):
    path = tmp_path / "history.json"
    store = VehicleHistoryStore(path)
    store.record("SALXXXXXXXXXXXX1", "module_scan", "ECM scan", {"dtcs": ["P0420"]})
    store.record("SALYYYYYYYYYYYY2", "capture", "Capture completed", {"frames": 42})

    loaded = VehicleHistoryStore(path)
    assert len(loaded.for_vin("SALXXXXXXXXXXXX1")) == 1
    assert loaded.for_vin("SALXXXXXXXXXXXX1")[0]["details"]["dtcs"] == ["P0420"]
    assert len(loaded.for_vin("SALYYYYYYYYYYYY2")) == 1



def test_capture_archive_is_saved_under_vin_folder(tmp_path):
    store = VehicleHistoryStore(tmp_path / "vehicle_history.json")
    archive = store.archive_capture("SALXXXXXXXXXXXX1", {"frames": [], "sensor_samples": []})
    assert archive.exists()
    assert "SALXXXXXXXXXXXX1" in str(archive)



def test_vehicle_backup_contains_only_selected_vin_data(tmp_path):
    import json
    import zipfile

    store = VehicleHistoryStore(tmp_path / "vehicle_history.json")
    vin_a = "SALXXXXXXXXXXXX1"
    vin_b = "SALYYYYYYYYYYYY2"
    store.record(vin_a, "module_scan", "ECM scanned", {"dtcs": ["P0420"]})
    store.record(vin_b, "module_scan", "Other vehicle", {"dtcs": []})
    capture = store.archive_capture(vin_a, {"frames": [{"id": 2024}]})
    state_path = tmp_path / "vehicles" / vin_a / "simulated_modules.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"schema_version": 1, "modules": []}', encoding="utf-8")

    backup = store.export_vehicle_backup(vin_a, tmp_path / "backup.zip")
    assert backup.exists()
    with zipfile.ZipFile(backup) as bundle:
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "history.json" in names
        assert "simulated_modules.json" in names
        assert f"captures/{capture.name}" in names
        events = json.loads(bundle.read("history.json"))
        assert len(events) == 1
        assert events[0]["vin"] == vin_a
        assert json.loads(bundle.read("manifest.json"))["vin"] == vin_a


def test_vehicle_backup_requires_a_specific_vin(tmp_path):
    import pytest

    store = VehicleHistoryStore(tmp_path / "vehicle_history.json")
    with pytest.raises(ValueError):
        store.export_vehicle_backup("UNASSIGNED", tmp_path / "backup.zip")
