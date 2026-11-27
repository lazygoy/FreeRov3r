"""Vehicle list, selection and VIN detection workflows."""

from PySide6.QtWidgets import QMessageBox

from .diagnostics.vehicle_identification import identify_vehicle, validate_vin


def _refresh_vehicle_list(window):
    window.vehicle_list.clear()
    vehicles = window.settings.get("vehicles", {})
    for vin, info in sorted(vehicles.items()):
        nick = info.get("nickname", "")
        model = info.get("model", "")
        label = nick or model
        window.vehicle_list.addItem(f"{vin}  —  {label}" if label else vin)
    current = window.settings.get("current_vin")
    if current and current in vehicles:
        nick = vehicles[current].get("nickname", "")
        window.current_vehicle_label.setText(f"Current: {current} ({nick})" if nick else f"Current: {current}")
    else:
        window.current_vehicle_label.setText("No vehicle selected")



def add_or_update_vehicle(window):
    vin = window.vin_edit.text().strip().upper()
    nickname = window.nickname_edit.text().strip()
    if not validate_vin(vin):
        QMessageBox.warning(window, "Invalid VIN", "Enter a valid 17-character VIN (letters I, O and Q are not used).")
        return
    identification = identify_vehicle(vin)
    vehicle = window.settings.setdefault("vehicles", {}).get(vin, {}).copy()
    vehicle.update({
        "nickname": nickname,
        "make": identification.get("make") or vehicle.get("make", ""),
        "model": identification.get("model") or vehicle.get("model", ""),
        "model_year": identification.get("model_year") or vehicle.get("model_year"),
        "profile_id": identification.get("profile_id", "generic"),
        "variant_id": identification.get("variant_id"),
        "identification_confidence": identification.get("confidence", "unknown"),
    })
    window.settings["vehicles"][vin] = vehicle
    window.settings["current_vin"] = vin
    window.settings["active_vehicle"] = vehicle.copy()
    window.research_tab.set_context(vin, window.active_interface, vehicle)
    window._refresh_vehicle_list()
    window._update_vehicle_context()
    window.research_tab.set_context(
        vin, window.active_interface,
        window.settings.get("active_vehicle", {}),
    )
    window.save_current_settings()
    window.vin_edit.clear()
    window.nickname_edit.clear()



def set_current_vehicle(window):
    item = window.vehicle_list.currentItem()
    if not item:
        return
    vin = item.text().split("  —  ")[0]
    window.settings["current_vin"] = vin
    window.settings["active_vehicle"] = window.settings.get("vehicles", {}).get(vin, {}).copy()
    window._refresh_vehicle_list()
    window._update_vehicle_context()
    window.save_current_settings()



def on_vehicle_selected(window, item):
    vin = item.text().split("  —  ")[0]
    info = window.settings.get("vehicles", {}).get(vin, {})
    window.vin_edit.setText(vin)
    window.nickname_edit.setText(info.get("nickname", ""))



def _apply_detected_vin(window, vin):
    """Use a validated VIN decoded from observed diagnostic response traffic."""
    previous = window.settings.get("current_vin")
    if previous == vin:
        return
    if previous and previous != vin:
        window.log.appendPlainText(
            f"VIN mismatch: selected {previous}, scan data reports {vin}. Using scan-reported VIN."
        )
    identification = identify_vehicle(vin)
    vehicle = window.settings.setdefault("vehicles", {}).get(vin, {})
    vehicle.update({
        "make": identification.get("make") or vehicle.get("make", ""),
        "model": identification.get("model") or vehicle.get("model", ""),
        "model_year": identification.get("model_year") or vehicle.get("model_year"),
        "profile_id": identification.get("profile_id", "generic"),
        "variant_id": identification.get("variant_id"),
        "identification_confidence": identification.get("confidence", "unknown"),
    })
    window.settings["vehicles"][vin] = vehicle
    window.settings["active_vehicle"] = vehicle.copy()
    window.settings["current_vin"] = vin
    if window.receiver and window.receiver.isRunning():
        window.capture_vin = vin
        if window.capture_session_context is not None:
            window.capture_session_context.vin = vin
    window._refresh_vehicle_list()
    window._update_vehicle_context()
    window.save_current_settings()
    window.record_vehicle_event(
        "vin_detected", "VIN decoded from diagnostic traffic",
        {"vin": vin, "source": "OBD Mode 09 PID 02 or UDS DID F190"}, vin=vin
    )
    window.log.appendPlainText(f"VIN detected from scan data: {vin}")
    window.show_toast(f"VIN identified: {vin}", "success")


