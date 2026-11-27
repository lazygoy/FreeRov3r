"""Application of vehicle setup wizard results."""

from PySide6.QtWidgets import QDialog


def run_setup_wizard(window):
    """Guide interface selection and vehicle-profile setup."""
    wizard = VehicleSetupWizard(window, window.settings)
    if wizard.exec() != QDialog.Accepted or not wizard.result_data:
        return
    data = wizard.result_data
    window.settings.update({
        "interface": data["interface"], "channel": data["channel"],
        "bitrate": data["bitrate"],
    })
    for combo in (window.backend, window.settings_backend):
        for index in range(combo.count()):
            item_data = combo.itemData(index)
            if item_data and item_data[0] == data["interface"]:
                combo.setCurrentIndex(index)
                break
    window.channel_edit.setCurrentText(data["channel"])
    window.settings_channel.setText(data["channel"])
    window.bitrate.setCurrentText(str(data["bitrate"]))
    window.settings_bitrate.setCurrentText(str(data["bitrate"]))
    vehicle = {
        "make": data["make"], "model": data["model"],
        "model_year": data["model_year"], "profile_id": data["profile_id"],
        "identification_confidence": data["identification"].get("confidence", "manual"),
        "variant_id": data["identification"].get("variant_id"),
        "profile_selection_explicit": True, "nickname": "",
    }
    vin = data["vin"]
    if vin:
        existing = window.settings.setdefault("vehicles", {}).get(vin, {})
        existing.update(vehicle)
        window.settings["vehicles"][vin] = existing
        window.settings["current_vin"] = vin
        window.settings["active_vehicle"] = existing.copy()
    else:
        window.settings["current_vin"] = None
        window.settings["active_vehicle"] = vehicle
    window._refresh_vehicle_list()
    window._update_vehicle_context()
    window.save_current_settings()
    window._navigate_to_tab("Capture")
    window.show_toast("Vehicle setup applied", "success")
