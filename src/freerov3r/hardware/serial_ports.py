"""Cross-platform serial-port discovery helpers."""

from serial.tools import list_ports


def normalize_port_info(port):
    """Convert a pyserial ListPortInfo object to display-safe metadata."""
    return {
        "device": str(getattr(port, "device", "") or ""),
        "description": str(getattr(port, "description", "") or "Serial device"),
        "hwid": str(getattr(port, "hwid", "") or ""),
        "vid": f"{port.vid:04X}" if getattr(port, "vid", None) is not None else None,
        "pid": f"{port.pid:04X}" if getattr(port, "pid", None) is not None else None,
    }


def list_serial_ports():
    """Return detected serial devices, sorted by port name.

    An enumeration failure returns an empty list; users can still type a
    channel manually and the connection attempt will report its own error.
    """
    try:
        ports = [normalize_port_info(port) for port in list_ports.comports()]
    except Exception:
        return []
    return sorted((port for port in ports if port["device"]), key=lambda item: item["device"].casefold())
