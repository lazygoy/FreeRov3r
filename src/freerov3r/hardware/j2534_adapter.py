"""Minimal, receive-only SAE J2534 Pass-Thru runtime.

This module implements the classic-CAN receive path only. It deliberately
contains no PassThruWriteMsgs binding. A vendor DLL is loaded only when an
operator explicitly constructs and opens this adapter on Windows.

The J2534 ABI uses 32-bit DWORD/ULONG fields even in 64-bit Windows processes.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import POINTER, byref, c_char, c_uint8, c_uint32, c_void_p
from dataclasses import dataclass
from typing import Callable

from ..models import CanFrame
from .base import CanAdapter
from .j2534_discovery import J2534DeviceRegistration


# J2534 protocol and status constants.
J2534_STATUS_NOERROR = 0x00
J2534_ERR_BUFFER_EMPTY = 0x10
J2534_PROTOCOL_CAN = 0x05
J2534_CAN_29BIT_ID = 0x00000100
J2534_MAX_DATA = 4128
J2534_CAN_ID_BYTES = 4


class PassThruError(RuntimeError):
    """A J2534 driver operation failed."""

    def __init__(self, operation: str, status: int, detail: str = ""):
        self.operation = operation
        self.status = int(status)
        self.detail = detail
        message = f"{operation} failed with J2534 status 0x{status:02X}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class PassThruUnavailable(RuntimeError):
    """J2534 is unavailable on this platform or the driver cannot be loaded."""


class PassThruMessage(ctypes.Structure):
    """SAE J2534 PASSTHRU_MSG layout (DWORD fields and 4128-byte data)."""

    _fields_ = [
        ("ProtocolID", c_uint32),
        ("RxStatus", c_uint32),
        ("TxFlags", c_uint32),
        ("Timestamp", c_uint32),
        ("DataSize", c_uint32),
        ("ExtraDataIndex", c_uint32),
        ("Data", c_uint8 * J2534_MAX_DATA),
    ]


@dataclass(frozen=True)
class J2534Connection:
    protocol_id: int = J2534_PROTOCOL_CAN
    baudrate: int = 500_000
    flags: int = 0
    channel_name: str = "J2534 CAN"


def _load_vendor_library(path: str):
    """Load a vendor DLL using the Windows stdcall loader."""
    if os.name != "nt":
        raise PassThruUnavailable("J2534 vendor DLLs can only be loaded on Windows")
    if not path or not os.path.isfile(path):
        raise PassThruUnavailable(f"J2534 FunctionLibrary DLL not found: {path!r}")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise PassThruUnavailable("Windows stdcall DLL loading is unavailable")
    try:
        return loader(path)
    except OSError as exc:
        raise PassThruUnavailable(f"Unable to load J2534 driver DLL: {exc}") from exc


def _bind_function(library, name: str, argtypes: list):
    """Bind a required vendor entry point with the J2534 ABI signature."""
    try:
        function = getattr(library, name)
    except AttributeError as exc:
        raise PassThruUnavailable(f"J2534 driver is missing required export {name}") from exc
    # ctypes functions expose argtypes/restype. Simple injected test doubles
    # need not, which keeps the ABI wrapper testable without a vendor DLL.
    if hasattr(function, "argtypes"):
        function.argtypes = argtypes
        function.restype = c_uint32
    return function


class J2534CanAdapter(CanAdapter):
    """Receive-only classic-CAN adapter backed by an installed J2534 DLL.

    Opening explicitly loads the selected vendor DLL, opens the Pass-Thru
    device, and connects one CAN channel. receive() returns one CAN frame.
    There is intentionally no public transmit method in this first runtime.
    """

    def __init__(
        self,
        registration: J2534DeviceRegistration,
        connection: J2534Connection | None = None,
        *,
        library_loader: Callable[[str], object] = _load_vendor_library,
    ):
        if not isinstance(registration, J2534DeviceRegistration):
            raise TypeError("registration must be a J2534DeviceRegistration")
        self.registration = registration
        self.connection = connection or J2534Connection()
        if self.connection.protocol_id != J2534_PROTOCOL_CAN:
            raise ValueError("This initial adapter supports classic CAN only")
        if self.connection.baudrate <= 0:
            raise ValueError("CAN baudrate must be positive")
        self._library_loader = library_loader
        self._library = None
        self._device_id = c_uint32(0)
        self._channel_id = c_uint32(0)
        self._opened = False
        self._connected = False
        self._functions = {}

    @property
    def description(self) -> str:
        return (
            f"{self.registration.name} "
            f"(J2534 {self.registration.api_version}, CAN receive-only)"
        )

    @property
    def is_open(self) -> bool:
        return self._opened and self._connected

    def _status(self, operation: str, status: int) -> None:
        if int(status) != J2534_STATUS_NOERROR:
            detail = ""
            get_last_error = self._functions.get("PassThruGetLastError")
            if get_last_error is not None:
                buffer = ctypes.create_string_buffer(80)
                try:
                    error_status = get_last_error(buffer)
                    if error_status == J2534_STATUS_NOERROR:
                        detail = buffer.value.decode("ascii", errors="replace")
                except Exception:
                    # Preserve the original driver status if optional error
                    # retrieval itself fails.
                    detail = ""
            raise PassThruError(operation, int(status), detail)

    def open(self) -> None:
        if self.is_open:
            return
        library = self._library_loader(self.registration.function_library)
        self._library = library
        self._functions = {
            "PassThruOpen": _bind_function(
                library, "PassThruOpen", [c_void_p, POINTER(c_uint32)]
            ),
            "PassThruClose": _bind_function(
                library, "PassThruClose", [c_uint32]
            ),
            "PassThruConnect": _bind_function(
                library, "PassThruConnect",
                [c_uint32, c_uint32, c_uint32, c_uint32, POINTER(c_uint32)],
            ),
            "PassThruDisconnect": _bind_function(
                library, "PassThruDisconnect", [c_uint32]
            ),
            "PassThruReadMsgs": _bind_function(
                library, "PassThruReadMsgs",
                [c_uint32, POINTER(PassThruMessage), POINTER(c_uint32), c_uint32],
            ),
        }
        optional_error = getattr(library, "PassThruGetLastError", None)
        if optional_error is not None:
            if hasattr(optional_error, "argtypes"):
                optional_error.argtypes = [ctypes.c_char_p]
                optional_error.restype = c_uint32
            self._functions["PassThruGetLastError"] = optional_error

        try:
            status = self._functions["PassThruOpen"](
                None, byref(self._device_id)
            )
            self._status("PassThruOpen", status)
            self._opened = True

            status = self._functions["PassThruConnect"](
                self._device_id.value,
                self.connection.protocol_id,
                self.connection.flags,
                self.connection.baudrate,
                byref(self._channel_id),
            )
            self._status("PassThruConnect", status)
            self._connected = True
        except Exception:
            self.close()
            raise

    def receive(self, timeout: float = 0.2) -> CanFrame | None:
        if not self.is_open:
            raise RuntimeError("J2534 adapter is not open")
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        timeout_ms = min(0xFFFFFFFF, max(0, round(timeout * 1000)))
        message = PassThruMessage()
        count = c_uint32(1)
        status = self._functions["PassThruReadMsgs"](
            self._channel_id.value,
            byref(message),
            byref(count),
            timeout_ms,
        )
        if int(status) == J2534_ERR_BUFFER_EMPTY:
            return None
        self._status("PassThruReadMsgs", status)
        if count.value == 0:
            return None
        if count.value != 1:
            raise PassThruError(
                "PassThruReadMsgs",
                J2534_STATUS_NOERROR,
                f"driver returned unexpected message count {count.value}",
            )
        if message.DataSize < J2534_CAN_ID_BYTES or message.DataSize > J2534_MAX_DATA:
            raise PassThruError(
                "PassThruReadMsgs",
                J2534_STATUS_NOERROR,
                f"invalid J2534 CAN DataSize {message.DataSize}",
            )

        raw = bytes(message.Data[:message.DataSize])
        arbitration_id = int.from_bytes(raw[:J2534_CAN_ID_BYTES], "big")
        is_extended = bool(message.RxStatus & J2534_CAN_29BIT_ID)
        if not is_extended and arbitration_id > 0x7FF:
            raise PassThruError(
                "PassThruReadMsgs",
                J2534_STATUS_NOERROR,
                f"11-bit CAN identifier out of range: 0x{arbitration_id:X}",
            )
        if is_extended and arbitration_id > 0x1FFFFFFF:
            raise PassThruError(
                "PassThruReadMsgs",
                J2534_STATUS_NOERROR,
                f"29-bit CAN identifier out of range: 0x{arbitration_id:X}",
            )

        return CanFrame(
            arbitration_id=arbitration_id,
            data=raw[J2534_CAN_ID_BYTES:],
            is_extended_id=is_extended,
            channel=self.connection.channel_name,
            device_timestamp_us=int(message.Timestamp) * 1000,
            timestamp_clock_domain="j2534_device",
            timestamp_source="j2534",
            device_timestamp_clock_domain="j2534_device",
        )

    def close(self) -> None:
        errors = []
        if self._connected:
            try:
                status = self._functions["PassThruDisconnect"](
                    self._channel_id.value
                )
                if int(status) != J2534_STATUS_NOERROR:
                    errors.append(PassThruError("PassThruDisconnect", status))
            except Exception as exc:
                errors.append(exc)
            finally:
                self._connected = False

        if self._opened:
            try:
                status = self._functions["PassThruClose"](self._device_id.value)
                if int(status) != J2534_STATUS_NOERROR:
                    errors.append(PassThruError("PassThruClose", status))
            except Exception as exc:
                errors.append(exc)
            finally:
                self._opened = False

        self._library = None
        self._functions = {}
        if errors:
            raise errors[0]

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
