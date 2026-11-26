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


def test_mode06_history_filter_and_readable_raw_report():
    from freerov3r.vehicle_history import filter_mode06_scan_events, format_mode06_scan_event

    events = [
        {"type": "capture", "summary": "Capture"},
        {
            "type": "monitor_tests_scan_completed",
            "timestamp": "2026-11-26T03:00:00+00:00",
            "vin": "SALXXXXXXXXXXXX1",
            "summary": "OBD-II Mode 06 monitor test scan completed: 1 result(s)",
            "details": {
                "interface": "elm327_obd",
                "service": "06",
                "supported_monitor_ids": [1, 2],
                "count": 1,
                "read_only": True,
                "values_are_raw": True,
                "results": {
                    "responses": [{
                        "monitor_id": 1,
                        "arbitration_id": 2024,
                        "is_extended_id": False,
                        "channel": "COM4",
                        "results": [{
                            "test_id": 128,
                            "unit_scaling_id": 36,
                            "value_raw": 100,
                            "minimum_raw": 0,
                            "maximum_raw": 200,
                            "status": "within_limits",
                            "raw": "0180240064000000C8",
                        }],
                    }],
                },
            },
        },
        {"type": "monitor_tests_scan_failed", "details": {"error": "No response"}},
    ]

    scans = filter_mode06_scan_events(events)
    assert [event["type"] for event in scans] == [
        "monitor_tests_scan_completed",
        "monitor_tests_scan_failed",
    ]
    report = format_mode06_scan_event(scans[0])
    assert "MID: 01" in report
    assert "\\n" not in report
    assert "MODE 06 TEST RESULTS (RAW)" in report
    assert "ECU: 000007E8 (11-bit)" in report.splitlines()
    assert "TID: 80" in report
    assert "UASID: 24" in report
    assert "Value (raw): 100" in report
    assert "ECU: 000007E8 (11-bit)" in report
    assert "No engineering units or scaling are inferred." in report
    assert "Error: No response" in format_mode06_scan_event(scans[1])



def test_obd_history_filters_cover_all_supported_scan_families():
    from freerov3r.vehicle_history import (
        filter_obd_scan_events, filter_readiness_scan_events,
        filter_freeze_frame_scan_events, filter_vehicle_info_scan_events,
    )

    events = [
        {"type": "capture"},
        {"type": "dtc_scan_completed"},
        {"type": "readiness_scan_failed"},
        {"type": "freeze_frame_scan_completed"},
        {"type": "vehicle_info_scan_failed"},
        {"type": "monitor_tests_scan_completed"},
        {"type": "unrelated_event"},
    ]
    assert [event["type"] for event in filter_obd_scan_events(events)] == [
        "dtc_scan_completed", "readiness_scan_failed",
        "freeze_frame_scan_completed", "vehicle_info_scan_failed",
        "monitor_tests_scan_completed",
    ]
    assert [event["type"] for event in filter_readiness_scan_events(events)] == ["readiness_scan_failed"]
    assert [event["type"] for event in filter_freeze_frame_scan_events(events)] == ["freeze_frame_scan_completed"]
    assert [event["type"] for event in filter_vehicle_info_scan_events(events)] == ["vehicle_info_scan_failed"]
