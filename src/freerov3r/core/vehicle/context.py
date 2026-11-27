"""Pure vehicle identity and profile-resolution context.

This module has no Qt dependencies so Diagnostic and Research services can
resolve the same vehicle context without depending on MainWindow.
"""
from dataclasses import dataclass, field

from ...diagnostics.vehicle_identification import identify_vehicle


L319_PROFILES = frozenset({
    "land_rover_l319",
    "land_rover_l319_lr3",
    "land_rover_l319_lr4",
})


@dataclass(frozen=True)
class VehicleContext:
    vin: str | None
    profile_id: str
    vehicle: dict = field(default_factory=dict)
    identification_confidence: str = "unknown"

    @property
    def is_l319(self) -> bool:
        return self.profile_id in L319_PROFILES


def _suggest_l319_profile(vehicle: dict) -> str:
    make = str(vehicle.get("make") or "").strip().lower()
    model = str(vehicle.get("model") or "").strip().lower()
    try:
        year = int(vehicle.get("model_year"))
    except (TypeError, ValueError):
        year = None

    if (not make and not model) or ("land rover" in make and not model):
        return "land_rover_l319"
    if "land rover" not in make:
        return "generic"
    if not ("discovery" in model or "lr3" in model or "lr4" in model):
        return "generic"
    if "discovery 3" in model or "lr3" in model or (year and 2005 <= year <= 2009):
        return "land_rover_l319_lr3"
    if "discovery 4" in model or "lr4" in model or (year and 2010 <= year <= 2016):
        return "land_rover_l319_lr4"
    return "land_rover_l319"


def resolve_vehicle_context(settings: dict) -> VehicleContext:
    """Resolve VIN and profile from persisted settings without touching the UI."""
    settings = settings if isinstance(settings, dict) else {}
    vin = settings.get("current_vin")
    vehicles = settings.get("vehicles", {})
    active = (
        vehicles.get(vin, {})
        if vin and isinstance(vehicles, dict) and vin in vehicles
        else settings.get("active_vehicle", {})
    )
    active = dict(active or {})

    if vin and not active.get("profile_id"):
        identification = identify_vehicle(vin)
        active.update({
            "make": identification.get("make") or active.get("make", ""),
            "model": identification.get("model") or active.get("model", ""),
            "model_year": identification.get("model_year") or active.get("model_year"),
            "profile_id": identification.get("profile_id", "generic"),
            "variant_id": identification.get("variant_id"),
            "identification_confidence": identification.get("confidence", "unknown"),
        })
        if isinstance(vehicles, dict):
            vehicles[vin] = active.copy()

    profile_id = active.get("profile_id", "generic")
    if profile_id == "generic" and not active.get("profile_selection_explicit"):
        suggested = _suggest_l319_profile(active)
        if suggested != "generic":
            profile_id = suggested
            active["profile_id"] = suggested

    return VehicleContext(
        vin=vin,
        profile_id=profile_id,
        vehicle={**active, "vin": vin},
        identification_confidence=str(active.get("identification_confidence", "unknown")),
    )
