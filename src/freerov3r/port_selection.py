"""Serial-interface inventory and adapter auto-selection."""

from PySide6.QtCore import Qt

from .hardware.interface_inventory import discover_all_interfaces


def refresh_serial_ports(window, discover=discover_all_interfaces):
    """Inventory serial interfaces and select only a single clear candidate."""
    current = window.channel_edit.currentText().strip()
    ports = discover()
    window.channel_edit.blockSignals(True)
    window.channel_edit.clear()
    for port in ports:
        window.channel_edit.addItem(port["device"], port["device"])
        index = window.channel_edit.count() - 1
        window.channel_edit.setItemData(
            index,
            f'{port["label"]} | {port["description"]} | '
            f'VID:PID {port["vid"] or "----"}:{port["pid"] or "----"}',
            Qt.ToolTipRole,
        )
    if current:
        window.channel_edit.setCurrentText(current)
    elif ports:
        window.channel_edit.setCurrentIndex(0)
    else:
        window.channel_edit.setEditText("")
        window.channel_edit.setPlaceholderText("No serial ports found; enter channel manually")
    window.channel_edit.blockSignals(False)

    # Only auto-select when exactly one recognized adapter candidate exists.
    recognized = [port for port in ports if port["kind"] in ("esp32", "elm327", "slcan")]
    if len(recognized) == 1:
        candidate = recognized[0]
        for index in range(window.backend.count()):
            data = window.backend.itemData(index)
            target_kind = (
                "esp32_framed_usb" if candidate["kind"] == "esp32"
                else candidate["kind"]
            )
            # Keep compatibility with callers that expose only the legacy
            # ESP32 backend; the full Capture UI prefers the binary transport.
            if candidate["kind"] == "esp32" and not any(
                window.backend.itemData(i)
                and window.backend.itemData(i)[0] == target_kind
                for i in range(window.backend.count())
            ):
                target_kind = "esp32"
            if data and data[0] == target_kind:
                window.backend.setCurrentIndex(index)
                window.channel_edit.setCurrentText(candidate["device"])
                break

    if ports:
        summary = ", ".join(
            f'{port["device"]}: {port["label"]}' for port in ports
        )
        window.status.setText("Interface inventory: " + summary)
    else:
        window.status.setText(
            "No USB/Bluetooth serial interfaces found. CAN channels can still be entered manually."
        )
