"""Centralized ESP32 transport discovery and adapter construction.

Discovery reads OS serial metadata only. It never probes an adapter or sends
commands to the vehicle network.
"""
from __future__ import annotations

from .interface_discovery import discover_interfaces
from .esp32_stream_adapter import Esp32FramedSerialAdapter, Esp32WifiAdapter


class Esp32ConnectionManager:
    """Build supported receive-only ESP32 adapters from explicit endpoints."""

    WIFI_DEFAULT_PORT = 3333
    USB_DEFAULT_BAUDRATE = 921600

    @staticmethod
    def discover_usb_devices():
        """Return possible ESP32 USB serial candidates, not confirmed devices."""
        return [
            item for item in discover_interfaces()
            if item.get("kind") == "esp32"
        ]

    @classmethod
    def parse_wifi_endpoint(cls, endpoint):
        """Parse host, host:port, or [IPv6]:port without guessing an address."""
        value = str(endpoint or "").strip()
        if not value:
            raise ValueError("Enter the ESP32 Wi-Fi IP address or hostname")
        if value.startswith("["):
            closing = value.find("]")
            if closing < 0:
                raise ValueError("Invalid bracketed IPv6 address")
            host = value[1:closing]
            suffix = value[closing + 1:]
            if not host or (suffix and not suffix.startswith(":")):
                raise ValueError("Invalid ESP32 Wi-Fi endpoint")
            port_text = suffix[1:] if suffix else ""
        elif value.count(":") == 1:
            host, port_text = value.rsplit(":", 1)
        else:
            host, port_text = value, ""
        if not host:
            raise ValueError("Enter a valid ESP32 Wi-Fi host")
        try:
            port = int(port_text) if port_text else cls.WIFI_DEFAULT_PORT
        except ValueError as exc:
            raise ValueError("ESP32 Wi-Fi port must be a number") from exc
        if not 1 <= port <= 65535:
            raise ValueError("ESP32 Wi-Fi port must be between 1 and 65535")
        return host, port

    @classmethod
    def create_adapter(cls, transport, endpoint, *, channel_names=None):
        """Create a binary protocol v1 ESP32 adapter for USB or Wi-Fi."""
        value = str(endpoint or "").strip()
        if transport == "usb":
            if not value:
                raise ValueError("Select an ESP32 USB serial port")
            return Esp32FramedSerialAdapter(
                port=value,
                baudrate=cls.USB_DEFAULT_BAUDRATE,
                channel_names=channel_names,
            )
        if transport == "wifi":
            host, port = cls.parse_wifi_endpoint(value)
            return Esp32WifiAdapter(host, port=port, channel_names=channel_names)
        raise ValueError(f"Unsupported ESP32 transport: {transport}")
