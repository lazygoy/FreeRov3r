import pytest

from freerov3r.diagnostics.service_routines import (
    ServiceRoutine,
    ServiceRoutineManager,
)
from freerov3r.safety import SafetyPolicy


def sample_routine():
    return ServiceRoutine(
        routine_id="parking-brake::service-mode",
        category="Parking Brake",
        target_module="Electronic parking-brake module",
        name="Parking brake service mode",
    )


def test_preflight_blocks_catalog_entry_without_vin_or_verified_support():
    result = ServiceRoutineManager().preflight(sample_routine(), vin=None)

    assert not result.ready
    assert result.vin == "UNASSIGNED"
    assert any("VIN" in item for item in result.blockers)
    assert any("executor" in item for item in result.blockers)


def test_execute_is_denied_by_default_even_with_registered_executor():
    called = []
    manager = ServiceRoutineManager()
    routine = sample_routine()
    manager.register_executor(routine.routine_id, lambda **kwargs: called.append(kwargs))

    with pytest.raises(PermissionError, match="Write/service operation disabled"):
        manager.execute(
            routine,
            "SALXXXXXXXXXXXX1",
            confirmed=True,
            vehicle_verified=True,
            module_verified=True,
            protocol_verified=True,
            prerequisites_confirmed=True,
        )

    assert called == []


def test_executor_requires_every_gate_and_explicit_policy_enablement():
    called = []
    manager = ServiceRoutineManager(SafetyPolicy(allow_write_services=True))
    routine = sample_routine()
    manager.register_executor(routine.routine_id, lambda **kwargs: called.append(kwargs) or "done")

    with pytest.raises(PermissionError, match="Routine blocked"):
        manager.execute(routine, "SALXXXXXXXXXXXX1", confirmed=True)

    result = manager.execute(
        routine,
        "SALXXXXXXXXXXXX1",
        confirmed=True,
        vehicle_verified=True,
        module_verified=True,
        protocol_verified=True,
        prerequisites_confirmed=True,
    )

    assert result == "done"
    assert len(called) == 1
