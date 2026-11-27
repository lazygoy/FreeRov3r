"""ISO 22900-2 D-PDU API runtime for passive MVCI module inventory.

This runtime loads only an explicitly selected D-PDU API library. It calls
PDUConstruct (which initializes the API and discovers modules without
allocating vehicle communication resources), PDUGetModuleIds, and
PDUDestroyItem. It never connects a module, creates a logical link, or sends
vehicle traffic.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from typing import Callable

from .dpdu_discovery import DPduModuleRegistration


PDU_STATUS_NOERROR = 0
MAX_MODULES = 256
MAX_RESOURCE_GROUPS = 256
MAX_RESOURCE_IDS = 4096
MAX_VENDOR_TEXT = 4096


class _PduItem(ctypes.Structure):
    _fields_ = [("item_type", ctypes.c_int32)]


class _PduModuleData(ctypes.Structure):
    _fields_ = [
        ("module_type_id", ctypes.c_uint32),
        ("module_handle", ctypes.c_uint32),
        ("vendor_module_name", ctypes.c_char_p),
        ("vendor_additional_info", ctypes.c_char_p),
        ("module_status", ctypes.c_int32),
    ]


class _PduModuleItem(ctypes.Structure):
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_entries", ctypes.c_uint32),
        ("module_data", ctypes.POINTER(_PduModuleData)),
    ]


class _PduPinData(ctypes.Structure):
    _fields_ = [
        ("dlc_pin_number", ctypes.c_uint32),
        ("dlc_pin_type_id", ctypes.c_uint32),
    ]


class _PduResourceData(ctypes.Structure):
    _fields_ = [
        ("bus_type_id", ctypes.c_uint32),
        ("protocol_id", ctypes.c_uint32),
        ("num_pin_data", ctypes.c_uint32),
        ("dlc_pin_data", ctypes.POINTER(_PduPinData)),
    ]


class _PduResourceIdItemData(ctypes.Structure):
    _fields_ = [
        ("module_handle", ctypes.c_uint32),
        ("num_ids", ctypes.c_uint32),
        ("resource_ids", ctypes.POINTER(ctypes.c_uint32)),
    ]


class _PduResourceIdItem(ctypes.Structure):
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_modules", ctypes.c_uint32),
        ("resource_id_data", ctypes.POINTER(_PduResourceIdItemData)),
    ]


@dataclass(frozen=True)
class DPduResourceIdSet:
    module_handle: int
    resource_ids: tuple[int, ...]


@dataclass(frozen=True)
class DPduLiveModule:
    """One live module interface reported by PDUGetModuleIds."""

    registration_name: str
    library_file: str
    module_type_id: int
    module_handle: int
    module_status: int
    vendor_module_name: str = ""
    vendor_additional_info: str = ""


class DPduApiError(RuntimeError):
    """A D-PDU API loading, initialization, or enumeration error."""


def _default_library_loader(path: str):
    if os.name == "nt":
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise DPduApiError("Windows stdcall loader is unavailable")
        return loader(path)
    return ctypes.CDLL(path)


def _set_signature(function, argtypes, restype) -> None:
    # Python test doubles do not expose ctypes function attributes.
    try:
        function.argtypes = argtypes
        function.restype = restype
    except (AttributeError, TypeError):
        pass


def _decode_vendor_text(value: bytes | None) -> str:
    if not value:
        return ""
    # Vendor strings are NUL-terminated CHAR8 (Latin-1) per ISO 22900-2.
    return bytes(value[:MAX_VENDOR_TEXT]).decode("latin-1", errors="replace").strip()


class DPduApiRuntime:
    """Explicit, read-only D-PDU runtime session for live module inventory."""

    def __init__(
        self,
        registration: DPduModuleRegistration,
        *,
        library_loader: Callable[[str], object] | None = None,
        option_string: bytes | None = None,
    ) -> None:
        if not registration.library_file:
            raise ValueError("D-PDU registration has no library path")
        self.registration = registration
        self._library_loader = library_loader or _default_library_loader
        self._option_string = option_string
        self._library = None
        self._constructed = False
        self._pdu_construct = None
        self._pdu_destruct = None
        self._pdu_get_module_ids = None
        self._pdu_destroy_item = None
        self._pdu_get_resource_ids = None

    @property
    def is_open(self) -> bool:
        return self._constructed

    def open(self) -> list[DPduLiveModule]:
        """Load the selected API and enumerate modules without vehicle I/O."""
        if self._constructed:
            raise RuntimeError("D-PDU API session is already open")

        try:
            self._library = self._library_loader(self.registration.library_file)
            self._bind_functions()
            option = self._option_string
            if option is not None and not isinstance(option, bytes):
                raise TypeError("D-PDU option_string must be bytes or None")
            status = int(self._pdu_construct(option, None))
            if status != PDU_STATUS_NOERROR:
                raise DPduApiError(f"PDUConstruct failed with status 0x{status:08X}")
            self._constructed = True
            return self.enumerate_modules()
        except Exception:
            self.close()
            raise

    def _bind_functions(self) -> None:
        try:
            self._pdu_construct = self._library.PDUConstruct
            self._pdu_destruct = self._library.PDUDestruct
            self._pdu_get_module_ids = self._library.PDUGetModuleIds
            self._pdu_destroy_item = self._library.PDUDestroyItem
        except AttributeError as exc:
            raise DPduApiError(
                f"Selected D-PDU library is missing required export: {exc}"
            ) from exc

        char_ptr = ctypes.c_char_p
        void_ptr = ctypes.c_void_p
        module_item_ptr = ctypes.POINTER(_PduModuleItem)
        _set_signature(self._pdu_construct, [char_ptr, void_ptr], ctypes.c_int32)
        _set_signature(self._pdu_destruct, [], ctypes.c_int32)
        _set_signature(
            self._pdu_get_module_ids,
            [ctypes.POINTER(module_item_ptr)],
            ctypes.c_int32,
        )
        _set_signature(
            self._pdu_destroy_item,
            [ctypes.POINTER(_PduItem)],
            ctypes.c_int32,
        )
        self._pdu_get_resource_ids = getattr(
            self._library, "PDUGetResourceIds", None
        )
        if self._pdu_get_resource_ids is not None:
            _set_signature(
                self._pdu_get_resource_ids,
                [
                    ctypes.c_uint32,
                    ctypes.POINTER(_PduResourceData),
                    ctypes.POINTER(ctypes.POINTER(_PduResourceIdItem)),
                ],
                ctypes.c_int32,
            )

    def enumerate_modules(self) -> list[DPduLiveModule]:
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")

        item_ptr = ctypes.POINTER(_PduModuleItem)()
        status = int(self._pdu_get_module_ids(ctypes.byref(item_ptr)))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUGetModuleIds failed with status 0x{status:08X}"
            )
        if not item_ptr:
            raise DPduApiError("PDUGetModuleIds succeeded but returned a null item")

        try:
            item = item_ptr.contents
            count = int(item.num_entries)
            if count < 0 or count > MAX_MODULES:
                raise DPduApiError(
                    f"PDUGetModuleIds returned invalid module count: {count}"
                )
            if count and not item.module_data:
                raise DPduApiError(
                    "PDUGetModuleIds returned entries with a null module array"
                )

            modules: list[DPduLiveModule] = []
            for index in range(count):
                record = item.module_data[index]
                modules.append(DPduLiveModule(
                    registration_name=self.registration.short_name,
                    library_file=self.registration.library_file,
                    module_type_id=int(record.module_type_id),
                    module_handle=int(record.module_handle),
                    module_status=int(record.module_status),
                    vendor_module_name=_decode_vendor_text(record.vendor_module_name),
                    vendor_additional_info=_decode_vendor_text(
                        record.vendor_additional_info
                    ),
                ))
            return modules
        finally:
            destroy_status = int(self._pdu_destroy_item(
                ctypes.cast(item_ptr, ctypes.POINTER(_PduItem))
            ))
            if destroy_status != PDU_STATUS_NOERROR:
                # Do not mask a successful inventory with a cleanup failure;
                # make the leak/driver fault visible to the caller.
                raise DPduApiError(
                    f"PDUDestroyItem failed with status 0x{destroy_status:08X}"
                )

    def enumerate_resource_ids(
        self,
        module_handle: int,
        bus_type_id: int,
        protocol_id: int,
        dlc_pins: tuple[tuple[int, int], ...] | list[tuple[int, int]],
    ) -> list[DPduResourceIdSet]:
        """Query matching resources using MDF/CDF IDs, without connecting a module."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        if self._pdu_get_resource_ids is None:
            raise DPduApiError("Selected D-PDU library does not export PDUGetResourceIds")
        for value, name in (
            (module_handle, "module_handle"),
            (bus_type_id, "bus_type_id"),
            (protocol_id, "protocol_id"),
        ):
            if not 0 <= int(value) <= 0xFFFFFFFF:
                raise ValueError(f"{name} must be an unsigned 32-bit value")
        if not dlc_pins or len(dlc_pins) > 64:
            raise ValueError("dlc_pins must contain between 1 and 64 entries")

        pin_array = (_PduPinData * len(dlc_pins))()
        for index, (pin_number, pin_type_id) in enumerate(dlc_pins):
            if not 0 <= int(pin_number) <= 0xFFFFFFFF:
                raise ValueError("DLC pin number must be an unsigned 32-bit value")
            if not 0 <= int(pin_type_id) <= 0xFFFFFFFF:
                raise ValueError("DLC pin type ID must be an unsigned 32-bit value")
            pin_array[index] = _PduPinData(int(pin_number), int(pin_type_id))

        request = _PduResourceData(
            int(bus_type_id), int(protocol_id), len(dlc_pins),
            ctypes.cast(pin_array, ctypes.POINTER(_PduPinData)),
        )
        result_ptr = ctypes.POINTER(_PduResourceIdItem)()
        status = int(self._pdu_get_resource_ids(
            int(module_handle), ctypes.byref(request), ctypes.byref(result_ptr)
        ))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUGetResourceIds failed with status 0x{status:08X}")
        if not result_ptr:
            raise DPduApiError("PDUGetResourceIds succeeded but returned a null item")

        try:
            result = result_ptr.contents
            group_count = int(result.num_modules)
            if group_count > MAX_RESOURCE_GROUPS:
                raise DPduApiError(f"Invalid resource result group count: {group_count}")
            if group_count and not result.resource_id_data:
                raise DPduApiError("Resource result has a null group array")
            matches: list[DPduResourceIdSet] = []
            total_ids = 0
            for index in range(group_count):
                group = result.resource_id_data[index]
                count = int(group.num_ids)
                total_ids += count
                if count > MAX_RESOURCE_IDS or total_ids > MAX_RESOURCE_IDS:
                    raise DPduApiError("PDUGetResourceIds returned too many resource IDs")
                if count and not group.resource_ids:
                    raise DPduApiError("Resource group has a null resource ID array")
                ids = tuple(int(group.resource_ids[i]) for i in range(count))
                matches.append(DPduResourceIdSet(int(group.module_handle), ids))
            return matches
        finally:
            destroy_status = int(self._pdu_destroy_item(
                ctypes.cast(result_ptr, ctypes.POINTER(_PduItem))
            ))
            if destroy_status != PDU_STATUS_NOERROR:
                raise DPduApiError(
                    f"PDUDestroyItem failed after resource query with status 0x{destroy_status:08X}"
                )

    def close(self) -> None:
        """Destroy the API session and release the selected library handle."""
        errors: list[str] = []
        if self._constructed and self._pdu_destruct is not None:
            try:
                status = int(self._pdu_destruct())
                if status != PDU_STATUS_NOERROR:
                    errors.append(f"PDUDestruct status 0x{status:08X}")
            except Exception as exc:  # vendor DLL boundary
                errors.append(f"PDUDestruct raised {exc}")
        self._constructed = False
        self._pdu_construct = None
        self._pdu_destruct = None
        self._pdu_get_module_ids = None
        self._pdu_destroy_item = None
        self._pdu_get_resource_ids = None
        self._library = None
        if errors:
            raise DPduApiError("; ".join(errors))

    def __enter__(self) -> "DPduApiRuntime":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
