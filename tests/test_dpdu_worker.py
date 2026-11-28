from __future__ import annotations

import threading

import pytest

from freerov3r.hardware.dpdu_discovery import DPduModuleRegistration
from freerov3r.hardware.dpdu_receive import DPduEvent, PDU_IT_RESULT
from freerov3r.hardware.dpdu_runtime import DPduLiveModule
from freerov3r.hardware.dpdu_worker import (
    DPduWorkerConfig,
    _run_diagnostic_session,
)


@pytest.fixture
def registration():
    return DPduModuleRegistration(
        short_name="Mock MVCI",
        library_file="mock-pdu.dll",
        module_description_file="mock.mdf",
        cable_description_file="mock.cdf",
    )


def make_config(registration, **overrides):
    values = {
        "registration": registration,
        "module_handle": 17,
        "resource_id": 600,
        "response_mask": b"\\xff",
        "response_pattern": b"\\x62",
        "operator_confirmed_physical_connection": True,
        "com_params_uint32": ((10, 500000),),
        "batch_size": 1,
    }
    values.update(overrides)
    return DPduWorkerConfig(**values)


def test_worker_config_requires_explicit_physical_connection_confirmation(registration):
    with pytest.raises(ValueError, match="explicit operator confirmation"):
        DPduWorkerConfig(
            registration=registration,
            module_handle=17,
            resource_id=600,
            response_mask=b"\\xff",
            response_pattern=b"\\x62",
        )


def test_worker_owns_runtime_lifecycle_and_emits_normalized_events(registration):
    calls = []
    worker_thread_id = threading.get_ident()

    class FakeRuntime:
        def __init__(self, selected_registration):
            assert selected_registration is registration
            calls.append(("construct", threading.get_ident()))
            self.events = [
                DPduEvent(
                    item_type=PDU_IT_RESULT,
                    cop_handle=91,
                    cop_tag=0,
                    timestamp_us=123456,
                    data=b"\\x62\\xf1\\x90",
                    acceptance_id=1,
                    unique_response_identifier=0x7E8,
                )
            ]

        def open(self):
            calls.append(("open", threading.get_ident()))
            return [DPduLiveModule(
                registration_name="Mock MVCI",
                library_file="mock-pdu.dll",
                module_type_id=1,
                module_handle=17,
                module_status=0,
            )]

        def connect_module(self, module_handle):
            calls.append(("module_connect", threading.get_ident(), module_handle))

        def create_logical_link(self, module_handle, resource_id):
            calls.append(("create_link", threading.get_ident(), module_handle, resource_id))
            return type("Link", (), {"logical_link_handle": 44})()

        def set_com_param_uint32(self, module_handle, cll_handle, param_id, value):
            calls.append(("set_param", threading.get_ident(), module_handle, cll_handle, param_id, value))

        def connect_logical_link(self, module_handle, cll_handle):
            calls.append(("connect_link", threading.get_ident(), module_handle, cll_handle))

        def start_receive_only(self, module_handle, cll_handle, **kwargs):
            calls.append(("start_receive", threading.get_ident(), module_handle, cll_handle, kwargs))
            return 91

        def get_next_event(self, module_handle, cll_handle):
            calls.append(("get_event", threading.get_ident(), module_handle, cll_handle))
            return self.events.pop(0) if self.events else None

        def close(self):
            calls.append(("close", threading.get_ident()))

    stop_event = threading.Event()
    emitted = []
    statuses = []

    def emit_events(events):
        emitted.extend(events)
        stop_event.set()

    _run_diagnostic_session(
        make_config(registration),
        stop_event,
        runtime_factory=FakeRuntime,
        emit_events=emit_events,
        emit_status=statuses.append,
    )

    assert [call[0] for call in calls] == [
        "construct", "open", "module_connect", "create_link", "set_param",
        "connect_link", "start_receive", "get_event", "close",
    ]
    assert all(call[1] == worker_thread_id for call in calls)
    assert len(emitted) == 1
    assert emitted[0].source == "dpdu"
    assert emitted[0].payload == b"\\x62\\xf1\\x90"
    assert emitted[0].unique_response_identifier == 0x7E8
    assert "Receiving protocol-level diagnostic events" in statuses


def test_worker_closes_runtime_when_selected_module_is_missing(registration):
    calls = []

    class FakeRuntime:
        def __init__(self, _registration):
            pass

        def open(self):
            return []

        def close(self):
            calls.append("close")

    with pytest.raises(RuntimeError, match="not in the live inventory"):
        _run_diagnostic_session(
            make_config(registration),
            threading.Event(),
            runtime_factory=FakeRuntime,
            emit_events=lambda _events: None,
            emit_status=lambda _status: None,
        )
    assert calls == ["close"]
