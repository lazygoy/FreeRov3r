from freerov3r.vehicle_history import format_readiness_scan_event


def test_readiness_history_report_preserves_supported_and_incomplete_states():
    event = {
        "type": "readiness_scan_completed",
        "timestamp": "2026-11-26T03:00:00+00:00",
        "vin": "SALXXXXXXXXXXXX1",
        "summary": "OBD-II readiness scan completed: 1 ECU response(s)",
        "details": {
            "interface": "elm327_obd",
            "read_only": True,
            "results": [{
                "arbitration_id": 0x7E8,
                "is_extended_id": False,
                "channel": "COM9",
                "ignition_type": "spark",
                "mil_on": False,
                "dtc_count": 0,
                "raw": "00000F08",
                "monitors": [
                    {"name": "misfire", "supported": True, "complete": True},
                    {"name": "catalyst", "supported": True, "complete": False},
                    {"name": "heated_catalyst", "supported": False, "complete": None},
                ],
            }],
        },
    }

    report = format_readiness_scan_event(event)
    assert "VIN: SALXXXXXXXXXXXX1" in report
    assert "MIL: OFF" in report
    assert "DTC count: 0" in report
    assert "misfire | Supported | Complete" in report
    assert "catalyst | Supported | Incomplete" in report
    assert "heated_catalyst | Not supported | N/A" in report


def test_readiness_history_report_formats_failures():
    event = {
        "type": "readiness_scan_failed",
        "details": {"error": "No valid PID 01 response", "read_only": True},
    }
    report = format_readiness_scan_event(event)
    assert "Read-only: Yes" in report
    assert "Error: No valid PID 01 response" in report
