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
