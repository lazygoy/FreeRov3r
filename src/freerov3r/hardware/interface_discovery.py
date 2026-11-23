"""Safe local interface inventory and serial-adapter classification.

Discovery only reads operating-system port metadata. It never opens a port,
sends adapter commands, or touches the vehicle network.
"""
from .serial_ports import list_serial_ports


def classify_serial_port(port):
    """Return (kind, confidence, label) using descriptive USB/COM metadata."""
    text = " ".join(str(port.get(key) or "") for key in ("description", "hwid")).casefold()
    vid = (port.get("vid") or "").upper()
    pid = (port.get("pid") or "").upper()
    if "bluetooth" in text or "bth" in text:
        return "elm327", "likely", "Bluetooth serial (ELM327 candidate)"
    if any(token in text for token in ("slcan", "canable", "candlelight")):
        return "slcan", "likely", "USB CAN adapter (SLCAN candidate)"
    usb_uart_ids = {("10C4", "EA60"), ("1A86", "7523"), ("1A86", "55D4"), ("0403", "6001")}
    if (vid, pid) in usb_uart_ids or any(token in text for token in ("cp210", "ch340", "ch910", "ft232", "esp32")):
        return "esp32", "possible", "USB serial (ESP32 firmware candidate)"
    return "serial", "unknown", "Unclassified serial device"


def discover_interfaces():
    """Return serial candidates without opening or probing any device."""
    found = []
    for port in list_serial_ports():
        kind, confidence, label = classify_serial_port(port)
        found.append({**port, "kind": kind, "confidence": confidence, "label": label})
    return found
