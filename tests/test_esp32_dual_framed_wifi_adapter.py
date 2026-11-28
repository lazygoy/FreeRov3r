from freerov3r.hardware import esp32_dual_framed_wifi_adapter as module


class FakeWifiAdapter:
    def __init__(self, host, port=3333, channel_names=None):
        self.host = host
        self.port = port
        self.channel_names = channel_names or {}
        self.connected = False

    @property
    def description(self):
        return f"Wi-Fi TCP {self.host}:{self.port}"

    @property
    def diagnostics(self):
        return {
            "connected": self.connected,
            "frames_received": 0,
            "receiver_state": "receiving" if self.connected else "disconnected",
        }

    def open(self):
        self.connected = True

    def receive(self, timeout=0.1):
        return None

    def close(self):
        self.connected = False


def test_dual_framed_wifi_adapter_opens_two_independent_receivers(monkeypatch):
    created = []

    def create_adapter(transport, endpoint, *, channel_names=None):
        assert transport == "wifi"
        host, _, port = endpoint.partition(":")
        adapter = FakeWifiAdapter(host, int(port or 3333), channel_names)
        created.append(adapter)
        return adapter

    monkeypatch.setattr(
        module.Esp32ConnectionManager, "create_adapter", create_adapter
    )
    adapter = module.Esp32DualFramedWifiAdapter(
        ["192.168.4.10:3333", "192.168.4.11:3333"]
    )
    adapter.open()
    try:
        report = adapter.diagnostics
        assert report["connected"] is True
        assert [item["channel"] for item in report["channels"]] == [
            "HS-CAN", "MS-CAN"
        ]
        assert [item.host for item in created] == [
            "192.168.4.10", "192.168.4.11"
        ]
    finally:
        adapter.close()
    assert adapter.diagnostics["connected"] is False


def test_dual_framed_wifi_adapter_rejects_duplicate_endpoints():
    try:
        module.Esp32DualFramedWifiAdapter(
            ["192.168.4.10", "192.168.4.10"]
        )
    except ValueError as exc:
        assert "two different host:port endpoints" in str(exc)
    else:
        raise AssertionError("duplicate Wi-Fi endpoints must be rejected")
