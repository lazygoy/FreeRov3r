import time

import can

from .base import CanAdapter
from ..models import CanFrame


class PythonCanAdapter(CanAdapter):
    def __init__(self, interface="virtual", channel="freerov3r", bitrate=500000, **kwargs):
        self.interface, self.channel, self.bitrate = interface, channel, bitrate
        self.kwargs, self.bus = kwargs, None

    @property
    def description(self):
        return f"{self.interface}:{self.channel} @ {self.bitrate} bit/s"

    def open(self):
        self.bus = can.Bus(interface=self.interface, channel=self.channel,
                           bitrate=self.bitrate, **self.kwargs)

    def close(self):
        if self.bus is not None:
            self.bus.shutdown()
            self.bus = None

    def receive(self, timeout=0.2):
        if self.bus is None:
            raise RuntimeError("CAN adapter is not open")
        msg = self.bus.recv(timeout)
        if msg is None:
            return None
        # Python-CAN timestamps are wall-clock epoch values. Normalize the
        # application timestamp to the host monotonic clock and preserve the
        # backend timestamp separately for traceability.
        return CanFrame(
            arbitration_id=msg.arbitration_id,
            data=bytes(msg.data),
            is_extended_id=msg.is_extended_id,
            is_remote_frame=msg.is_remote_frame,
            is_error_frame=msg.is_error_frame,
            channel=str(msg.channel),
            timestamp=time.monotonic(),
            timestamp_clock_domain="host_monotonic",
            timestamp_source="python_can_receive",
            source_timestamp=msg.timestamp,
            source_timestamp_clock_domain="unix_epoch",
        )
