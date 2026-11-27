import time

import can

from .base import CanAdapter
from .capabilities import AdapterCapabilities, SOCKETCAN_CAPABILITIES
from ..models import CanFrame


class PythonCanAdapter(CanAdapter):
    def __init__(self, interface="virtual", channel="freerov3r", bitrate=500000, **kwargs):
        self.interface, self.channel, self.bitrate = interface, channel, bitrate
        self.kwargs, self.bus = kwargs, None

    @property
    def capabilities(self):
        # SocketCAN is the only backend explicitly declared transmit-capable
        # here. Other python-can interfaces may have hardware-specific limits.
        if str(self.interface).casefold() == "socketcan":
            return SOCKETCAN_CAPABILITIES
        return AdapterCapabilities(raw_can_receive=True)

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

    def send_frame(self, frame, authorize_transmit, timeout=1.0):
        """Send one classic CAN data frame after explicit per-frame approval.

        This low-level method deliberately does not own user policy. Callers
        must provide an authorization callback that returns exactly True for
        this frame. No default callback or implicit permission is provided.
        """
        if self.bus is None:
            raise RuntimeError("CAN adapter is not open")
        if not isinstance(frame, CanFrame):
            raise TypeError("frame must be a CanFrame")
        if not callable(authorize_transmit):
            raise TypeError("An explicit transmit authorization callback is required")
        if frame.is_remote_frame or frame.is_error_frame:
            raise ValueError("Only CAN data frames can be transmitted")
        if not isinstance(frame.data, (bytes, bytearray, memoryview)):
            raise TypeError("CAN frame data must be bytes-like")
        data = bytes(frame.data)
        if not 1 <= len(data) <= 8:
            raise ValueError("Classic CAN data length must be between 1 and 8 bytes")
        limit = 0x1FFFFFFF if frame.is_extended_id else 0x7FF
        if (
            isinstance(frame.arbitration_id, bool)
            or not isinstance(frame.arbitration_id, int)
            or not 0 <= frame.arbitration_id <= limit
        ):
            raise ValueError("CAN arbitration ID is outside the selected identifier range")
        if timeout <= 0:
            raise ValueError("CAN send timeout must be positive")
        if authorize_transmit(frame) is not True:
            raise PermissionError("CAN transmission denied by caller policy")

        message = can.Message(
            arbitration_id=frame.arbitration_id,
            data=data,
            is_extended_id=bool(frame.is_extended_id),
            is_remote_frame=False,
            is_error_frame=False,
            check=True,
        )
        self.bus.send(message, timeout=float(timeout))
        return True

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
