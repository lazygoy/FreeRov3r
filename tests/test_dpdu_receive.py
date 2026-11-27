import ctypes

import pytest

from freerov3r.hardware.dpdu_discovery import DPduModuleRegistration
from freerov3r.hardware.dpdu_receive import (
    DPduReceiveRuntime,
    PDU_COPT_SENDRECV,
    PDU_ERR_EVENT_QUEUE_EMPTY,
    PDU_IT_RESULT,
    _PduCopCtrlData,
    _PduEventItem,
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
        17, 91, response_mask=b"\\xff\\x00",
        response_pattern=b"\\x62\\x00", unique_response_ids=[0x123],
    )

    call = next(call for call in library.calls if call[0] == "start_receive")
    assert cop == 700
    assert call == (
        "start_receive", 17, 91, PDU_COPT_SENDRECV, 0, False, 0, -1, 1,
        b"\\xff\\x00", b"\\x62\\x00",
    )

    runtime.cancel_receive_only(17, 91, cop)
    runtime.close()


def test_receive_primitive_requires_online_link_and_valid_filter(runtime_pair):
    runtime, library = runtime_pair
    runtime.disconnect_logical_link(17, 91)

    with pytest.raises(RuntimeError, match="must be online"):
        runtime.start_receive_only(
            17, 91, response_mask=b"\\xff", response_pattern=b"\\x62"
        )

    with pytest.raises(ValueError, match="equal nonzero"):
        runtime.start_receive_only(
            17, 91, response_mask=b"\\xff", response_pattern=b""
        )

    assert not any(call[0] == "start_receive" for call in library.calls)
    runtime.close()


def test_event_queue_copies_result_and_destroys_api_item(runtime_pair):
    runtime, library = runtime_pair
    runtime.start_receive_only(
        17, 91, response_mask=b"\\xff", response_pattern=b"\\x62"
    )

    library.payload = (ctypes.c_uint8 * 3)(0x62, 0xF1, 0x90)
    library.result_data = _PduResultData(
        _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
        0x123,
        9,
        _PduFlagData(0, ctypes.POINTER(ctypes.c_uint8)()),
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
    assert event.data == b"\\x62\\xf1\\x90"
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
        17, 91, response_mask=b"\\xff", response_pattern=b"\\x62"
    )

    runtime.close()

    names = [call[0] for call in library.calls]
    assert names.index("cancel") < names.index("disconnect")
    assert names.index("disconnect") < names.index("destroy_cll")
    assert names.index("destroy_cll") < names.index("module_disconnect")
    assert names.index("module_disconnect") < names.index("destruct")
