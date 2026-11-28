"""Receive-only D-PDU ComPrimitive and event-queue support.

This layer receives protocol-level diagnostic responses. It is not a raw CAN
sniffer: D-PDU receive-only ComPrimitives match configured expected-response
structures. No request payload is supplied and NumSendCycles is always zero.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .dpdu_runtime import (
    DPduApiError,
    DPduApiRuntime,
    PDU_STATUS_NOERROR,
    _PduFlagData,
    _PduItem,
    _set_signature,
)

PDU_COPT_SENDRECV = 0x8004
PDU_IT_RESULT = 0x1300
PDU_IT_STATUS = 0x1301
PDU_IT_ERROR = 0x1302
PDU_IT_INFO = 0x1303
PDU_ERR_EVENT_QUEUE_EMPTY = 113
MAX_EVENT_DATA_BYTES = 65536
MAX_RESPONSE_PATTERN_BYTES = 4096


class _PduExpectedResponseData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("response_type", ctypes.c_uint32),
        ("acceptance_id", ctypes.c_uint32),
        ("num_mask_pattern_bytes", ctypes.c_uint32),
        ("mask_data", ctypes.POINTER(ctypes.c_uint8)),
        ("pattern_data", ctypes.POINTER(ctypes.c_uint8)),
        ("num_unique_resp_ids", ctypes.c_uint32),
        ("unique_resp_ids", ctypes.POINTER(ctypes.c_uint32)),
    ]


class _PduCopCtrlData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("time", ctypes.c_uint32),
        ("num_send_cycles", ctypes.c_int32),
        ("num_receive_cycles", ctypes.c_int32),
        ("temp_param_update", ctypes.c_uint32),
        ("tx_flag", _PduFlagData),
        ("num_possible_expected_responses", ctypes.c_uint32),
        ("expected_response_array", ctypes.POINTER(_PduExpectedResponseData)),
    ]


class _PduEventItem(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("item_type", ctypes.c_int32),
        ("cop_handle", ctypes.c_uint32),
        ("cop_tag", ctypes.c_void_p),
        ("timestamp", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


class _PduResultData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("rx_flag", _PduFlagData),
        ("unique_resp_identifier", ctypes.c_uint32),
        ("acceptance_id", ctypes.c_uint32),
        ("timestamp_flags", _PduFlagData),
        ("tx_msg_done_timestamp", ctypes.c_uint32),
        ("start_msg_timestamp", ctypes.c_uint32),
        ("extra_info", ctypes.c_void_p),
        ("num_data_bytes", ctypes.c_uint32),
        ("data_bytes", ctypes.POINTER(ctypes.c_uint8)),
    ]


class _PduErrorData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("error_code_id", ctypes.c_uint32),
        ("extra_error_info_id", ctypes.c_uint32),
    ]


class _PduInfoData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("info_code", ctypes.c_uint32),
        ("extra_info_data", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class DPduEvent:
    item_type: int
    cop_handle: int
    cop_tag: int
    timestamp_us: int
    data: bytes = b""
    start_message_timestamp_us: int | None = None
    transmit_done_timestamp_us: int | None = None
    acceptance_id: int | None = None
    unique_response_identifier: int | None = None
    error_code: int | None = None
    extra_info: int | None = None


class DPduReceiveRuntime(DPduApiRuntime):
    """D-PDU runtime with explicitly started, receive-only diagnostic CoPs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pdu_start_com_primitive = None
        self._pdu_cancel_com_primitive = None
        self._pdu_get_event_item = None
        self._active_receive_primitives: dict[tuple[int, int, int], None] = {}

    def _bind_functions(self) -> None:
        super()._bind_functions()
        self._pdu_start_com_primitive = getattr(
            self._library, "PDUStartComPrimitive", None
        )
        self._pdu_cancel_com_primitive = getattr(
            self._library, "PDUCancelComPrimitive", None
        )
        self._pdu_get_event_item = getattr(self._library, "PDUGetEventItem", None)
        if self._pdu_start_com_primitive is not None:
            _set_signature(
                self._pdu_start_com_primitive,
                [
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.POINTER(_PduCopCtrlData),
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_uint32),
                ],
                ctypes.c_int32,
            )
        if self._pdu_cancel_com_primitive is not None:
            _set_signature(
                self._pdu_cancel_com_primitive,
                [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                ctypes.c_int32,
            )
        if self._pdu_get_event_item is not None:
            _set_signature(
                self._pdu_get_event_item,
                [
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(ctypes.POINTER(_PduEventItem)),
                ],
                ctypes.c_int32,
            )

    def start_receive_only(
        self,
        module_handle: int,
        logical_link_handle: int,
        *,
        response_mask: bytes,
        response_pattern: bytes,
        unique_response_ids: tuple[int, ...] | list[int] = (),
        acceptance_id: int = 1,
    ) -> int:
        """Start infinite protocol-response reception with zero transmit cycles.

        The response mask/pattern are protocol-level expected-response filters,
        not CAN arbitration-ID filters. This method never supplies request data.
        """
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        module, cll = int(module_handle), int(logical_link_handle)
        link = self._logical_links.get((module, cll))
        if link is None or link.state != "online":
            raise RuntimeError("ComLogicalLink must be online before receiving")
        if self._pdu_start_com_primitive is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUStartComPrimitive"
            )
        if not response_mask or len(response_mask) != len(response_pattern):
            raise ValueError("response_mask and response_pattern must have equal nonzero lengths")
        if len(response_mask) > MAX_RESPONSE_PATTERN_BYTES:
            raise ValueError("expected-response pattern exceeds the safety limit")
        if len(unique_response_ids) > 256:
            raise ValueError("too many unique response identifiers")
        ids = tuple(int(value) for value in unique_response_ids)
        if any(value < 0 or value > 0xFFFFFFFF for value in ids):
            raise ValueError("unique response identifiers must be uint32 values")
        if not 0 <= int(acceptance_id) <= 0xFFFFFFFF:
            raise ValueError("acceptance_id must be a uint32 value")

        mask = (ctypes.c_uint8 * len(response_mask)).from_buffer_copy(response_mask)
        pattern = (ctypes.c_uint8 * len(response_pattern)).from_buffer_copy(response_pattern)
        id_array = (ctypes.c_uint32 * len(ids))(*ids) if ids else None
        expected = _PduExpectedResponseData(
            0,
            int(acceptance_id),
            len(response_mask),
            ctypes.cast(mask, ctypes.POINTER(ctypes.c_uint8)),
            ctypes.cast(pattern, ctypes.POINTER(ctypes.c_uint8)),
            len(ids),
            ctypes.cast(id_array, ctypes.POINTER(ctypes.c_uint32)) if id_array is not None
            else ctypes.POINTER(ctypes.c_uint32)(),
        )
        expected_array = (_PduExpectedResponseData * 1)(expected)
        control = _PduCopCtrlData(
            0,
            0,
            -1,
            0,
            _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
            1,
            ctypes.cast(expected_array, ctypes.POINTER(_PduExpectedResponseData)),
        )
        output = ctypes.c_uint32(0xFFFFFFFF)
        status = int(self._pdu_start_com_primitive(
            module,
            cll,
            PDU_COPT_SENDRECV,
            0,
            None,
            ctypes.byref(control),
            None,
            ctypes.byref(output),
        ))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUStartComPrimitive receive-only failed with status 0x{status:08X}"
            )
        cop = int(output.value)
        if cop == 0xFFFFFFFF:
            raise DPduApiError("PDUStartComPrimitive returned PDU_HANDLE_UNDEF")
        key = (module, cll, cop)
        if key in self._active_receive_primitives:
            raise DPduApiError("D-PDU API returned a duplicate ComPrimitive handle")
        self._active_receive_primitives[key] = None
        return cop

    def cancel_receive_only(
        self, module_handle: int, logical_link_handle: int, cop_handle: int
    ) -> None:
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        key = (int(module_handle), int(logical_link_handle), int(cop_handle))
        if key not in self._active_receive_primitives:
            raise ValueError("Unknown or already completed receive ComPrimitive")
        if self._pdu_cancel_com_primitive is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUCancelComPrimitive"
            )
        status = int(self._pdu_cancel_com_primitive(*key))
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(
                f"PDUCancelComPrimitive failed with status 0x{status:08X}"
            )
        self._active_receive_primitives.pop(key, None)

    def get_next_event(
        self, module_handle: int, logical_link_handle: int
    ) -> DPduEvent | None:
        """Pop and copy one event; returns None only when the event queue is empty."""
        if not self._constructed:
            raise RuntimeError("D-PDU API session is not open")
        if self._pdu_get_event_item is None:
            raise DPduApiError(
                "Selected D-PDU library does not export PDUGetEventItem"
            )
        module, cll = int(module_handle), int(logical_link_handle)
        if (module, cll) not in self._logical_links:
            raise ValueError("Unknown ComLogicalLink")
        item_ptr = ctypes.POINTER(_PduEventItem)()
        status = int(self._pdu_get_event_item(module, cll, ctypes.byref(item_ptr)))
        if status == PDU_ERR_EVENT_QUEUE_EMPTY:
            return None
        if status != PDU_STATUS_NOERROR:
            raise DPduApiError(f"PDUGetEventItem failed with status 0x{status:08X}")
        if not item_ptr:
            raise DPduApiError("PDUGetEventItem succeeded but returned a null item")
        try:
            item = item_ptr.contents
            item_type = int(item.item_type)
            cop_handle = int(item.cop_handle)
            tag = int(item.cop_tag or 0)
            timestamp = int(item.timestamp)
            data = b""
            start_ts = tx_done_ts = acceptance = unique_id = error_code = extra = None
            if item_type == PDU_IT_RESULT:
                if not item.data:
                    raise DPduApiError("PDU result event has a null data pointer")
                result = ctypes.cast(item.data, ctypes.POINTER(_PduResultData)).contents
                length = int(result.num_data_bytes)
                if length > MAX_EVENT_DATA_BYTES:
                    raise DPduApiError("PDU result event payload exceeds the safety limit")
                if length and not result.data_bytes:
                    raise DPduApiError("PDU result event has a null payload buffer")
                data = ctypes.string_at(result.data_bytes, length) if length else b""
                start_ts = int(result.start_msg_timestamp)
                tx_done_ts = int(result.tx_msg_done_timestamp)
                acceptance = int(result.acceptance_id)
                unique_id = int(result.unique_resp_identifier)
            elif item_type == PDU_IT_ERROR:
                if not item.data:
                    raise DPduApiError("PDU error event has a null data pointer")
                detail = ctypes.cast(item.data, ctypes.POINTER(_PduErrorData)).contents
                error_code, extra = int(detail.error_code_id), int(detail.extra_error_info_id)
            elif item_type == PDU_IT_INFO:
                if not item.data:
                    raise DPduApiError("PDU info event has a null data pointer")
                detail = ctypes.cast(item.data, ctypes.POINTER(_PduInfoData)).contents
                error_code, extra = int(detail.info_code), int(detail.extra_info_data)
            event = DPduEvent(
                item_type, cop_handle, tag, timestamp, data,
                start_ts, tx_done_ts, acceptance, unique_id, error_code, extra,
            )
            return event
        finally:
            destroy_status = int(self._pdu_destroy_item(
                ctypes.cast(item_ptr, ctypes.POINTER(_PduItem))
            ))
            if destroy_status != PDU_STATUS_NOERROR:
                raise DPduApiError(
                    f"PDUDestroyItem failed for event item with status 0x{destroy_status:08X}"
                )

    def close(self) -> None:
        """Cancel live receive primitives before the base runtime tears links down."""
        if self._constructed and self._active_receive_primitives:
            if self._pdu_cancel_com_primitive is None:
                raise DPduApiError(
                    "Cannot close D-PDU session with active receive primitives: "
                    "PDUCancelComPrimitive is unavailable"
                )
            for key in tuple(self._active_receive_primitives):
                status = int(self._pdu_cancel_com_primitive(*key))
                if status != PDU_STATUS_NOERROR:
                    raise DPduApiError(
                        "Cannot safely close D-PDU session; "
                        f"PDUCancelComPrimitive failed with status 0x{status:08X}"
                    )
                self._active_receive_primitives.pop(key, None)
        super().close()
