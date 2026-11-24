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

    def to_dict(self) -> dict:
        """Return the mutable simulator state in a versioned JSON-safe format."""
        return {
            "schema_version": 1,
            "modules": [
                {
                    "code": module.code,
                    "last_scan": module.last_scan,
                    "dtcs": [
                        {
                            "code": dtc.code,
                            "description": dtc.description,
                            "status": dtc.status,
                            "severity": dtc.severity,
                        }
                        for dtc in module.dtcs
                    ],
                }
                for module in self.modules
            ],
        }

    def load_state(self, path) -> bool:
        """Load saved DTC state for this VIN; retain defaults on invalid files."""
        import json
        from pathlib import Path

        state_path = Path(path)
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                return False
            saved_modules = data.get("modules")
            if not isinstance(saved_modules, list):
                return False

            saved_by_code = {
                item.get("code"): item for item in saved_modules
                if isinstance(item, dict) and isinstance(item.get("code"), str)
            }
            restored_state = {}
            for module in self.modules:
                saved = saved_by_code.get(module.code)
                if saved is None:
                    continue
                dtcs = saved.get("dtcs", [])
                if not isinstance(dtcs, list):
                    return False
                restored = []
                for item in dtcs:
                    if not isinstance(item, dict) or not item.get("code"):
                        return False
                    restored.append(SimulatedDTC(
                        code=str(item["code"]),
                        description=str(item.get("description", "")),
                        status=str(item.get("status", "Stored")),
                        severity=str(item.get("severity", "Information")),
                    ))
                last_scan = saved.get("last_scan")
                if last_scan is not None and not isinstance(last_scan, str):
                    return False
                restored_state[module.code] = (restored, last_scan)

            # Apply only after the complete file has passed validation.
            for code, (dtcs, last_scan) in restored_state.items():
                module = self._by_code[code]
                module.dtcs = dtcs
                module.last_scan = last_scan
            return True
        except (OSError, ValueError, TypeError):
            return False

    def save_state(self, path) -> None:
        """Atomically save mutable simulator state to a VIN-scoped JSON file."""
        import json
        from pathlib import Path

        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(state_path)

    def get_module(self, code: str) -> SimulatedModule:
        return self._by_code[code]
