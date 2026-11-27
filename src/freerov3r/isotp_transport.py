"""Active classic-CAN ISO-TP transport primitives.

This is a transport core, not an adapter or vehicle service. Callers must
supply CAN send/receive functions and an explicit per-frame transmit
authorization callback. No hardware is opened and no CAN frame is sent merely
by importing or constructing this module.

Initial scope: normal addressing, 11/29-bit CAN identifiers, classic CAN
frames up to 8 bytes, 12-bit ISO-TP payload lengths. CAN FD and extended
addressing are intentionally not implemented.
"""

import time

from .models import CanFrame


class IsoTpError(RuntimeError):
    """Base class for ISO-TP transport failures."""


class IsoTpTimeout(IsoTpError):
    """A required ISO-TP frame or flow-control response did not arrive."""


class IsoTpProtocolError(IsoTpError):
    """A received ISO-TP frame violates the supported transport format."""


class IsoTpTransport:
    """Blocking ISO-TP endpoint over injected CAN callbacks.

    The authorization callback is mandatory and is evaluated for every
    outgoing data and Flow Control frame.
    """

    def __init__(
        self,
        send_can_frame,
        receive_can_frame,
        authorize_transmit,
        *,
        tx_id,
        rx_id,
        extended_id=False,
        channel=None,
        block_size=0,
        st_min=0,
        padding=None,
        timeout=1.0,
        max_wait_frames=8,
        max_payload=4095,
    ):
        if not callable(send_can_frame) or not callable(receive_can_frame):
            raise TypeError("CAN send and receive callbacks are required")
        if not callable(authorize_transmit):
            raise TypeError("An explicit transmit authorization callback is required")
        limit = 0x1FFFFFFF if extended_id else 0x7FF
        for name, value in (("tx_id", tx_id), ("rx_id", rx_id)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
                raise ValueError(f"{name} is outside the selected CAN identifier range")
        if tx_id == rx_id:
            raise ValueError("ISO-TP transmit and receive IDs must be different")
        if isinstance(block_size, bool) or not isinstance(block_size, int) or not 0 <= block_size <= 0xFF:
            raise ValueError("block_size must be between 0 and 255")
        self._validate_st_min(st_min)
        if padding is not None and (
            isinstance(padding, bool) or not isinstance(padding, int) or not 0 <= padding <= 0xFF
        ):
            raise ValueError("padding must be None or one byte")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if isinstance(max_payload, bool) or not isinstance(max_payload, int) or not 1 <= max_payload <= 4095:
            raise ValueError("max_payload must be between 1 and 4095 bytes")
        if isinstance(max_wait_frames, bool) or not isinstance(max_wait_frames, int) or max_wait_frames < 0:
            raise ValueError("max_wait_frames must be non-negative")

        self._send_callback = send_can_frame
        self._receive_callback = receive_can_frame
        self._authorize_callback = authorize_transmit
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.extended_id = bool(extended_id)
        self.channel = channel
        self.block_size = block_size
        self.st_min = st_min
        self.padding = padding
        self.timeout = float(timeout)
        self.max_wait_frames = max_wait_frames
        self.max_payload = max_payload

    @staticmethod
    def _validate_st_min(value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("STmin must be an integer byte")
        if not (0 <= value <= 0x7F or 0xF1 <= value <= 0xF9):
            raise ValueError("Reserved or unsupported STmin encoding")

    @staticmethod
    def _st_min_seconds(value):
        IsoTpTransport._validate_st_min(value)
        return value / 1000.0 if value <= 0x7F else (value - 0xF0) / 10000.0

    def _frame(self, arbitration_id, payload):
        data = bytes(payload)
        if not data or len(data) > 8:
            raise IsoTpProtocolError("Classic CAN ISO-TP frame must contain 1 to 8 bytes")
        if self.padding is not None and len(data) < 8:
            data += bytes((self.padding,)) * (8 - len(data))
        return CanFrame(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=self.extended_id,
            channel=self.channel,
        )

    def _send(self, arbitration_id, payload):
        frame = self._frame(arbitration_id, payload)
        if self._authorize_callback(frame) is not True:
            raise PermissionError("ISO-TP CAN transmission denied by caller policy")
        self._send_callback(frame)

    def _receive_matching(self, expected_id, timeout):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IsoTpTimeout("Timed out waiting for ISO-TP frame")
            frame = self._receive_callback(timeout=remaining)
            if frame is None:
                raise IsoTpTimeout("Timed out waiting for ISO-TP frame")
            if frame.is_remote_frame or frame.is_error_frame:
                continue
            if frame.arbitration_id != expected_id:
                continue
            if bool(frame.is_extended_id) != self.extended_id:
                continue
            if self.channel is not None and frame.channel != self.channel:
                continue
            data = bytes(frame.data)
            if not data:
                continue
            if len(data) > 8:
                raise IsoTpProtocolError("CAN FD frame received by classic-CAN ISO-TP endpoint")
            return frame

    def _wait_flow_control(self):
        wait_count = 0
        while True:
            frame = self._receive_matching(self.rx_id, self.timeout)
            data = bytes(frame.data)
            if data[0] >> 4 != 3 or len(data) < 3:
                continue
            status = data[0] & 0x0F
            if status == 0:
                st_min = data[2]
                self._validate_st_min(st_min)
                return data[1], self._st_min_seconds(st_min)
            if status == 1:
                wait_count += 1
                if wait_count > self.max_wait_frames:
                    raise IsoTpProtocolError("Exceeded configured ISO-TP Flow Control WAIT limit")
                continue
            if status == 2:
                raise IsoTpProtocolError("Receiver rejected ISO-TP transfer with OVERFLOW")
            raise IsoTpProtocolError(f"Reserved Flow Control status 0x{status:X}")

    def send_payload(self, payload):
        """Transmit one ISO-TP payload, waiting for receiver Flow Control."""
        payload = bytes(payload)
        if not payload:
            raise ValueError("ISO-TP payload cannot be empty")
        if len(payload) > self.max_payload:
            raise ValueError("Payload exceeds configured ISO-TP limit")
        if len(payload) <= 7:
            self._send(self.tx_id, bytes((len(payload),)) + payload)
            return {"payload_bytes": len(payload), "frames_sent": 1}

        first = bytes((0x10 | ((len(payload) >> 8) & 0x0F), len(payload) & 0xFF))
        self._send(self.tx_id, first + payload[:6])
        offset = 6
        sequence = 1
        frames_sent = 1
        block_count = 0
        block_size, separation = self._wait_flow_control()

        while offset < len(payload):
            if block_size and block_count >= block_size:
                block_size, separation = self._wait_flow_control()
                block_count = 0
            if separation:
                time.sleep(separation)
            chunk = payload[offset:offset + 7]
            self._send(self.tx_id, bytes((0x20 | sequence,)) + chunk)
            offset += len(chunk)
            sequence = (sequence + 1) & 0x0F
            frames_sent += 1
            block_count += 1
        return {"payload_bytes": len(payload), "frames_sent": frames_sent}

    def receive_payload(self, timeout=None):
        """Receive one ISO-TP payload within one overall response deadline.

        The optional timeout bounds the complete ISO-TP payload, including all
        Consecutive Frames, rather than restarting the timeout for each frame.
        """
        response_timeout = self.timeout if timeout is None else float(timeout)
        if response_timeout <= 0:
            raise ValueError("receive timeout must be positive")
        deadline = time.monotonic() + response_timeout

        def receive_next():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IsoTpTimeout("Timed out waiting for complete ISO-TP payload")
            return self._receive_matching(self.rx_id, remaining)

        frame = receive_next()
        data = bytes(frame.data)
        pci_type = data[0] >> 4

        if pci_type == 0:
            length = data[0] & 0x0F
            if length == 0 or length > 7 or len(data) < length + 1:
                raise IsoTpProtocolError("Invalid or truncated classic-CAN Single Frame")
            return data[1:1 + length]

        if pci_type != 1 or len(data) < 2:
            raise IsoTpProtocolError("Expected ISO-TP Single Frame or First Frame")

        expected_length = ((data[0] & 0x0F) << 8) | data[1]
        if expected_length <= 7 or expected_length > self.max_payload:
            raise IsoTpProtocolError("Invalid or unsupported First Frame payload length")
        result = bytearray(data[2:])
        self._send(self.tx_id, bytes((0x30, self.block_size, self.st_min)))
        expected_sequence = 1
        block_count = 0

        while len(result) < expected_length:
            next_frame = receive_next()
            chunk = bytes(next_frame.data)
            if chunk[0] >> 4 != 2:
                raise IsoTpProtocolError("Expected Consecutive Frame during segmented transfer")
            sequence = chunk[0] & 0x0F
            if sequence != expected_sequence:
                raise IsoTpProtocolError(
                    f"Consecutive Frame sequence mismatch: expected {expected_sequence:X}, got {sequence:X}"
                )
            result.extend(chunk[1:])
            expected_sequence = (expected_sequence + 1) & 0x0F
            block_count += 1
            if self.block_size and block_count >= self.block_size and len(result) < expected_length:
                self._send(self.tx_id, bytes((0x30, self.block_size, self.st_min)))
                block_count = 0

        return bytes(result[:expected_length])
