"""Restrictive-by-default policy for vehicle communication."""
from dataclasses import dataclass

@dataclass
class SafetyPolicy:
    allow_transmit: bool = False
    allow_write_services: bool = False
    allow_programming: bool = False

    def authorize_transmit(self, operation: str, confirmed: bool = False) -> None:
        if not self.allow_transmit:
            raise PermissionError(f"Transmit disabled: {operation}")
        if not confirmed:
            raise PermissionError("Explicit operator confirmation required")

    def authorize_write(self, operation: str, confirmed: bool = False) -> None:
        if not self.allow_write_services:
            raise PermissionError(f"Write/service operation disabled: {operation}")
        if not confirmed:
            raise PermissionError("Explicit operator confirmation required")

    def authorize_programming(self, ecu_verified: bool, backup_verified: bool,
                              stable_power: bool, confirmed: bool = False) -> None:
        if not self.allow_programming:
            raise PermissionError("Programming disabled by default")
        if not all((ecu_verified, backup_verified, stable_power, confirmed)):
            raise PermissionError("Programming preconditions incomplete")
