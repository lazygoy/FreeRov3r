"""VIN-derived vehicle profile context and workspace gating."""

from .diagnostics.vehicle_identification import identify_vehicle
from .diagnostics.simulated_modules import SimulatedModuleNetwork


def update_vehicle_context(window):
vin = window.settings.get("current_vin")
vehicles = window.settings.get("vehicles", {})
active = vehicles.get(vin, {}) if vin and vin in vehicles else window.settings.get("active_vehicle", {})
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
    vehicles[vin] = active.copy()
profile_id = active.get("profile_id", "generic")
if profile_id == "generic" and not active.get("profile_selection_explicit"):
    make = str(active.get("make") or "").strip().lower()
    model = str(active.get("model") or "").strip().lower()
    year = active.get("model_year")
    if (not make and not model) or ("land rover" in make and not model):
        profile_id = "land_rover_l319"
    elif "land rover" in make and (
        "discovery" in model or "lr3" in model or "lr4" in model
    ):
        if "discovery 3" in model or "lr3" in model or (year and 2005 <= year <= 2009):
            profile_id = "land_rover_l319_lr3"
        elif "discovery 4" in model or "lr4" in model or (year and 2010 <= year <= 2016):
            profile_id = "land_rover_l319_lr4"
        else:
            profile_id = "land_rover_l319"
    if profile_id != "generic":
        active["profile_id"] = profile_id
window.active_vehicle_profile = window.vehicle_profiles.get(profile_id)
window.sensor_capture.vehicle_context = {**active, "vin": vin}
l319_enabled = profile_id in {
    "land_rover_l319", "land_rover_l319_lr3", "land_rover_l319_lr4"
}
l319_tabs = {"Special Functions", "Topology", "Wiring Diagrams"}
for index in range(window.tabs.count()):
    tab_name = window.tabs.tabText(index)
    if tab_name in l319_tabs:
        window.tabs.setTabEnabled(index, l319_enabled)
        window.tabs.setTabToolTip(
            index,
            "" if l319_enabled else
            "VIN identification indicates a vehicle outside the supported L319 family. Generic OBD-II/CAN tools remain available."
        )

if vin and hasattr(window, "modules_tab"):
    network = window.module_networks.setdefault(vin, SimulatedModuleNetwork())
    window.modules_tab.set_network(network)
    if hasattr(window, "network_tab"):
        window.network_tab.set_network(network)
    if hasattr(window, "solutions_tab"):
        window.solutions_tab.set_network(network)

if hasattr(window, "graph_tab"):
    window.graph_tab.set_vehicle_vin(vin)
if hasattr(window, "special_functions_tab"):
    window.special_functions_tab.refresh()
window._refresh_workspace_header()
