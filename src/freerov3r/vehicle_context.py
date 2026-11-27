"""VIN-derived vehicle profile context and workspace gating."""

from .diagnostics.simulated_modules import SimulatedModuleNetwork
from .core.vehicle.context import resolve_vehicle_context


def update_vehicle_context(window):
    context = resolve_vehicle_context(window.settings)
    vin = context.vin
    active = context.vehicle
    profile_id = context.profile_id
    window.active_vehicle_profile = window.vehicle_profiles.get(profile_id)
    window.sensor_capture.vehicle_context = active
    l319_enabled = context.is_l319
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

    if hasattr(window, "modules_tab"):
        window.modules_tab.set_vehicle_context(context)
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
