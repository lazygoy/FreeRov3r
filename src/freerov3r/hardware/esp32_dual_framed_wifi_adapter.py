"""Two framed ESP32 Wi-Fi receivers for simultaneous dual-bus capture."""

from .esp32_connection import Esp32ConnectionManager
from .esp32_dual_framed_adapter import Esp32DualFramedSerialAdapter


class Esp32DualFramedWifiAdapter(Esp32DualFramedSerialAdapter):
    """Multiplex two independently addressed framed ESP32 TCP receivers."""

    def __init__(self, endpoints, *, channel_names=("HS-CAN", "MS-CAN"),
                 connect_timeout=3.0, queue_capacity=10000):
        if isinstance(endpoints, str):
            endpoints = [part.strip() for part in endpoints.split(",") if part.strip()]
        if len(endpoints or []) != 2 or str(endpoints[0]).casefold() == str(endpoints[1]).casefold():
            raise ValueError(
                "Dual framed ESP32 Wi-Fi capture requires two different host:port endpoints"
            )
        if len(channel_names) != 2:
            raise ValueError("Exactly two channel names are required")
        self.endpoints = [str(endpoint).strip() for endpoint in endpoints]
        adapters = [
            Esp32ConnectionManager.create_adapter(
                "wifi", endpoint,
                channel_names={0: channel, 1: channel},
            )
            for endpoint, channel in zip(self.endpoints, channel_names)
        ]
        super().__init__(
            self.endpoints,
            channel_names=channel_names,
            queue_capacity=queue_capacity,
            adapters=adapters,
        )

    @property
    def description(self):
        return "Dual framed ESP32 Wi-Fi: " + " + ".join(self.endpoints)
