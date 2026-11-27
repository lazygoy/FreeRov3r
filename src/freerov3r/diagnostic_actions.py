"""Read-only OBD-II diagnostic request and result handling."""

def est_dtc_scan(window):
    receiver = window.receiver
    if window.active_interface != "elm327_obd" or receiver is None:
        return False
    return receiver.request_dtcs()



def est_readiness_scan(window):
    receiver = window.receiver
    if window.active_interface != "elm327_obd" or receiver is None:
        return False
    return receiver.request_readiness()



def est_vehicle_info_scan(window):
    receiver = window.receiver
    if window.active_interface != "elm327_obd" or receiver is None:
        return False
    return receiver.request_vehicle_info()



def est_monitor_tests_scan(window):
    receiver = window.receiver
    if window.active_interface != "elm327_obd" or receiver is None:
        return False
    return receiver.request_monitor_tests()



def monitor_tests_scan_completed(window, result):
    window.obd_tab.show_monitor_test_results(result)
    responses = result.get("responses", [])
    count = sum(len(response.get("results", [])) for response in responses)
    window.record_vehicle_event(
        "monitor_tests_scan_completed",
        f"OBD-II Mode 06 monitor test scan completed: {count} result(s)",
        {
            "interface": window.active_interface,
            "service": "06",
            "supported_monitor_ids": result.get("supported_monitor_ids", []),
            "count": count,
            "results": result,
            "read_only": True,
            "values_are_raw": True,
        },
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast(
        f"Mode 06 read: {count} test result(s)",
        "success" if count else "warning",
    )



def monitor_tests_scan_failed(window, message):
    window.obd_tab.set_monitor_tests_scan_error(message)
    window.record_vehicle_event(
        "monitor_tests_scan_failed",
        "OBD-II Mode 06 monitor test read failed",
        {"interface": window.active_interface, "error": str(message), "read_only": True},
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast("Mode 06 read failed", "warning")



def vehicle_info_scan_completed(window, results):
    window.obd_tab.show_vehicle_info_results(results)
    detected_vins = {
        validate_vin(item.get("value"))
        for result in results if result.get("pid") == 0x02
        for item in result.get("items", []) if item.get("type") == "vin"
    }
    detected_vins.discard(None)
    if len(detected_vins) == 1:
        window._apply_detected_vin(next(iter(detected_vins)))
    window.record_vehicle_event(
        "vehicle_info_scan_completed",
        f"OBD-II Mode 09 identification read: {sum(len(item.get('items', [])) for item in results)} record(s)",
        {
            "interface": window.active_interface,
            "service": "09",
            "count": len(results),
            "results": results,
            "read_only": True,
        },
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast(
        f"Vehicle information read: {len(results)} ECU response(s)",
        "success" if results else "warning",
    )



def vehicle_info_scan_failed(window, message):
    window.obd_tab.set_vehicle_info_scan_error(message)
    window.record_vehicle_event(
        "vehicle_info_scan_failed",
        "OBD-II Mode 09 vehicle-information read failed",
        {"interface": window.active_interface, "error": str(message), "read_only": True},
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast("Vehicle-information read failed", "warning")



def est_freeze_frame_scan(window, pids, frame_number=0):
    receiver = window.receiver
    if window.active_interface != "elm327_obd" or receiver is None:
        return False
    return receiver.request_freeze_frame(pids, frame_number)



def freeze_frame_scan_completed(window, results):
    window.obd_tab.show_freeze_frame_results(results)
    window.record_vehicle_event(
        "freeze_frame_scan_completed",
        f"OBD-II freeze-frame scan completed: {len(results)} PID response(s)",
        {
            "interface": window.active_interface,
            "service": "02",
            "frame_number": window.obd_tab.freeze_frame_number.value(),
            "count": len(results),
            "results": results,
            "read_only": True,
        },
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast(
        f"Freeze-frame scan complete: {len(results)} PID response(s)",
        "success" if results else "warning",
    )



def freeze_frame_scan_failed(window, message):
    window.obd_tab.set_freeze_frame_scan_error(message)
    window.record_vehicle_event(
        "freeze_frame_scan_failed",
        "OBD-II freeze-frame scan failed",
        {"interface": window.active_interface, "error": str(message), "read_only": True},
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast("Freeze-frame scan failed", "warning")



def readiness_scan_completed(window, results):
    window.obd_tab.show_readiness_results(results)
    window.record_vehicle_event(
        "readiness_scan_completed",
        f"OBD-II readiness scan completed: {len(results)} ECU response(s)",
        {
            "interface": window.active_interface,
            "service": "01",
            "pid": "01",
            "count": len(results),
            "results": results,
            "read_only": True,
        },
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast(
        f"Readiness scan complete: {len(results)} ECU response(s)",
        "success" if results else "warning",
    )



def readiness_scan_failed(window, message):
    window.obd_tab.set_readiness_scan_error(message)
    window.record_vehicle_event(
        "readiness_scan_failed",
        "OBD-II readiness scan failed",
        {"interface": window.active_interface, "error": str(message), "read_only": True},
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast("Readiness scan failed", "warning")



def dtc_scan_completed(window, codes):
    window.obd_tab.show_dtc_results(codes)
    window.record_vehicle_event(
        "dtc_scan_completed",
        f"OBD-II DTC scan completed: {len(codes)} code record(s)",
        {
            "interface": window.active_interface,
            "services": ["03", "07", "0A"],
            "count": len(codes),
            "dtcs": codes,
            "read_only": True,
        },
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast(
        f"DTC scan complete: {len(codes)} code(s)",
        "success" if codes else "info",
    )



def dtc_scan_failed(window, message):
    window.obd_tab.set_dtc_scan_error(message)
    window.record_vehicle_event(
        "dtc_scan_failed",
        "OBD-II DTC scan failed",
        {"interface": window.active_interface, "error": str(message), "read_only": True},
        vin=window.capture_vin or window.settings.get("current_vin") or "UNASSIGNED",
    )
    window.show_toast("DTC scan failed", "warning")

