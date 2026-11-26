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



def test_dtc_history_filter_and_readable_report():
    from freerov3r.vehicle_history import filter_dtc_scan_events, format_dtc_scan_event

    events = [
        {"type": "capture", "summary": "Capture"},
        {
            "type": "dtc_scan_completed",
            "timestamp": "2026-11-26T02:00:00+00:00",
            "vin": "SALXXXXXXXXXXXX1",
            "summary": "OBD-II DTC scan completed: 1 code record(s)",
            "details": {
                "interface": "ELM327 OBD-II",
                "services": ["03", "07", "0A"],
                "count": 1,
                "read_only": True,
                "dtcs": [{
                    "code": "P0133", "status": "Stored", "arbitration_id": 2024,
                    "is_extended_id": False, "channel": "COM4", "raw": "0133",
                }],
            },
        },
        {"type": "dtc_scan_failed", "details": {"error": "No response"}},
    ]

    scans = filter_dtc_scan_events(events)
    assert [event["type"] for event in scans] == ["dtc_scan_completed", "dtc_scan_failed"]
    report = format_dtc_scan_event(scans[0])
    assert "P0133 | Stored" in report
    assert "ECU 000007E8 (11-bit)" in report
    assert "OEM-specific descriptions are not inferred" in report
    assert "Error: No response" in format_dtc_scan_event(scans[1])
