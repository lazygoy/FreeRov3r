"""ISO 22900-2 D-PDU API runtime for passive MVCI module inventory.

This runtime loads only an explicitly selected D-PDU API library. All module,
logical-link, parameter, and physical-connection operations are explicit.
Physical connection is never initiated by open(), enumeration, or link
creation. No ComPrimitive or diagnostic transmit path is exposed.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from typing import Callable

from .dpdu_discovery import DPduModuleRegistration


PDU_STATUS_NOERROR = 0
PDU_PT_UNUM32 = 0x00000105
PDU_IT_RSC_STATUS = 0x1100
PDU_IT_RSC_CONFLICT = 0x1500
PDU_IT_MODULE_ID = 0x1600
MAX_MODULES = 256
MAX_RESOURCE_GROUPS = 256
MAX_RESOURCE_IDS = 4096
MAX_VENDOR_TEXT = 4096


class _PduItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("item_type", ctypes.c_int32)]


class _PduModuleData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("module_type_id", ctypes.c_uint32),
        ("module_handle", ctypes.c_uint32),
        ("vendor_module_name", ctypes.c_char_p),
        ("vendor_additional_info", ctypes.c_char_p),
        ("module_status", ctypes.c_int32),
    ]


class _PduModuleItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_entries", ctypes.c_uint32),
        ("module_data", ctypes.POINTER(_PduModuleData)),
    ]


class _PduPinData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dlc_pin_number", ctypes.c_uint32),
        ("dlc_pin_type_id", ctypes.c_uint32),
    ]


class _PduResourceData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bus_type_id", ctypes.c_uint32),
        ("protocol_id", ctypes.c_uint32),
        ("num_pin_data", ctypes.c_uint32),
        ("dlc_pin_data", ctypes.POINTER(_PduPinData)),
    ]


class _PduResourceIdItemData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("module_handle", ctypes.c_uint32),
        ("num_ids", ctypes.c_uint32),
        ("resource_ids", ctypes.POINTER(ctypes.c_uint32)),
    ]


class _PduResourceIdItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_modules", ctypes.c_uint32),
        ("resource_id_data", ctypes.POINTER(_PduResourceIdItemData)),
    ]


class _PduResourceStatusData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("module_handle", ctypes.c_uint32),
        ("resource_id", ctypes.c_uint32),
        ("resource_status", ctypes.c_uint32),
    ]


class _PduResourceStatusItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_entries", ctypes.c_uint32),
        ("resource_status_data", ctypes.POINTER(_PduResourceStatusData)),
    ]


class _PduFlagData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("num_flag_bytes", ctypes.c_uint32),
        ("flag_data", ctypes.POINTER(ctypes.c_uint8)),
    ]


class _PduParamItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("com_param_id", ctypes.c_uint32),
        ("data_type", ctypes.c_int32),
        ("param_class", ctypes.c_int32),
        ("data", ctypes.c_void_p),
    ]


class _PduResourceConflictData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("module_handle", ctypes.c_uint32),
        ("resource_id", ctypes.c_uint32),
    ]


class _PduResourceConflictItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("num_entries", ctypes.c_uint32),
        ("resource_conflict_data", ctypes.POINTER(_PduResourceConflictData)),
    ]


@dataclass(frozen=True)
class DPduResourceStatus:
    module_handle: int
    resource_id: int
    raw_status: int


@dataclass(frozen=True)
class DPduResourceConflict:
    module_handle: int
    resource_id: int


@dataclass(frozen=True)
class DPduComLogicalLink:
    module_handle: int
    logical_link_handle: int
    resource_id: int
    state: str = "offline"

    @property
    def initial_state(self) -> str:
        """Compatibility alias for callers that display the creation state."""
        return "offline"


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
        self._pdu_get_resource_status = None
        self._pdu_get_conflicting_resources = None
        self._pdu_module_connect = None
        self._pdu_module_disconnect = None
        self._pdu_create_logical_link = None
        self._pdu_destroy_logical_link = None
        self._pdu_connect = None
        self._pdu_disconnect = None
        self._pdu_get_com_param = None
        self._pdu_set_com_param = None
        self._live_modules: list[DPduLiveModule] = []
        self._connected_modules: set[int] = set()
        self._logical_links: dict[tuple[int, int], DPduComLogicalLink] = {}

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
        self._pdu_get_resource_status = getattr(
            self._library, "PDUGetResourceStatus", None
        )
        if self._pdu_get_resource_status is not None:
            _set_signature(
                self._pdu_get_resource_status,
                [ctypes.POINTER(_PduResourceStatusItem)],
                ctypes.c_int32,
            )
        self._pdu_get_conflicting_resources = getattr(
            self._library, "PDUGetConflictingResources", None
        )
        if self._pdu_get_conflicting_resources is not None:
            _set_signature(
                self._pdu_get_conflicting_resources,
                [
                    ctypes.c_uint32,
                    ctypes.POINTER(_PduModuleItem),
                    ctypes.POINTER(ctypes.POINTER(_PduResourceConflictItem)),
                ],
                ctypes.c_int32,
            )
        self._pdu_module_connect = getattr(self._library, "PDUModuleConnect", None)
        if self._pdu_module_connect is not None:
            _set_signature(self._pdu_module_connect, [ctypes.c_uint32], ctypes.c_int32)
        self._pdu_module_disconnect = getattr(self._library, "PDUModuleDisconnect", None)
        if self._pdu_module_disconnect is not None:
            _set_signature(self._pdu_module_disconnect, [ctypes.c_uint32], ctypes.c_int32)
        self._pdu_create_logical_link = getattr(
            self._library, "PDUCreateComLogicalLink", None
        )
        if self._pdu_create_logical_link is not None:
            _set_signature(
                self._pdu_create_logical_link,
                [
                    ctypes.c_uint32,
                    ctypes.POINTER(_PduResourceData),
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_uint32),
                    ctypes.POINTER(_PduFlagData),
                ],
                ctypes.c_int32,
            )
        self._pdu_destroy_logical_link = getattr(
            self._library, "PDUDestroyComLogicalLink", None
        )
        if self._pdu_destroy_logical_link is not None:
            _set_signature(
                self._pdu_destroy_logical_link,
                [ctypes.c_uint32, ctypes.c_uint32],
                ctypes.c_int32,
            )
        self._pdu_connect = getattr(self._library, "PDUConnect", None)
        if self._pdu_connect is not None:
            _set_signature(
                self._pdu_connect, [ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int32
            )
        self._pdu_disconnect = getattr(self._library, "PDUDisconnect", None)
        if self._pdu_disconnect is not None:
            _set_signature(
                self._pdu_disconnect, [ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int32
            )
        self._pdu_get_com_param = getattr(self._library, "PDUGetComParam", None)
        if self._pdu_get_com_param is not None:
            _set_signature(
                self._pdu_get_com_param,
                [
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(ctypes.POINTER(_PduParamItem)),
                ],
                ctypes.c_int32,
            )
        self._pdu_set_com_param = getattr(self._library, "PDUSetComParam", None)
        if self._pdu_set_com_param is not None:
            _set_signature(
                self._pdu_set_com_param,
                [
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(_PduParamItem),
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
            self._live_modules = modules
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
        for value, name in (
            (module_handle, "module_handle"),
            (bus_type_id, "bus_type_id"),
            (protocol_id, "protocol_id"),
        ):
            if not 0 <= int(value) <= 0xFFFFFFFF:
                raise ValueError(f"{name} must be an unsigned 32-bit value")
        if not dlc_pins or len(dlc_pins) > 64:
            raise ValueError("dlc_pins must contain between 1 and 64 entries")
        if self._pdu_get_resource_ids is None:
            raise DPduApiError("Selected D-PDU library does not export PDUGetResourceIds")

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

    def connect_module(self, module_handle: int) -> None:
        """Explicitly initialize one MVCI module; this remains offline from the vehicle."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        if self._pdu_module_connect is None:
            raise DPduApiError("Selected D-PDU library does not export PDUModuleConnect")
        handle = int(module_handle)
        if handle not in {module.module_handle for module in self._live_modules}:
            raise ValueError(f"Unknown MVCI module handle: {handle}")
        if handle in self._connected_modules:
            return
        status = int(self._pdu_module_connect(handle))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUModuleConnect failed with status 0x{status:08X}")
        self._connected_modules.add(handle)

    def disconnect_module(self, module_handle: int) -> None:
        """Disconnect an explicitly initialized MVCI module without vehicle-bus I/O."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        handle = int(module_handle)
        if handle not in self._connected_modules:
            return
        if any(key[0] == handle for key in self._logical_links):
            raise RuntimeError("Destroy all ComLogicalLinks before disconnecting the MVCI module")
        if self._pdu_module_disconnect is None:
            raise DPduApiError("Selected D-PDU library does not export PDUModuleDisconnect")
        status = int(self._pdu_module_disconnect(handle))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUModuleDisconnect failed with status 0x{status:08X}")
        self._connected_modules.discard(handle)

    def get_resource_status(
        self,
        module_handle: int,
        resource_ids: tuple[int, ...] | list[int],
    ) -> list[DPduResourceStatus]:
        """Read resource status from the constructed API resource table.

        This query does not require module connection or vehicle-bus access.
        """
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        handle = int(module_handle)
        if handle not in {module.module_handle for module in self._live_modules}:
            raise ValueError(f"Unknown MVCI module handle: {handle}")
        if self._pdu_get_resource_status is None:
            raise DPduApiError("Selected D-PDU library does not export PDUGetResourceStatus")
        if not resource_ids or len(resource_ids) > MAX_RESOURCE_IDS:
            raise ValueError(f"resource_ids must contain between 1 and {MAX_RESOURCE_IDS} entries")
        records = (_PduResourceStatusData * len(resource_ids))()
        for index, resource_id in enumerate(resource_ids):
            value = int(resource_id)
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("resource IDs must be unsigned 32-bit values")
            records[index] = _PduResourceStatusData(handle, value, 0)
        item = _PduResourceStatusItem(
            PDU_IT_RSC_STATUS,
            len(resource_ids),
            ctypes.cast(records, ctypes.POINTER(_PduResourceStatusData)),
        )
        status = int(self._pdu_get_resource_status(ctypes.byref(item)))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUGetResourceStatus failed with status 0x{status:08X}")
        return [
            DPduResourceStatus(
                module_handle=int(record.module_handle),
                resource_id=int(record.resource_id),
                raw_status=int(record.resource_status),
            )
            for record in records
        ]

    def enumerate_conflicts(
        self,
        resource_id: int,
        modules: tuple[DPduLiveModule, ...] | list[DPduLiveModule] | None = None,
    ) -> list[DPduResourceConflict]:
        """Query resource conflicts across the supplied/current module inventory."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        if self._pdu_get_conflicting_resources is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUGetConflictingResources"
            )
        value = int(resource_id)
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("resource_id must be an unsigned 32-bit value")
        selected = list(self._live_modules if modules is None else modules)
        if not selected or len(selected) > MAX_MODULES:
            raise ValueError(f"modules must contain between 1 and {MAX_MODULES} entries")
        module_records = (_PduModuleData * len(selected))()
        for index, module in enumerate(selected):
            module_records[index] = _PduModuleData(
                int(module.module_type_id),
                int(module.module_handle),
                None,
                None,
                int(module.module_status),
            )
        module_item = _PduModuleItem(
            PDU_IT_MODULE_ID,
            len(selected),
            ctypes.cast(module_records, ctypes.POINTER(_PduModuleData)),
        )
        output_ptr = ctypes.POINTER(_PduResourceConflictItem)()
        status = int(self._pdu_get_conflicting_resources(
            value, ctypes.byref(module_item), ctypes.byref(output_ptr)
        ))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUGetConflictingResources failed with status 0x{status:08X}"
            )
        if not output_ptr:
            return []
        try:
            result = output_ptr.contents
            count = int(result.num_entries)
            if count > MAX_RESOURCE_IDS:
                raise DPduApiError(f"Invalid conflict count: {count}")
            if count and not result.resource_conflict_data:
                raise DPduApiError("Conflict result has a null data array")
            return [
                DPduResourceConflict(
                    module_handle=int(result.resource_conflict_data[i].module_handle),
                    resource_id=int(result.resource_conflict_data[i].resource_id),
                )
                for i in range(count)
            ]
        finally:
            destroy_status = int(self._pdu_destroy_item(
                ctypes.cast(output_ptr, ctypes.POINTER(_PduItem))
            ))
            if destroy_status != PDU_STATUS_NOERROR:
                raise DPduApiError(
                    f"PDUDestroyItem failed after conflict query with status 0x{destroy_status:08X}"
                )

    def create_logical_link(
        self, module_handle: int, resource_id: int
    ) -> DPduComLogicalLink:
        """Reserve one known resource in an OFFLINE CLL; does not call PDUConnect."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        handle = int(module_handle)
        resource = int(resource_id)
        if handle not in self._connected_modules:
            raise RuntimeError("MVCI module must be explicitly connected first")
        if not 0 <= resource <= 0xFFFFFFFF:
            raise ValueError("resource_id must be an unsigned 32-bit value")
        if self._pdu_create_logical_link is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUCreateComLogicalLink"
            )
        if self._pdu_destroy_logical_link is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUDestroyComLogicalLink"
            )
        output_handle = ctypes.c_uint32(0)
        # The specific-resource-ID scheme requires pRscData=NULL and a valid
        # resourceId. The flag descriptor itself is mandatory; zero flag bytes
        # request no optional create flags.
        create_flags = _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)())
        status = int(self._pdu_create_logical_link(
            handle,
            None,
            resource,
            None,
            ctypes.byref(output_handle),
            ctypes.byref(create_flags),
        ))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUCreateComLogicalLink failed with status 0x{status:08X}"
            )
        logical_handle = int(output_handle.value)
        if logical_handle == 0xFFFFFFFF:
            raise DPduApiError("PDUCreateComLogicalLink returned PDU_HANDLE_UNDEF")
        link = DPduComLogicalLink(handle, logical_handle, resource)
        key = (handle, logical_handle)
        if key in self._logical_links:
            raise DPduApiError("D-PDU API returned a duplicate ComLogicalLink handle")
        self._logical_links[key] = link
        return link

    def connect_logical_link(
        self, module_handle: int, logical_link_handle: int
    ) -> DPduComLogicalLink:
        """Physically connect an OFFLINE CLL to its vehicle interface.

        This is an explicit hardware activation operation. It is never called
        by open(), module enumeration, CLL creation, or parameter setup.
        """
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        module = int(module_handle)
        cll = int(logical_link_handle)
        key = (module, cll)
        link = self._logical_links.get(key)
        if link is None:
            raise ValueError("Unknown or already destroyed ComLogicalLink")
        if module not in self._connected_modules:
            raise RuntimeError("MVCI module must be explicitly initialized first")
        if link.state != "offline":
            raise RuntimeError(f"ComLogicalLink is {link.state}, not offline")
        if self._pdu_connect is None:
            raise DPduApiError("Selected D-PDU library does not export PDUConnect")
        status = int(self._pdu_connect(module, cll))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUConnect failed with status 0x{status:08X}")
        connected = DPduComLogicalLink(module, cll, link.resource_id, "online")
        self._logical_links[key] = connected
        return connected

    def disconnect_logical_link(
        self, module_handle: int, logical_link_handle: int
    ) -> DPduComLogicalLink:
        """Physically disconnect an ONLINE CLL and return it to OFFLINE."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        module = int(module_handle)
        cll = int(logical_link_handle)
        key = (module, cll)
        link = self._logical_links.get(key)
        if link is None:
            raise ValueError("Unknown or already destroyed ComLogicalLink")
        if module not in self._connected_modules:
            raise RuntimeError("MVCI module is not initialized")
        if link.state != "online":
            raise RuntimeError(f"ComLogicalLink is {link.state}, not online")
        if self._pdu_disconnect is None:
            raise DPduApiError("Selected D-PDU library does not export PDUDisconnect")
        status = int(self._pdu_disconnect(module, cll))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUDisconnect failed with status 0x{status:08X}")
        disconnected = DPduComLogicalLink(module, cll, link.resource_id, "offline")
        self._logical_links[key] = disconnected
        return disconnected

    def destroy_logical_link(self, module_handle: int, logical_link_handle: int) -> None:
        """Destroy an OFFLINE ComLogicalLink and release its reserved resource."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        handle = int(module_handle)
        cll_handle = int(logical_link_handle)
        key = (handle, cll_handle)
        if key not in self._logical_links:
            raise ValueError("Unknown or already destroyed ComLogicalLink")
        if self._logical_links[key].state != "offline":
            raise RuntimeError("Disconnect the ComLogicalLink before destroying it")
        if self._pdu_destroy_logical_link is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUDestroyComLogicalLink"
            )
        status = int(self._pdu_destroy_logical_link(handle, cll_handle))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUDestroyComLogicalLink failed with status 0x{status:08X}"
            )
        del self._logical_links[key]

    def set_com_param_uint32(
        self,
        module_handle: int,
        logical_link_handle: int,
        param_id: int,
        value: int,
    ) -> int:
        """Set a UNUM32 ComParam in the offline CLL working buffer.

        param_id is the numeric COMPARAM ID from the module MDF. The API's
        PDUGetComParam result supplies the authoritative data type/class and
        an API-owned value buffer; only the UNUM32 value is modified.
        """
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        module = int(module_handle)
        cll = int(logical_link_handle)
        key = (module, cll)
        if key not in self._logical_links:
            raise ValueError("Unknown or already destroyed ComLogicalLink")
        if module not in self._connected_modules:
            raise RuntimeError("MVCI module is not initialized")
        param = int(param_id)
        new_value = int(value)
        if not 0 <= param <= 0xFFFFFFFF:
            raise ValueError("param_id must be an unsigned 32-bit value")
        if not 0 <= new_value <= 0xFFFFFFFF:
            raise ValueError("UNUM32 ComParam value must be an unsigned 32-bit value")
        if self._pdu_get_com_param is None:
            raise DPduApiError("Selected D-PDU library does not export PDUGetComParam")
        if self._pdu_set_com_param is None:
            raise DPduApiError("Selected D-PDU library does not export PDUSetComParam")

        item_ptr = ctypes.POINTER(_PduParamItem)()
        status = int(self._pdu_get_com_param(
            module, cll, param, ctypes.byref(item_ptr)
        ))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUGetComParam failed with status 0x{status:08X}")
        if not item_ptr:
            raise DPduApiError("PDUGetComParam succeeded but returned a null item")
        try:
            item = item_ptr.contents
            if int(item.com_param_id) != param:
                raise DPduApiError(
                    f"PDUGetComParam returned ID {int(item.com_param_id)}, expected {param}"
                )
            if int(item.data_type) != PDU_PT_UNUM32:
                raise DPduApiError(
                    f"ComParam {param} has data type 0x{int(item.data_type):08X}; "
                    "this setter only supports PDU_PT_UNUM32"
                )
            if not item.data:
                raise DPduApiError(f"ComParam {param} has a null data pointer")
            ctypes.cast(item.data, ctypes.POINTER(ctypes.c_uint32))[0] = new_value
            status = int(self._pdu_set_com_param(
                module, cll, ctypes.cast(item_ptr, ctypes.POINTER(_PduParamItem))
            ))
            if status != PDU_STATUS_NOERROR:
                raise DPduApiError(f"PDUSetComParam failed with status 0x{status:08X}")
            return new_value
        finally:
            destroy_status = int(self._pdu_destroy_item(
                ctypes.cast(item_ptr, ctypes.POINTER(_PduItem))
            ))
            if destroy_status != PDU_STATUS_NOERROR:
                raise DPduApiError(
                    f"PDUDestroyItem failed after ComParam update with status 0x{destroy_status:08X}"
                )

    def close(self) -> None:
        """Destroy the API session and release the selected library handle."""
        errors: list[str] = []
        if self._constructed and self._pdu_disconnect is not None:
            for (module_handle, cll_handle), link in tuple(self._logical_links.items()):
                if link.state != "online":
                    continue
                try:
                    status = int(self._pdu_disconnect(module_handle, cll_handle))
                    if status != PDU_STATUS_NOERROR:
                        errors.append(
                            f"PDUDisconnect({module_handle}, {cll_handle}) status 0x{status:08X}"
                        )
                    else:
                        self._logical_links[(module_handle, cll_handle)] = DPduComLogicalLink(
                            module_handle, cll_handle, link.resource_id, "offline"
                        )
                except Exception as exc:
                    errors.append(
                        f"PDUDisconnect({module_handle}, {cll_handle}) raised {exc}"
                    )
        if self._constructed and self._pdu_destroy_logical_link is not None:
            for module_handle, cll_handle in tuple(self._logical_links):
                current_link = self._logical_links[(module_handle, cll_handle)]
                if current_link.state != "offline":
                    errors.append(
                        f"PDUDestroyComLogicalLink({module_handle}, {cll_handle}) skipped because disconnect failed"
                    )
                    continue
                try:
                    status = int(self._pdu_destroy_logical_link(module_handle, cll_handle))
                    if status != PDU_STATUS_NOERROR:
                        errors.append(
                            f"PDUDestroyComLogicalLink({module_handle}, {cll_handle}) status 0x{status:08X}"
                        )
                    else:
                        self._logical_links.pop((module_handle, cll_handle), None)
                except Exception as exc:
                    errors.append(
                        f"PDUDestroyComLogicalLink({module_handle}, {cll_handle}) raised {exc}"
                    )
        if self._constructed and self._pdu_module_disconnect is not None:
            for handle in tuple(self._connected_modules):
                if any(key[0] == handle for key in self._logical_links):
                    errors.append(
                        f"PDUModuleDisconnect({handle}) skipped because a ComLogicalLink remains"
                    )
                    continue
                try:
                    status = int(self._pdu_module_disconnect(handle))
                    if status != PDU_STATUS_NOERROR:
                        errors.append(
                            f"PDUModuleDisconnect({handle}) status 0x{status:08X}"
                        )
                except Exception as exc:
                    errors.append(f"PDUModuleDisconnect({handle}) raised {exc}")
        self._connected_modules.clear()
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
        self._pdu_get_resource_status = None
        self._pdu_get_conflicting_resources = None
        self._pdu_module_connect = None
        self._pdu_module_disconnect = None
        self._pdu_create_logical_link = None
        self._pdu_destroy_logical_link = None
        self._pdu_connect = None
        self._pdu_disconnect = None
        self._pdu_get_com_param = None
        self._pdu_set_com_param = None
        self._logical_links = {}
        self._live_modules = []
        self._library = None
        if errors:
            raise DPduApiError("; ".join(errors))

    def __enter__(self) -> "DPduApiRuntime":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
