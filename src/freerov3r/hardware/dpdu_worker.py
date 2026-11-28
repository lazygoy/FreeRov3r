"""Thread-owned D-PDU receive worker.

The worker owns the complete D-PDU API lifecycle on one thread. Starting it is
an explicit operator action; the configuration also requires an explicit
physical-connection authorization flag because PDUConnect activates the
selected vehicle-interface resource.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from .dpdu_discovery import DPduModuleRegistration
from .dpdu_receive import (
    DPduEvent,
    DPduReceiveRuntime,
    PDU_IT_STATUS,
    PDU_COPST_CANCELLED,
    PDU_COPST_FINISHED,
)
from .dpdu_runtime import DPduLiveModule


@dataclass(frozen=True)
class DPduWorkerConfig:
    """All identifiers required to activate one explicitly selected D-PDU path."""

    registration: DPduModuleRegistration
    module_handle: int
    resource_id: int
    response_mask: bytes
    response_pattern: bytes
    operator_confirmed_physical_connection: bool = False
    com_params_uint32: tuple[tuple[int, int], ...] = ()
    unique_response_ids: tuple[int, ...] = ()
    acceptance_id: int = 1
    poll_interval_seconds: float = 0.01
    batch_size: int = 64
    source: str = "dpdu"

    def __post_init__(self) -> None:
        if not self.registration.library_file:
            raise ValueError("A selected D-PDU API registration is required")
        if not 0 <= int(self.module_handle) <= 0xFFFFFFFF:
            raise ValueError("module_handle must be uint32")
        if not 0 <= int(self.resource_id) <= 0xFFFFFFFF:
            raise ValueError("resource_id must be uint32")
        if not self.response_mask or len(self.response_mask) != len(self.response_pattern):
            raise ValueError("A matching non-empty response mask and pattern are required")
        if not self.operator_confirmed_physical_connection:
            raise ValueError(
                "Physical connection requires explicit operator confirmation"
            )
        if not 0.001 <= float(self.poll_interval_seconds) <= 1.0:
            raise ValueError("poll_interval_seconds must be between 0.001 and 1.0")
        if not 1 <= int(self.batch_size) <= 4096:
            raise ValueError("batch_size must be between 1 and 4096")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        for param_id, value in self.com_params_uint32:
            if not 0 <= int(param_id) <= 0xFFFFFFFF:
                raise ValueError("ComParam IDs must be uint32")
            if not 0 <= int(value) <= 0xFFFFFFFF:
                raise ValueError("ComParam values must be uint32")


RuntimeFactory = Callable[[DPduModuleRegistration], DPduReceiveRuntime]


def _run_diagnostic_session(
    config: DPduWorkerConfig,
    stop_event: threading.Event,
    *,
    runtime_factory: RuntimeFactory = DPduReceiveRuntime,
    emit_events: Callable[[list], None],
    emit_status: Callable[[str], None],
) -> None:
    """Run every D-PDU call on the caller's thread and always close the runtime."""
    runtime = runtime_factory(config.registration)
    pending = []
    primary_error: Exception | None = None
    try:
        emit_status("Loading selected D-PDU API and enumerating modules")
        modules: list[DPduLiveModule] = runtime.open()
        selected = next(
            (module for module in modules
             if module.module_handle == int(config.module_handle)),
            None,
        )
        if selected is None:
            raise RuntimeError(
                f"Selected module handle {config.module_handle} is not in the live inventory"
            )

        emit_status("Initializing selected MVCI module")
        runtime.connect_module(config.module_handle)
        link = runtime.create_logical_link(config.module_handle, config.resource_id)
        cll_handle = int(link.logical_link_handle)

        for param_id, value in config.com_params_uint32:
            runtime.set_com_param_uint32(
                config.module_handle, cll_handle, param_id, value
            )

        # This is the physical activation boundary. The config cannot be
        # constructed without an explicit operator-confirmation flag.
        emit_status("Connecting selected D-PDU logical link")
        runtime.connect_logical_link(config.module_handle, cll_handle)
        cop_handle = runtime.start_receive_only(
            config.module_handle,
            cll_handle,
            response_mask=config.response_mask,
            response_pattern=config.response_pattern,
            unique_response_ids=config.unique_response_ids,
            acceptance_id=config.acceptance_id,
        )
        emit_status("Receiving protocol-level diagnostic events")

        while not stop_event.is_set():
            event: DPduEvent | None = runtime.get_next_event(
                config.module_handle, cll_handle
            )
            if event is None:
                if pending:
                    emit_events(pending)
                    pending = []
                stop_event.wait(config.poll_interval_seconds)
                continue

            pending.append(event.to_capture_event(
                config.module_handle, cll_handle, source=config.source
            ))
            if len(pending) >= config.batch_size:
                emit_events(pending)
                pending = []

            if (
                event.item_type == PDU_IT_STATUS
                and event.status_code in (PDU_COPST_FINISHED, PDU_COPST_CANCELLED)
            ):
                break

        if pending:
            emit_events(pending)
        emit_status("D-PDU receive session stopping")
    except Exception as exc:
        primary_error = exc
        raise
    finally:
        try:
            runtime.close()
        except Exception as cleanup_error:
            if primary_error is None:
                raise
            emit_status(f"D-PDU cleanup also failed: {cleanup_error}")


class DPduDiagnosticWorker(QThread):
    """Dedicated QThread that exclusively owns a D-PDU runtime session."""

    diagnostic_events = Signal(object)
    status = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: DPduWorkerConfig,
        *,
        runtime_factory: RuntimeFactory = DPduReceiveRuntime,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._runtime_factory = runtime_factory
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Request cooperative shutdown; the worker performs API cleanup itself."""
        self._stop_event.set()

    def run(self) -> None:
        try:
            _run_diagnostic_session(
                self.config,
                self._stop_event,
                runtime_factory=self._runtime_factory,
                emit_events=self.diagnostic_events.emit,
                emit_status=self.status.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
