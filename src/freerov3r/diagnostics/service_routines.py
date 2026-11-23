"""Guarded service-routine registry and read-only preflight checks.

No vehicle protocol implementation is bundled here. Executors must be registered
explicitly after the exact vehicle, ECU, protocol and procedure are verified.
"""
from dataclasses import asdict, dataclass, field
from typing import Callable

from ..safety import SafetyPolicy


@dataclass(frozen=True)
class ServiceRoutine:
    routine_id: str
    category: str
    target_module: str
    name: str
    description: str = ""
    prerequisites: str = ""
    requires_security_access: bool = False


@dataclass(frozen=True)
class RoutinePreflight:
    routine_id: str
    routine_name: str
    vin: str
    ready: bool
    blockers: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["blockers"] = list(self.blockers)
        return result


class ServiceRoutineManager:
    """Only runs registered routines after explicit compatibility and safety gates."""

    def __init__(self, safety_policy: SafetyPolicy | None = None):
        self.safety_policy = safety_policy or SafetyPolicy()
        self._executors: dict[str, Callable] = {}

    def register_executor(self, routine_id: str, executor: Callable) -> None:
        if not callable(executor):
            raise TypeError("Routine executor must be callable")
        self._executors[str(routine_id)] = executor

    def preflight(
        self,
        routine: ServiceRoutine,
        vin: str | None,
        *,
        vehicle_verified: bool = False,
        module_verified: bool = False,
        protocol_verified: bool = False,
        security_access_verified: bool = False,
        prerequisites_confirmed: bool = False,
    ) -> RoutinePreflight:
        blockers = []
        if not vin:
            blockers.append("No vehicle VIN is selected.")
        if not vehicle_verified:
            blockers.append("Exact vehicle variant and routine compatibility are not verified.")
        if not module_verified:
            blockers.append(f"Target module is not identified and verified: {routine.target_module}.")
        if not protocol_verified:
            blockers.append("Diagnostic addressing and required services are not verified.")
        if routine.requires_security_access and not security_access_verified:
            blockers.append("Required diagnostic security access is not verified.")
        if not prerequisites_confirmed:
            blockers.append("Vehicle-specific safety and operating prerequisites are not confirmed.")
        if routine.routine_id not in self._executors:
            blockers.append("No reviewed vehicle-specific routine executor is registered.")

        return RoutinePreflight(
            routine_id=routine.routine_id,
            routine_name=routine.name,
            vin=vin or "UNASSIGNED",
            ready=not blockers,
            blockers=tuple(blockers),
        )

    def execute(
        self,
        routine: ServiceRoutine,
        vin: str | None,
        *,
        confirmed: bool = False,
        vehicle_verified: bool = False,
        module_verified: bool = False,
        protocol_verified: bool = False,
        security_access_verified: bool = False,
        prerequisites_confirmed: bool = False,
    ):
        """Execute only after all gates pass; default policy denies write services."""
        check = self.preflight(
            routine,
            vin,
            vehicle_verified=vehicle_verified,
            module_verified=module_verified,
            protocol_verified=protocol_verified,
            security_access_verified=security_access_verified,
            prerequisites_confirmed=prerequisites_confirmed,
        )
        if not check.ready:
            raise PermissionError("Routine blocked: " + " ".join(check.blockers))
        self.safety_policy.authorize_write(routine.name, confirmed=confirmed)
        executor = self._executors[routine.routine_id]
        return executor(routine=routine, vin=vin)
