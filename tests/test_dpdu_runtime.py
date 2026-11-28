import ctypes

import pytest

from freerov3r.hardware.dpdu_discovery import DPduModuleRegistration
from freerov3r.hardware.dpdu_runtime import (
    DPduApiError,
    DPduApiRuntime,
    _PduItem,
    _PduModuleData,
    _PduModuleItem,
    _PduPinData,
    _PduResourceData,
    _PduResourceIdItemData,
    _PduResourceIdItem,
    _PduResourceStatusData,
    _PduResourceStatusItem,
    _PduFlagData,
    _PduParamItem,
    _PduResourceConflictData,
    _PduResourceConflictItem,
)


@pytest.fixture
def registration():
    return DPduModuleRegistration(
        short_name="Test_API",
        library_file="test-pdu.dll",
        module_description_file="mdf.xml",
        cable_description_file="cdf.xml",
    )


class FakePduLibrary:
    def __init__(self, *, construct_status=0, list_status=0, modules=()):
        self.construct_status = construct_status
        self.list_status = list_status
        self.calls = []
        self._records = (_PduModuleData * len(modules))()
        self._strings = []
        for index, module in enumerate(modules):
            name = ctypes.create_string_buffer(module.get("name", "").encode("latin-1"))
            info = ctypes.create_string_buffer(module.get("info", "").encode("latin-1"))
            self._strings.extend([name, info])
            self._records[index] = _PduModuleData(
                module.get("type_id", 1),
                module.get("handle", index + 1),
                ctypes.cast(name, ctypes.c_char_p),
                ctypes.cast(info, ctypes.c_char_p),
                module.get("status", 0),
            )
        self._item = _PduModuleItem(
            0x1000,
            len(modules),
            ctypes.cast(self._records, ctypes.POINTER(_PduModuleData))
            if modules else ctypes.POINTER(_PduModuleData)(),
        )
        self._item_pointer = ctypes.pointer(self._item)

    def PDUConstruct(self, option, tag):
        self.calls.append(("construct", option, tag))
        return self.construct_status

    def PDUDestruct(self):
        self.calls.append(("destruct",))
        return 0

    def PDUGetModuleIds(self, output):
        self.calls.append(("get_modules",))
        if self.list_status == 0:
            output_pointer = ctypes.cast(
                output, ctypes.POINTER(ctypes.POINTER(_PduModuleItem))
            )
            output_pointer[0] = self._item_pointer
        return self.list_status

    def PDUDestroyItem(self, item):
        self.calls.append(("destroy_item", ctypes.cast(item, ctypes.c_void_p).value))
        return 0


def test_runtime_loads_selected_api_and_enumerates_live_modules(registration):
    library = FakePduLibrary(modules=[
        {
            "type_id": 3,
            "handle": 17,
            "status": 1,
            "name": "MVCI Friendly Name='VCI One'",
            "info": "Connection Type USB=''",
        },
        {
            "type_id": 4,
            "handle": 18,
            "status": 0,
            "name": "VCI Two",
        },
    ])
    loaded = []
    runtime = DPduApiRuntime(
        registration,
        library_loader=lambda path: loaded.append(path) or library,
    )

    modules = runtime.open()

    assert loaded == ["test-pdu.dll"]
    assert [(m.module_type_id, m.module_handle, m.module_status) for m in modules] == [
        (3, 17, 1),
        (4, 18, 0),
    ]
    assert modules[0].vendor_module_name == "MVCI Friendly Name='VCI One'"
    assert modules[1].vendor_module_name == "VCI Two"
    assert runtime.is_open
    assert [call[0] for call in library.calls] == [
        "construct", "get_modules", "destroy_item"
    ]

    runtime.close()
    assert not runtime.is_open
    assert library.calls[-1] == ("destruct",)


def test_runtime_handles_zero_detected_modules(registration):
    library = FakePduLibrary(modules=[])
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)

    assert runtime.open() == []
    runtime.close()


def test_runtime_destroys_module_item_when_decoding_fails(registration):
    library = FakePduLibrary(modules=[])
    # Corrupt the returned count beyond the defensive maximum.
    library._item.num_entries = 999
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)

    with pytest.raises(DPduApiError, match="invalid module count"):
        runtime.open()

    assert ("destroy_item", ctypes.cast(
        library._item_pointer, ctypes.c_void_p
    ).value) in library.calls
    assert library.calls[-1] == ("destruct",)


def test_runtime_destructs_after_module_enumeration_error(registration):
    library = FakePduLibrary(list_status=0x22)
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)

    with pytest.raises(DPduApiError, match="PDUGetModuleIds"):
        runtime.open()

    assert library.calls[-1] == ("destruct",)


def test_runtime_does_not_destruct_when_construct_fails(registration):
    library = FakePduLibrary(construct_status=0x31)
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)

    with pytest.raises(DPduApiError, match="PDUConstruct"):
        runtime.open()

    assert [call[0] for call in library.calls] == ["construct"]


def test_runtime_rejects_missing_required_exports(registration):
    class IncompleteLibrary:
        def PDUConstruct(self, *_args):
            return 0

    runtime = DPduApiRuntime(
        registration, library_loader=lambda _path: IncompleteLibrary()
    )

    with pytest.raises(DPduApiError, match="missing required export"):
        runtime.open()


def test_runtime_requires_explicit_open(registration):
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: None)

    with pytest.raises(RuntimeError, match="not open"):
        runtime.enumerate_modules()


def test_runtime_rejects_repeated_open(registration):
    library = FakePduLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    with pytest.raises(RuntimeError, match="already open"):
        runtime.open()

    runtime.close()

def test_runtime_queries_resource_ids_using_mdf_cdf_pin_ids(registration):
    from freerov3r.hardware.dpdu_runtime import (
        _PduResourceIdItem,
        _PduResourceIdItemData,
        _PduResourceData,
    )

    class ResourceLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__()
            self.resource_records = (ctypes.c_uint32 * 2)(600, 601)
            self.group = (_PduResourceIdItemData * 1)()
            self.group[0] = _PduResourceIdItemData(
                17, 2, ctypes.cast(self.resource_records, ctypes.POINTER(ctypes.c_uint32))
            )
            self.item = _PduResourceIdItem(
                0x1000, 1,
                ctypes.cast(self.group, ctypes.POINTER(_PduResourceIdItemData))
            )
            self.item_ptr = ctypes.pointer(self.item)
            self.request_seen = None

        def PDUGetResourceIds(self, module_handle, request, output):
            self.calls.append(("get_resource_ids", module_handle))
            req = ctypes.cast(request, ctypes.POINTER(_PduResourceData)).contents
            self.request_seen = (
                int(req.bus_type_id),
                int(req.protocol_id),
                int(req.num_pin_data),
                tuple(
                    (int(req.dlc_pin_data[i].dlc_pin_number),
                     int(req.dlc_pin_data[i].dlc_pin_type_id))
                    for i in range(req.num_pin_data)
                ),
            )
            ctypes.cast(
                output, ctypes.POINTER(ctypes.POINTER(_PduResourceIdItem))
            )[0] = self.item_ptr
            return 0

    library = ResourceLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    matches = runtime.enumerate_resource_ids(
        17, 300, 400, [(6, 2000), (14, 2001)]
    )

    assert library.request_seen == (300, 400, 2, ((6, 2000), (14, 2001)))
    assert matches[0].module_handle == 17
    assert matches[0].resource_ids == (600, 601)
    assert any(call[0] == "destroy_item" for call in library.calls)

    runtime.close()


def test_runtime_rejects_resource_query_without_dlc_pin_data(registration):
    library = FakePduLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    with pytest.raises(ValueError, match="dlc_pins"):
        runtime.enumerate_resource_ids(17, 300, 400, [])

    runtime.close()


def test_runtime_resource_status_is_read_without_module_connection(registration):
    from freerov3r.hardware.dpdu_runtime import (
        _PduResourceStatusItem,
        _PduResourceStatusData,
    )

    class StatusLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUGetResourceStatus(self, item_ptr):
            item = ctypes.cast(
                item_ptr, ctypes.POINTER(_PduResourceStatusItem)
            ).contents
            self.calls.append(("resource_status", item.item_type, item.num_entries))
            assert item.item_type == 0x1100
            assert item.num_entries == 2
            records = ctypes.cast(
                item.resource_status_data,
                ctypes.POINTER(_PduResourceStatusData),
            )
            records[0].resource_status = 0
            records[1].resource_status = 3
            return 0

    library = StatusLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    statuses = runtime.get_resource_status(17, [600, 601])

    assert [(s.resource_id, s.raw_status) for s in statuses] == [(600, 0), (601, 3)]
    assert ("resource_status", 0x1100, 2) in library.calls
    assert not any(call[0] == "module_connect" for call in library.calls)
    runtime.close()

def test_runtime_disconnects_connected_modules_during_close(registration):
    class ConnectedLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, handle):
            self.calls.append(("module_connect", handle))
            return 0

        def PDUModuleDisconnect(self, handle):
            self.calls.append(("module_disconnect", handle))
            return 0

    library = ConnectedLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.close()

    assert library.calls[-2:] == [("module_disconnect", 17), ("destruct",)]


def test_runtime_enumerates_conflicting_resources_and_destroys_result(registration):
    from freerov3r.hardware.dpdu_runtime import (
        _PduResourceConflictData,
        _PduResourceConflictItem,
        _PduModuleItem,
    )

    class ConflictLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])
            self.conflicts = (_PduResourceConflictData * 2)(
                _PduResourceConflictData(17, 701),
                _PduResourceConflictData(17, 702),
            )
            self.item = _PduResourceConflictItem(
                0x1500, 2,
                ctypes.cast(self.conflicts, ctypes.POINTER(_PduResourceConflictData)),
            )
            self.item_ptr = ctypes.pointer(self.item)

        def PDUGetConflictingResources(self, resource_id, modules_ptr, output_ptr):
            modules = ctypes.cast(
                modules_ptr, ctypes.POINTER(_PduModuleItem)
            ).contents
            self.calls.append((
                "conflicts", resource_id, modules.item_type, modules.num_entries,
                int(modules.module_data[0].module_type_id),
                int(modules.module_data[0].module_handle),
            ))
            ctypes.cast(
                output_ptr, ctypes.POINTER(ctypes.POINTER(_PduResourceConflictItem))
            )[0] = self.item_ptr
            return 0

    library = ConflictLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    conflicts = runtime.enumerate_conflicts(600)

    assert library.calls[-2] == ("conflicts", 600, 0x1600, 1, 3, 17)
    assert [(item.module_handle, item.resource_id) for item in conflicts] == [
        (17, 701), (17, 702)
    ]
    assert any(call[0] == "destroy_item" for call in library.calls)
    runtime.close()


def test_runtime_creates_and_destroys_offline_logical_link(registration):
    from freerov3r.hardware.dpdu_runtime import _PduFlagData

    class LogicalLinkLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])
            self.next_cll = 91

        def PDUModuleConnect(self, handle):
            self.calls.append(("module_connect", handle))
            return 0

        def PDUModuleDisconnect(self, handle):
            self.calls.append(("module_disconnect", handle))
            return 0

        def PDUCreateComLogicalLink(
            self, module_handle, resource_data, resource_id, tag, output_handle, flags
        ):
            flag_data = ctypes.cast(flags, ctypes.POINTER(_PduFlagData)).contents
            self.calls.append((
                "create_cll", module_handle, resource_data, resource_id, tag,
                flag_data.num_flag_bytes,
            ))
            ctypes.cast(output_handle, ctypes.POINTER(ctypes.c_uint32))[0] = self.next_cll
            return 0

        def PDUDestroyComLogicalLink(self, module_handle, cll_handle):
            self.calls.append(("destroy_cll", module_handle, cll_handle))
            return 0

    library = LogicalLinkLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    with pytest.raises(RuntimeError, match="module must be explicitly connected"):
        runtime.create_logical_link(17, 600)

    runtime.connect_module(17)
    link = runtime.create_logical_link(17, 600)

    assert (link.module_handle, link.logical_link_handle, link.resource_id) == (17, 91, 600)
    assert link.initial_state == "offline"
    assert ("create_cll", 17, None, 600, None, 0) in library.calls

    runtime.destroy_logical_link(17, 91)
    assert ("destroy_cll", 17, 91) in library.calls
    runtime.disconnect_module(17)
    runtime.close()


def test_runtime_refuses_module_disconnect_while_logical_link_exists(registration):
    class LogicalLinkLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, handle):
            return 0

        def PDUModuleDisconnect(self, handle):
            self.calls.append(("module_disconnect", handle))
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, out, _flags):
            ctypes.cast(out, ctypes.POINTER(ctypes.c_uint32))[0] = 92
            return 0

        def PDUDestroyComLogicalLink(self, module_handle, cll_handle):
            self.calls.append(("destroy_cll", module_handle, cll_handle))
            return 0

    library = LogicalLinkLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)

    with pytest.raises(RuntimeError, match="Destroy all ComLogicalLinks"):
        runtime.disconnect_module(17)

    runtime.close()
    assert library.calls[-3:] == [
        ("destroy_cll", 17, 92),
        ("module_disconnect", 17),
        ("destruct",),
    ]


def test_runtime_rejects_logical_link_creation_without_exports(registration):
    class ModuleLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, _handle):
            return 0

        def PDUModuleDisconnect(self, _handle):
            return 0

    library = ModuleLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)

    with pytest.raises(DPduApiError, match="PDUCreateComLogicalLink"):
        runtime.create_logical_link(17, 600)

    runtime.close()


def test_runtime_sets_uint32_com_param_in_offline_logical_link(registration):
    from freerov3r.hardware.dpdu_runtime import _PduParamItem

    class ComParamLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])
            self.value = ctypes.c_uint32(50000)
            self.param_item = _PduParamItem(
                0x2000, 77, 0x00000105, 3,
                ctypes.cast(ctypes.pointer(self.value), ctypes.c_void_p),
            )
            self.param_ptr = ctypes.pointer(self.param_item)

        def PDUModuleConnect(self, _handle):
            return 0

        def PDUModuleDisconnect(self, _handle):
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, output, _flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 91
            return 0

        def PDUDestroyComLogicalLink(self, _mod, _cll):
            return 0

        def PDUGetComParam(self, module, cll, param_id, output):
            self.calls.append(("get_param", module, cll, param_id))
            ctypes.cast(
                output, ctypes.POINTER(ctypes.POINTER(_PduParamItem))
            )[0] = self.param_ptr
            return 0

        def PDUSetComParam(self, module, cll, item_ptr):
            item = ctypes.cast(item_ptr, ctypes.POINTER(_PduParamItem)).contents
            self.calls.append((
                "set_param", module, cll, item.com_param_id,
                item.data_type, item.param_class, self.value.value,
            ))
            return 0

    library = ComParamLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)

    assert runtime.set_com_param_uint32(17, 91, 77, 250000) == 250000
    assert library.value.value == 250000
    assert ("set_param", 17, 91, 77, 0x00000105, 3, 250000) in library.calls
    assert any(call[0] == "destroy_item" for call in library.calls)

    runtime.close()


def test_runtime_rejects_unsupported_com_param_type_and_frees_item(registration):
    from freerov3r.hardware.dpdu_runtime import _PduParamItem

    class ComParamLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])
            self.value = ctypes.c_uint8(1)
            self.param_item = _PduParamItem(
                0x2000, 77, 0x00000101, 3,
                ctypes.cast(ctypes.pointer(self.value), ctypes.c_void_p),
            )
            self.param_ptr = ctypes.pointer(self.param_item)

        def PDUModuleConnect(self, _handle):
            return 0

        def PDUModuleDisconnect(self, _handle):
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, output, _flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 91
            return 0

        def PDUDestroyComLogicalLink(self, _mod, _cll):
            return 0

        def PDUGetComParam(self, _module, _cll, _param, output):
            ctypes.cast(
                output, ctypes.POINTER(ctypes.POINTER(_PduParamItem))
            )[0] = self.param_ptr
            return 0

        def PDUSetComParam(self, *_args):
            raise AssertionError("PDUSetComParam must not be called for unsupported types")

    library = ComParamLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)

    with pytest.raises(DPduApiError, match="only supports PDU_PT_UNUM32"):
        runtime.set_com_param_uint32(17, 91, 77, 5)

    assert any(call[0] == "destroy_item" for call in library.calls)
    runtime.close()


def test_runtime_explicitly_connects_and_disconnects_logical_link(registration):
    class PhysicalLinkLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, handle):
            self.calls.append(("module_connect", handle))
            return 0

        def PDUModuleDisconnect(self, handle):
            self.calls.append(("module_disconnect", handle))
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, output, _flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 91
            return 0

        def PDUDestroyComLogicalLink(self, module, cll):
            self.calls.append(("destroy_cll", module, cll))
            return 0

        def PDUConnect(self, module, cll):
            self.calls.append(("connect_cll", module, cll))
            return 0

        def PDUDisconnect(self, module, cll):
            self.calls.append(("disconnect_cll", module, cll))
            return 0

    library = PhysicalLinkLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()

    assert not any(call[0] == "connect_cll" for call in library.calls)
    runtime.connect_module(17)
    link = runtime.create_logical_link(17, 600)
    assert link.state == "offline"
    assert not any(call[0] == "connect_cll" for call in library.calls)

    online = runtime.connect_logical_link(17, 91)
    assert online.state == "online"
    assert ("connect_cll", 17, 91) in library.calls

    with pytest.raises(RuntimeError, match="not offline"):
        runtime.connect_logical_link(17, 91)
    with pytest.raises(RuntimeError, match="Disconnect"):
        runtime.destroy_logical_link(17, 91)

    offline = runtime.disconnect_logical_link(17, 91)
    assert offline.state == "offline"
    assert ("disconnect_cll", 17, 91) in library.calls

    runtime.destroy_logical_link(17, 91)
    runtime.disconnect_module(17)
    runtime.close()


def test_runtime_close_disconnects_online_links_before_destroying(registration):
    class PhysicalLinkLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, _handle):
            return 0

        def PDUModuleDisconnect(self, handle):
            self.calls.append(("module_disconnect", handle))
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, output, _flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 92
            return 0

        def PDUConnect(self, module, cll):
            self.calls.append(("connect_cll", module, cll))
            return 0

        def PDUDisconnect(self, module, cll):
            self.calls.append(("disconnect_cll", module, cll))
            return 0

        def PDUDestroyComLogicalLink(self, module, cll):
            self.calls.append(("destroy_cll", module, cll))
            return 0

    library = PhysicalLinkLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)
    runtime.connect_logical_link(17, 92)

    runtime.close()

    names = [call[0] for call in library.calls]
    assert names.index("disconnect_cll") < names.index("destroy_cll")
    assert names.index("destroy_cll") < names.index("module_disconnect")
    assert names.index("module_disconnect") < names.index("destruct")


def test_runtime_rejects_physical_connect_without_export(registration):
    class ModuleAndLinkLibrary(FakePduLibrary):
        def __init__(self):
            super().__init__(modules=[{"type_id": 3, "handle": 17, "status": 1}])

        def PDUModuleConnect(self, _handle):
            return 0

        def PDUModuleDisconnect(self, _handle):
            return 0

        def PDUCreateComLogicalLink(self, _mod, _rsc, _rid, _tag, output, _flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 93
            return 0

        def PDUDestroyComLogicalLink(self, _module, _cll):
            return 0

    library = ModuleAndLinkLibrary()
    runtime = DPduApiRuntime(registration, library_loader=lambda _path: library)
    runtime.open()
    runtime.connect_module(17)
    runtime.create_logical_link(17, 600)

    with pytest.raises(DPduApiError, match="does not export PDUConnect"):
        runtime.connect_logical_link(17, 93)

    runtime.close()



def test_all_d_pdu_runtime_structures_use_iso_byte_packing():
    structures = (
        _PduItem,
        _PduModuleData,
        _PduModuleItem,
        _PduPinData,
        _PduResourceData,
        _PduResourceIdItemData,
        _PduResourceIdItem,
        _PduResourceStatusData,
        _PduResourceStatusItem,
        _PduFlagData,
        _PduParamItem,
        _PduResourceConflictData,
        _PduResourceConflictItem,
    )
    assert all(structure._pack_ == 1 for structure in structures)
