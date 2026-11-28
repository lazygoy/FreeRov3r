"""Primary and advanced vehicle-interface choices for the FreeRov3r UI."""

PRIMARY_CONNECTION_OPTIONS = (
    ("elm327_obd", "ELM327 OBD-II (USB / Bluetooth serial)", ""),
    ("esp32_framed_dual_usb", "Dual ESP32 CAN (USB)", "COM3,COM4"),
    ("esp32_framed_dual_wifi", "Dual ESP32 CAN (Wi-Fi)", ""),
)

ADVANCED_CONNECTION_OPTIONS = (
    ("virtual", "Virtual CAN (no hardware)", "freerov3r"),
    ("dual_simulator", "Dual-channel CAN simulator (offline)", "offline"),
    ("capture_replay", "Capture replay (JSONL, offline)", ""),
    ("simulator", "Simulated vehicle (synthetic OBD-II)", "L319-DEMO"),
    ("esp32_framed_usb", "Single ESP32 CAN (USB)", "COM3"),
    ("esp32_framed_wifi", "Single ESP32 CAN (Wi-Fi)", ""),
    ("esp32", "ESP32 legacy serial adapter", "COM3"),
    ("esp32_dual", "ESP32 dual legacy serial", "COM3,COM4"),
    ("elm327", "ELM327 raw CAN monitor (advanced)", ""),
    ("socketcan", "SocketCAN", "can0"),
    ("slcan", "SLCAN", "COM3"),
    ("j2534", "J2534 Pass-Thru (registered driver)", ""),
)


def populate_connection_combo(combo, *, include_advanced=False, selected=None):
    """Populate a selector while preserving an existing backend when possible."""
    previous = selected if selected is not None else combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for interface, label, channel in PRIMARY_CONNECTION_OPTIONS:
        combo.addItem(label, (interface, channel))
    if include_advanced:
        combo.insertSeparator(combo.count())
        for interface, label, channel in ADVANCED_CONNECTION_OPTIONS:
            combo.addItem(label, (interface, channel))
    index = combo.findData(previous) if previous is not None else -1
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def select_connection_backend(combo, advanced_toggle, interface):
    """Select a saved backend, revealing the advanced list only when required."""
    index = next(
        (i for i, option in enumerate(ADVANCED_CONNECTION_OPTIONS)
         if option[0] == interface),
        None,
    )
    if index is not None and not advanced_toggle.isChecked():
        advanced_toggle.setChecked(True)
    for i in range(combo.count()):
        data = combo.itemData(i)
        if data and data[0] == interface:
            combo.setCurrentIndex(i)
            return True
    return False
