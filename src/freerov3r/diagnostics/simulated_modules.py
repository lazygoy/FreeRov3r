"""Synthetic module/DTC model for UI development only.

Nothing in this module sends CAN or diagnostic requests to a vehicle.
The module inventory and DTCs are illustrative fixtures, not verified L319 data.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SimulatedDTC:
    code: str
    description: str
    status: str = "Stored"
    severity: str = "Information"


@dataclass
class SimulatedModule:
    code: str
    name: str
    category: str
    dtcs: list[SimulatedDTC] = field(default_factory=list)
    available: bool = True
    last_scan: str | None = None

    def scan(self):
        self.last_scan = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return list(self.dtcs)


class SimulatedModuleNetwork:
    """A deterministic, in-memory example network with mutable DTC state."""

    def __init__(self):
        self.modules = [
            SimulatedModule("ECM", "Engine Control Module", "Powertrain", [
                SimulatedDTC("P0420", "Catalyst system efficiency below threshold (Bank 1)", "Stored", "Warning"),
                SimulatedDTC("P0113", "Intake air temperature sensor circuit high", "Pending", "Warning"),
            ]),
            SimulatedModule("TCM", "Transmission Control Module", "Powertrain", [
                SimulatedDTC("P0705", "Transmission range sensor circuit malfunction", "Stored", "Warning"),
            ]),
            SimulatedModule("ABS", "Anti-lock Braking System", "Chassis", [
                SimulatedDTC("C003A", "Right rear wheel speed sensor circuit", "Stored", "Warning"),
            ]),
            SimulatedModule("EPB", "Electronic Parking Brake", "Chassis", [
                SimulatedDTC("C1A43", "Parking brake actuator performance", "Intermittent", "Warning"),
            ]),
            SimulatedModule("SASM", "Steering Angle Sensor Module", "Chassis"),
            SimulatedModule("RLM", "Ride Level / Suspension Module", "Chassis", [
                SimulatedDTC("C1A20", "Air suspension reservoir pressure plausibility", "Stored", "Warning"),
            ]),
            SimulatedModule("BCM", "Body Control Module", "Body"),
            SimulatedModule("DDM", "Driver Door Module", "Body", [
                SimulatedDTC("B11DB", "Driver door latch switch signal", "Intermittent", "Information"),
            ]),
            SimulatedModule("PDM", "Passenger Door Module", "Body"),
            SimulatedModule("RCM", "Restraints Control Module", "Safety"),
            SimulatedModule("HVAC", "Climate Control Module", "Climate", [
                SimulatedDTC("B1B77", "Cabin temperature sensor signal", "Stored", "Information"),
            ]),
            SimulatedModule("PAM", "Parking Aid Module", "Driver Assistance"),
            SimulatedModule("CJB", "Central Junction Box", "Body"),
            SimulatedModule("GWM", "Gateway Module", "Network"),
            SimulatedModule("IC", "Instrument Cluster", "Information"),
            SimulatedModule("AAM", "Audio Amplifier Module", "Infotainment"),
            SimulatedModule("NAV", "Navigation Module", "Infotainment"),
        ]
        self._by_code = {module.code: module for module in self.modules}

    def scan_module(self, code: str) -> SimulatedModule:
        module = self._by_code[code]
        module.scan()
        return module

    def scan_all(self) -> list[SimulatedModule]:
        for module in self.modules:
            module.scan()
        return list(self.modules)

    def clear_code(self, module_code: str, dtc_code: str) -> bool:
        module = self._by_code[module_code]
        before = len(module.dtcs)
        module.dtcs = [dtc for dtc in module.dtcs if dtc.code != dtc_code]
        return len(module.dtcs) != before

    def clear_module(self, module_code: str) -> int:
        module = self._by_code[module_code]
        count = len(module.dtcs)
        module.dtcs.clear()
        return count

    def clear_all(self) -> int:
        return sum(self.clear_module(module.code) for module in self.modules)

    def get_module(self, code: str) -> SimulatedModule:
        return self._by_code[code]
