"""Explicit boundaries between operator diagnostics and engineering workspaces."""

from enum import Enum


class WorkspaceMode(str, Enum):
    DIAGNOSTICS = "diagnostics"
    RESEARCH = "research"


SHARED_TABS = frozenset({"Sensors", "Graph", "Settings"})
DIAGNOSTIC_TABS = frozenset({
    "OBD-II",
    "Modules",
    "Special Functions",
    "Topology",
    "Solutions",
    "Vehicle History",
})
DEVELOPMENT_TABS = frozenset({
    "Capture",
    "D-PDU",
    "Research",
    "Tuning",
    "Wiring Diagrams",
})


def tab_is_visible(tab_name: str, mode: WorkspaceMode) -> bool:
    """Return whether a tab belongs in the selected top-level workspace."""
    if tab_name in SHARED_TABS:
        return True
    if mode is WorkspaceMode.RESEARCH:
        return tab_name in DEVELOPMENT_TABS
    return tab_name in DIAGNOSTIC_TABS


def visible_tab_names(tab_names, mode: WorkspaceMode) -> tuple[str, ...]:
    """Filter tab names while preserving their existing order."""
    return tuple(name for name in tab_names if tab_is_visible(name, mode))
