import pytest

from freerov3r.hardware.esp32_connection import Esp32ConnectionManager
from freerov3r.hardware.esp32_stream_adapter import (
    Esp32FramedSerialAdapter,
    Esp32WifiAdapter,
)


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("192.168.4.1", ("192.168.4.1", 3333)),
        ("192.168.4.1:4444", ("192.168.4.1", 4444)),
        ("esp32.local:3333", ("esp32.local", 3333)),
        ("[fe80::1234]:3333", ("fe80::1234", 3333)),
        ("fe80::1234", ("fe80::1234", 3333)),
    ],
)
def test_parse_wifi_endpoint(endpoint, expected):
    assert Esp32ConnectionManager.parse_wifi_endpoint(endpoint) == expected


@pytest.mark.parametrize(
    "endpoint",
    ["", ":3333", "192.168.4.1:notaport", "192.168.4.1:0", "192.168.4.1:65536", "[bad"],
)
def test_parse_wifi_endpoint_rejects_invalid_values(endpoint):
    with pytest.raises(ValueError):
        Esp32ConnectionManager.parse_wifi_endpoint(endpoint)


def test_create_usb_adapter_uses_binary_protocol_and_standard_baudrate():
    adapter = Esp32ConnectionManager.create_adapter("usb", "COM8")
    assert isinstance(adapter, Esp32FramedSerialAdapter)
    assert adapter.port == "COM8"
    assert adapter.baudrate == 921600
    assert adapter.diagnostics["mode"] == "receive-only"


def test_create_wifi_adapter_uses_binary_protocol():
    adapter = Esp32ConnectionManager.create_adapter("wifi", "192.168.4.1:4444")
    assert isinstance(adapter, Esp32WifiAdapter)
    assert adapter.host == "192.168.4.1"
    assert adapter.port == 4444
    assert adapter.diagnostics["mode"] == "receive-only"


def test_create_adapter_requires_explicit_endpoint():
    with pytest.raises(ValueError, match="USB serial port"):
        Esp32ConnectionManager.create_adapter("usb", "")
    with pytest.raises(ValueError, match="Wi-Fi IP"):
        Esp32ConnectionManager.create_adapter("wifi", "")


def test_create_adapter_rejects_unknown_transport():
    with pytest.raises(ValueError, match="Unsupported"):
        Esp32ConnectionManager.create_adapter("bluetooth", "COM8")


def test_usb_discovery_only_returns_possible_esp32_candidates(monkeypatch):
    monkeypatch.setattr(
        "freerov3r.hardware.esp32_connection.discover_interfaces",
        lambda: [
            {"device": "COM4", "kind": "esp32", "confidence": "possible"},
            {"device": "COM5", "kind": "elm327", "confidence": "likely"},
            {"device": "COM6", "kind": "serial", "confidence": "unknown"},
        ],
    )
    assert Esp32ConnectionManager.discover_usb_devices() == [
        {"device": "COM4", "kind": "esp32", "confidence": "possible"}
    ]
