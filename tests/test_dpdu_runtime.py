import ctypes

import pytest

from freerov3r.hardware.dpdu_discovery import DPduModuleRegistration
from freerov3r.hardware.dpdu_runtime import (
    DPduApiError,
    DPduApiRuntime,
    _PduItem,
    _PduModuleData,
    _PduModuleItem,
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
