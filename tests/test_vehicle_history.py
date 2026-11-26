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


def test_freeze_frame_history_has_readable_measurements_and_failure():
    from freerov3r.vehicle_history import format_freeze_frame_scan_event

    event = {
        "type": "freeze_frame_scan_completed",
        "timestamp": "2026-11-26T04:00:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "summary": "Freeze-frame scan",
        "details": {
            "interface": "ELM327 OBD-II",
            "frame_number": 0,
            "read_only": True,
            "results": [{
                "pid": "0C",
                "frame_number": 0,
                "arbitration_id": 2024,
                "is_extended_id": False,
                "channel": "COM4",
                "raw": "420C1AF8",
                "measurements": [
                    {"key": "rpm", "name": "Engine RPM", "value": 1726, "unit": "rpm"},
                    {"key": "speed", "name": "Vehicle speed", "value": 40, "unit": "km/h"},
                ],
            }],
        },
    }
    report = format_freeze_frame_scan_event(event)
    assert "Freeze-frame number: 0" in report
    assert "Engine RPM: 1726 rpm" in report
    assert "Vehicle speed: 40 km/h" in report
    assert "ECU: 000007E8 (11-bit)" in report
    assert "Raw response: 420C1AF8" in report
    assert "Error: No response" in format_freeze_frame_scan_event({
        "type": "freeze_frame_scan_failed", "details": {"error": "No response"}
    })


def test_vehicle_info_history_has_readable_mode09_records_and_failure():
    from freerov3r.vehicle_history import format_vehicle_info_scan_event

    event = {
        "type": "vehicle_info_scan_completed",
        "timestamp": "2026-11-26T04:10:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "summary": "Mode 09 identification read",
        "details": {
            "interface": "ELM327 OBD-II",
            "service": "09",
            "read_only": True,
            "results": [{
                "pid": 2,
                "name": "Vehicle identification number",
                "count": 1,
                "arbitration_id": 2024,
                "is_extended_id": False,
                "channel": "COM4",
                "items": [{"type": "vin", "value": "SALXXXXXXXXXXXX1"}],
                "raw": "490201...",
            }, {
                "pid": 4,
                "name": "Calibration identification",
                "count": 1,
                "arbitration_id": 2024,
                "is_extended_id": False,
                "channel": "COM4",
                "items": [{"type": "calibration_id", "value": "CALID123"}],
                "raw": "4904...",
            }],
        },
    }
    report = format_vehicle_info_scan_event(event)
    assert "02 | Vehicle identification number" in report
    assert "vin: SALXXXXXXXXXXXX1" in report
    assert "calibration_id: CALID123" in report
    assert "Identification records: 2" in report
    assert "ECU: 000007E8 (11-bit)" in report
    assert "Error: No response" in format_vehicle_info_scan_event({
        "type": "vehicle_info_scan_failed", "details": {"error": "No response"}
    })


def test_history_json_export_preserves_complete_event_data(tmp_path):
    import json
    from freerov3r.vehicle_history import export_history_json

    events = [{
        "timestamp": "2026-11-26T05:00:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "type": "dtc_scan_completed",
        "summary": "One code",
        "details": {"dtcs": [{"code": "P0420"}]},
    }]
    destination = export_history_json(tmp_path / "exports" / "history.json", events)
    assert json.loads(destination.read_text(encoding="utf-8")) == events


def test_history_csv_export_keeps_nested_details_as_json(tmp_path):
    import csv
    import json
    from freerov3r.vehicle_history import export_history_csv

    events = [{
        "timestamp": "2026-11-26T05:00:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "type": "dtc_scan_completed",
        "summary": "One code",
        "details": {"dtcs": [{"code": "P0420"}]},
    }]
    destination = export_history_csv(tmp_path / "history.csv", events)
    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["vin"] == "SALXXXXXXXXXXXX1"
    assert rows[0]["type"] == "dtc_scan_completed"
    assert json.loads(rows[0]["details"]) == {"dtcs": [{"code": "P0420"}]}



def test_history_search_matches_vin_summary_and_nested_details_case_insensitively():
    from freerov3r.vehicle_history import search_history_events

    events = [
        {
            "timestamp": "2026-11-26T05:00:00+00:00",
            "vin": "SALXXXXXXXXXXXX1",
            "type": "dtc_scan_completed",
            "summary": "One trouble code",
            "details": {"dtcs": [{"code": "P0420", "status": "Stored"}]},
        },
        {
            "timestamp": "2026-11-26T06:00:00+00:00",
            "vin": "SALYYYYYYYYYYYY2",
            "type": "capture",
            "summary": "CAN capture",
            "details": {"frames": 42},
        },
    ]

    assert search_history_events(events, "p0420") == [events[0]]
    assert search_history_events(events, "salyyyy") == [events[1]]
    assert search_history_events(events, "CAN CAPTURE") == [events[1]]
    assert search_history_events(events, "  ") == events
    assert search_history_events(events, "not present") == []



def test_capture_history_report_formats_lifecycle_and_vin_metadata():
    from freerov3r.vehicle_history import format_capture_event

    completed = {
        "type": "capture_completed",
        "timestamp": "2026-11-26T07:00:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "summary": "CAN capture stopped",
        "details": {
            "interface": "ESP32 dual CAN",
            "channel": "HS-CAN",
            "bitrate": 500000,
            "frames": 1250,
            "sensor_samples": 84,
            "sensor_samples_dropped_from_bounded_buffer": 3,
            "duration_seconds": 61.5,
            "archive_file": "vehicles/SALXXXXXXXXXXXX1/captures/capture.json",
        },
    }
    report = format_capture_event(completed)
    assert "Channel: HS-CAN" in report
    assert "Bitrate: 500000" in report
    assert "Frames recorded: 1250" in report
    assert "Sensor samples: 84" in report
    assert "dropped from bounded buffer: 3" in report
    assert "Duration: 61.5 seconds" in report
    assert "capture.json" in report

    started = format_capture_event({
        "type": "capture_started",
        "details": {"interface": "python-can", "channel": "can0", "bitrate": 500000},
    })
    assert "Status: Started" in started
    assert "Channel: can0" in started
    assert "Bitrate: 500000" in started

    vin_report = format_capture_event({
        "type": "vin_detected",
        "vin": "SALXXXXXXXXXXXX1",
        "details": {"vin": "SALXXXXXXXXXXXX1", "source": "OBD Mode 09 PID 02"},
    })
    assert "Detected VIN: SALXXXXXXXXXXXX1" in vin_report
    assert "OBD Mode 09 PID 02" in vin_report



def test_can_activity_history_filter_includes_capture_and_vin_events_only():
    from freerov3r.vehicle_history import filter_can_activity_events

    events = [
        {"type": "capture_started", "summary": "Capture started"},
        {"type": "dtc_scan_completed", "summary": "DTC scan"},
        {"type": "capture_completed", "summary": "Capture completed"},
        {"type": "vin_detected", "summary": "VIN detected"},
        {"type": "monitor_tests_scan_failed", "summary": "Mode 06 failed"},
    ]

    assert filter_can_activity_events(events) == [
        events[0], events[2], events[3],
    ]
    assert filter_can_activity_events([]) == []
