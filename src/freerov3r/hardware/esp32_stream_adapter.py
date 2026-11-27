"""Receive-only PC transports for the versioned ESP32 device protocol.

USB serial and Wi-Fi TCP expose the same byte-stream contract. This adapter
only consumes FRAME_RX messages; it intentionally has no command/write path.
"""
from __future__ import annotations

import socket
import time

import serial

from .base import CanAdapter
from .device_protocol import MessageStreamDecoder, MessageType, decode_can_frame_payload
from ..models import CanFrame


class Esp32FramedStreamAdapter(CanAdapter):
    """Shared receive and decode logic for ESP32 byte-stream transports."""

    def __init__(self, *, channel_names=None, read_size=4096, transport_label="stream"):
        if isinstance(read_size, bool) or not isinstance(read_size, int) or read_size < 1:
            raise ValueError("read_size must be a positive integer")
        self.channel_names = dict(channel_names or {})
        self.read_size = read_size
        self.transport_label = str(transport_label)
        self.decoder = MessageStreamDecoder()
        self.frames_received = 0
        self.messages_received = 0
        self.ignored_messages = 0
        self.invalid_can_payloads = 0
        self.sequence_gaps = 0
        self.last_sequence = None
        self.last_error = None
        self.last_frame_monotonic = None
        self._pending_frames = []
        self._opened = False

    @property
    def connected(self):
        return self._opened

    @property
    def description(self):
        return f"FreeRov3r ESP32 framed {self.transport_label} (receive-only)"

    @property
    def diagnostics(self):
        age = (
            max(0.0, time.monotonic() - self.last_frame_monotonic)
            if self.last_frame_monotonic is not None else None
        )
        if not self.connected:
            state = "disconnected/error" if self.last_error else "disconnected"
        elif self.last_error:
            state = "connected/error"
        elif age is None or age > 2.5:
            state = "connected/silent"
        else:
            state = "receiving"
        return {
            "connected": self.connected,
            "receiver_state": state,
            "transport": self.transport_label,
            "frames_received": self.frames_received,
            "messages_received": self.messages_received,
            "ignored_messages": self.ignored_messages,
            "invalid_can_payloads": self.invalid_can_payloads,
            "sequence_gaps": self.sequence_gaps,
            "decoder_rejected_frames": self.decoder.frames_rejected,
            "decoder_bytes_discarded": self.decoder.bytes_discarded,
            "decoder_buffered_bytes": self.decoder.buffered_bytes,
            "last_frame_age_seconds": age,
            "last_error": self.last_error,
            "mode": "receive-only",
        }

    def open(self):
        if self._opened:
            return
        self.decoder = MessageStreamDecoder()
        self._pending_frames.clear()
        self.frames_received = self.messages_received = 0
        self.ignored_messages = self.invalid_can_payloads = 0
        self.sequence_gaps = 0
        self.last_sequence = self.last_frame_monotonic = None
        self.last_error = None
        self._open_transport()
        self._opened = True

    def _open_transport(self):
        raise NotImplementedError

    def _close_transport(self):
        raise NotImplementedError

    def close(self):
        try:
            self._close_transport()
        finally:
            self._opened = False
            self._pending_frames.clear()

    def _read(self, timeout):
        raise NotImplementedError

    def _decode_messages(self, chunk):
        frames = []
        for message in self.decoder.feed(chunk):
            self.messages_received += 1
            if self.last_sequence is not None:
                expected = (self.last_sequence + 1) & 0xFFFFFFFF
                if message.sequence != expected:
                    distance = (message.sequence - expected) & 0xFFFFFFFF
                    if distance < 0x80000000:
                        self.sequence_gaps += distance + 1
            self.last_sequence = message.sequence

            if message.version != 1 or message.message_type != MessageType.FRAME_RX:
                self.ignored_messages += 1
                continue
            try:
                item = decode_can_frame_payload(message.payload)
            except ValueError:
                self.invalid_can_payloads += 1
                continue
            if item.is_remote_frame:
                self.ignored_messages += 1
                continue

            channel = self.channel_names.get(item.channel, f"CAN{item.channel + 1}")
            frame = CanFrame(
                arbitration_id=item.arbitration_id,
                data=item.data,
                is_extended_id=item.is_extended_id,
                channel=channel,
                timestamp=time.monotonic(),
                device_timestamp_us=item.device_timestamp_us,
                timestamp_clock_domain="host_monotonic",
                timestamp_source=f"esp32_{self.transport_label}",
                device_timestamp_clock_domain=(
                    "device_uptime" if item.device_timestamp_us is not None else None
                ),
            )
            self.frames_received += 1
            self.last_frame_monotonic = frame.timestamp
            self.last_error = None
            frames.append(frame)
        return frames

    def receive(self, timeout=0.2):
        if not self._opened:
            raise RuntimeError("ESP32 framed adapter is not open")
        if self._pending_frames:
            return self._pending_frames.pop(0)

        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                chunk = self._read(remaining)
            except (OSError, serial.SerialException) as exc:
                self.last_error = str(exc)[:240]
                self._opened = False
                raise
            if chunk:
                self._pending_frames.extend(self._decode_messages(chunk))
                if self._pending_frames:
                    return self._pending_frames.pop(0)
            if time.monotonic() >= deadline:
                return None


class Esp32FramedSerialAdapter(Esp32FramedStreamAdapter):
    """USB CDC/UART transport for the versioned ESP32 protocol."""

    def __init__(self, port="COM3", baudrate=921600, timeout=0.1, *, channel_names=None):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.connection = None
        super().__init__(
            channel_names=channel_names,
            transport_label=f"USB serial {self.port}",
        )

    @property
    def connected(self):
        return self._opened and self.connection is not None and bool(
            getattr(self.connection, "is_open", True)
        )

    def _open_transport(self):
        self.connection = serial.Serial(
            self.port, self.baudrate, timeout=self.timeout
        )

    def _read(self, timeout):
        if self.connection is None:
            raise RuntimeError("ESP32 USB serial connection is not open")
        self.connection.timeout = min(self.timeout, timeout)
        return self.connection.read(self.read_size)

    def _close_transport(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None


class Esp32WifiAdapter(Esp32FramedStreamAdapter):
    """Direct Wi-Fi TCP connection to an ESP32 device endpoint."""

    def __init__(
        self,
        host,
        port=3333,
        *,
        connect_timeout=3.0,
        channel_names=None,
        read_size=4096,
    ):
        self.host = str(host)
        self.port = int(port)
        self.connect_timeout = float(connect_timeout)
        self.connection = None
        super().__init__(
            channel_names=channel_names,
            read_size=read_size,
            transport_label=f"Wi-Fi TCP {self.host}:{self.port}",
        )

    @property
    def connected(self):
        return self._opened and self.connection is not None

    def _open_transport(self):
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("A valid ESP32 Wi-Fi host and TCP port are required")
        self.connection = socket.create_connection(
            (self.host, self.port), timeout=self.connect_timeout
        )

    def _read(self, timeout):
        if self.connection is None:
            raise RuntimeError("ESP32 Wi-Fi connection is not open")
        self.connection.settimeout(max(0.001, timeout))
        try:
            chunk = self.connection.recv(self.read_size)
        except socket.timeout:
            return b""
        if not chunk:
            raise ConnectionError("ESP32 Wi-Fi device closed the connection")
        return chunk

    def _close_transport(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None
