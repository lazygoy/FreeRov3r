"""Vehicle profile registry with third-party Python entry-point support."""
from dataclasses import dataclass, field
from importlib.metadata import entry_points


@dataclass
class VehicleProfile:
    profile_id: str
    display_name: str
    make: str = ""
    model: str = ""
    year_start: int | None = None
    year_end: int | None = None
    description: str = ""
    capabilities: set[str] = field(default_factory=set)
    module: object | None = None


class VehicleProfileRegistry:
    """Loads built-in profiles and optional plugins installed as Python packages.

    Third-party packages register an entry point in the
    'freerov3r.vehicle_profiles' group. The entry point may resolve to a
    VehicleProfile instance or a zero-argument factory returning one.
    """

    ENTRY_POINT_GROUP = "freerov3r.vehicle_profiles"

    def __init__(self):
        self._profiles = {
            "generic": VehicleProfile(
                profile_id="generic",
                display_name="Generic OBD-II / CAN",
                description="Standardized OBD-II and general CAN capture tools.",
                capabilities={"can_capture", "obd2", "pid_monitoring", "graphing", "logging"},
            )
        }
        from .l319 import L319Profile
        self.register(L319Profile())
        self.plugin_errors = []
        self.load_plugins()

    def register(self, profile):
        if not isinstance(profile, VehicleProfile):
            raise TypeError("Vehicle profile plugin must provide a VehicleProfile")
        if not profile.profile_id or profile.profile_id == "generic":
            raise ValueError("Vehicle profile must have a unique non-generic profile_id")
        self._profiles[profile.profile_id] = profile

    def load_plugins(self):
        try:
            discovered = entry_points()
            selected = discovered.select(group=self.ENTRY_POINT_GROUP) if hasattr(discovered, "select") else discovered.get(self.ENTRY_POINT_GROUP, [])
            for entry in selected:
                try:
                    factory = entry.load()
                    profile = factory() if callable(factory) else factory
                    self.register(profile)
                except Exception as exc:
                    self.plugin_errors.append(f"{entry.name}: {exc}")
        except Exception as exc:
            self.plugin_errors.append(str(exc))

    def get(self, profile_id):
        return self._profiles.get(profile_id, self._profiles["generic"])

    def all(self):
        return list(self._profiles.values())
