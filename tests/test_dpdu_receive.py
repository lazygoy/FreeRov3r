import ctypes

import pytest

from freerov3r.hardware.dpdu_discovery import DPduModuleRegistration
from freerov3r.hardware.dpdu_receive import (
    DPduReceiveRuntime,
    PDU_COPT_SENDRECV,
    PDU_ERR_EVENT_QUEUE_EMPTY,
    PDU_IT_RESULT,
    PDU_IT_STATUS,
    PDU_COPST_FINISHED,
    _PduCopCtrlData,
    _PduEventItem,
    _PduExpectedResponseData,
    _PduResultData,
)
from freerov3r.hardware.dpdu_runtime import (
    DPduApiError,
    _PduFlagData,
    _PduModuleData,
    _PduModuleItem,
)


class FakePduLibrary:
    def __init__(self):
        self.calls = []
        self.module_data = (_PduModuleData * 1)()
        self.module_data[0] = _PduModuleData(3, 17, None, None, 1)
        self.module_item = _PduModuleItem(
            0x1600, 1,
            ctypes.cast(self.module_data, ctypes.POINTER(_PduModuleData)),
        )
        self.module_item_ptr = ctypes.pointer(self.module_item)
        self.event_item = None
        self.event_item_ptr = None
        self.result_data = None
        self.payload = None
        self.next_cop = 700

    def PDUConstruct(self, _option, _tag):
        self.calls.append(("construct",))
        return 0

    def PDUDestruct(self):
        self.calls.append(("destruct",))
        return 0

    def PDUGetModuleIds(self, output):
        ctypes.cast(
            output, ctypes.POINTER(ctypes.POINTER(_PduModuleItem))
        )[0] = self.module_item_ptr
        return 0

    def PDUDestroyItem(self, item):
        self.calls.append(("destroy_item", ctypes.cast(item, ctypes.c_void_p).value))
        return 0

    def PDUModuleConnect(self, module):
        self.calls.append(("module_connect", module))
        return 0

    def PDUModuleDisconnect(self, module):
        self.calls.append(("module_disconnect", module))
        return 0

    def PDUCreateComLogicalLink(self, _module, _rsc, _rid, _tag, output, _flags):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 91
        return 0

    def PDUConnect(self, module, cll):
        self.calls.append(("connect", module, cll))
        return 0

    def PDUDisconnect(self, module, cll):
        self.calls.append(("disconnect", module, cll))
        return 0

    def PDUDestroyComLogicalLink(self, module, cll):
        self.calls.append(("destroy_cll", module, cll))
        return 0

    def PDUStartComPrimitive(
        self, module, cll, cop_type, data_size, data, control, tag, output
    ):
        ctrl = ctypes.cast(control, ctypes.POINTER(_PduCopCtrlData)).contents
        expected = ctrl.expected_response_array[0]
        self.calls.append((
            "start_receive",
            module,
            cll,
            cop_type,
            data_size,
            bool(data),
            int(ctrl.num_send_cycles),
            int(ctrl.num_receive_cycles),
            int(ctrl.num_possible_expected_responses),
            bytes(expected.mask_data[i] for i in range(expected.num_mask_pattern_bytes)),
            bytes(expected.pattern_data[i] for i in range(expected.num_mask_pattern_bytes)),
        ))
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = self.next_cop
        return 0

    def PDUCancelComPrimitive(self, module, cll, cop):
        self.calls.append(("cancel", module, cll, cop))
        return 0

    def PDUGetEventItem(self, module, cll, output):
        self.calls.append(("get_event", module, cll))
        if self.event_item_ptr is None:
            return PDU_ERR_EVENT_QUEUE_EMPTY
        ctypes.cast(
            output, ctypes.POINTER(ctypes.POINTER(_PduEventItem))
        )[0] = self.event_item_ptr
        self.event_item_ptr = None
        return 0


@pytest.fixture
def runtime_pair():
    registration = DPduModuleRegistration(
        short_name="Test_API",
        library_file="test-pdu.dll",
        module_description_file="mdf.xml",
        cable_description_file="cdf.xml",
    )
    library = FakePduLibrary()
    runtime = DPduReceiveRuntime(
        registration, library_loader=lambda _path: library
    )
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)
    runtime.connect_logical_link(17, 91)
    return runtime, library


def test_receive_primitive_is_explicitly_receive_only(runtime_pair):
    runtime, library = runtime_pair

    cop = runtime.start_receive_only(
        17, 91, response_mask=b"\xff\x00",
        response_pattern=b"\x62\x00", unique_response_ids=[0x123],
    )

    call = next(call for call in library.calls if call[0] == "start_receive")
    assert cop == 700
    assert call == (
        "start_receive", 17, 91, PDU_COPT_SENDRECV, 0, False, 0, -1, 1,
        b"\xff\x00", b"\x62\x00",
    )

    runtime.cancel_receive_only(17, 91, cop)
    runtime.close()


def test_receive_primitive_requires_online_link_and_valid_filter(runtime_pair):
    runtime, library = runtime_pair
    with pytest.raises(ValueError, match="equal nonzero"):
        runtime.start_receive_only(
            17, 91, response_mask=b"\xff", response_pattern=b""
        )

    runtime.disconnect_logical_link(17, 91)
    with pytest.raises(RuntimeError, match="must be online"):
        runtime.start_receive_only(
            17, 91, response_mask=b"\xff", response_pattern=b"\x62"
        )

    assert not any(call[0] == "start_receive" for call in library.calls)
    runtime.close()


def test_event_queue_copies_result_and_destroys_api_item(runtime_pair):
    runtime, library = runtime_pair
    runtime.start_receive_only(
        17, 91, response_mask=b"\xff", response_pattern=b"\x62"
    )

    library.payload = (ctypes.c_uint8 * 3)(0x62, 0xF1, 0x90)
    timestamp_flag_bytes = (ctypes.c_uint8 * 1)(0xC0)
    library.result_data = _PduResultData(
        _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
        0x123,
        9,
        _PduFlagData(
            1, ctypes.cast(timestamp_flag_bytes, ctypes.POINTER(ctypes.c_uint8))
        ),
        456,
        123,
        None,
        3,
        ctypes.cast(library.payload, ctypes.POINTER(ctypes.c_uint8)),
    )
    library.event_item = _PduEventItem(
        PDU_IT_RESULT, 700, None, 999,
        ctypes.cast(ctypes.pointer(library.result_data), ctypes.c_void_p),
    )
    library.event_item_ptr = ctypes.pointer(library.event_item)

    event = runtime.get_next_event(17, 91)

    assert event.item_type == PDU_IT_RESULT
    assert event.cop_handle == 700
    assert event.timestamp_us == 999
    assert event.data == b"\x62\xf1\x90"
    assert event.start_message_timestamp_us == 123
    assert event.transmit_done_timestamp_us == 456
    assert event.acceptance_id == 9
    assert event.unique_response_identifier == 0x123
    assert any(call[0] == "destroy_item" for call in library.calls)
    assert runtime.get_next_event(17, 91) is None

    runtime.cancel_receive_only(17, 91, 700)
    runtime.close()


def test_close_cancels_receive_primitive_before_disconnect(runtime_pair):
    runtime, library = runtime_pair
    runtime.start_receive_only(
        17, 91, response_mask=b"\xff", response_pattern=b"\x62"
    )

    runtime.close()

    names = [call[0] for call in library.calls]
    assert names.index("cancel") < names.index("disconnect")
    assert names.index("disconnect") < names.index("destroy_cll")
    assert names.index("destroy_cll") < names.index("module_disconnect")
    assert names.index("module_disconnect") < names.index("destruct")



def test_iso_22900_structures_use_one_byte_packing():
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    assert _PduExpectedResponseData.mask_data.offset == 12
    assert _PduExpectedResponseData.pattern_data.offset == 12 + pointer_size
    assert _PduExpectedResponseData.num_unique_resp_ids.offset == 16 + 2 * pointer_size
    assert _PduExpectedResponseData.unique_resp_ids.offset == 20 + 2 * pointer_size
    assert ctypes.sizeof(_PduExpectedResponseData) == 20 + 3 * pointer_size

    assert _PduCopCtrlData.tx_flag.offset == 16
    assert _PduCopCtrlData.num_possible_expected_responses.offset == 20 + pointer_size
    assert _PduCopCtrlData.expected_response_array.offset == 24 + pointer_size
    assert ctypes.sizeof(_PduCopCtrlData) == 24 + 2 * pointer_size

    assert _PduEventItem.cop_tag.offset == 8
    assert _PduEventItem.timestamp.offset == 8 + pointer_size
    assert _PduEventItem.data.offset == 12 + pointer_size
    assert ctypes.sizeof(_PduEventItem) == 12 + 2 * pointer_size

    assert _PduResultData.unique_resp_identifier.offset == 4 + pointer_size
    assert _PduResultData.timestamp_flags.offset == 12 + pointer_size
    assert _PduResultData.tx_msg_done_timestamp.offset == 16 + 2 * pointer_size
    assert _PduResultData.start_msg_timestamp.offset == 20 + 2 * pointer_size
    assert _PduResultData.extra_info.offset == 24 + 2 * pointer_size
    assert _PduResultData.num_data_bytes.offset == 24 + 3 * pointer_size
    assert _PduResultData.data_bytes.offset == 28 + 3 * pointer_size


def test_result_timestamps_are_none_when_timestamp_flags_are_clear(runtime_pair):
    runtime, library = runtime_pair
    runtime.start_receive_only(
        17, 91, response_mask=b"\\xff", response_pattern=b"\\x62"
    )
    library.payload = (ctypes.c_uint8 * 1)(0x62)
    library.result_data = _PduResultData(
        _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
        0,
        1,
        _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
        456,
        123,
        None,
        1,
        ctypes.cast(library.payload, ctypes.POINTER(ctypes.c_uint8)),
    )
    library.event_item = _PduEventItem(
        PDU_IT_RESULT, 700, None, 999,
        ctypes.cast(ctypes.pointer(library.result_data), ctypes.c_void_p),
    )
    library.event_item_ptr = ctypes.pointer(library.event_item)

    event = runtime.get_next_event(17, 91)
    assert event.start_message_timestamp_us is None
    assert event.transmit_done_timestamp_us is None

    runtime.cancel_receive_only(17, 91, 700)
    runtime.close()



def test_terminal_status_event_retires_receive_primitive(runtime_pair):
    runtime, library = runtime_pair
    runtime.start_receive_only(
        17, 91, response_mask=b"\\xff", response_pattern=b"\\x62"
    )
    status_data = ctypes.c_uint32(PDU_COPST_FINISHED)
    library.event_item = _PduEventItem(
        PDU_IT_STATUS, 700, None, 1000,
        ctypes.cast(ctypes.pointer(status_data), ctypes.c_void_p),
    )
    library.event_item_ptr = ctypes.pointer(library.event_item)

    event = runtime.get_next_event(17, 91)

    assert event.item_type == PDU_IT_STATUS
    assert event.status_code == PDU_COPST_FINISHED
    runtime.close()
    assert not any(call[0] == "cancel" for call in library.calls)
