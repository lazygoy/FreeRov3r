"""Workspace boundaries for the FreeRov3r desktop application.

Capture is shared infrastructure. Research-only analysis is kept out of the
normal diagnostic navigation so exploratory CAN work is not confused with
verified vehicle diagnostics.
"""
from enum import Enum


class WorkspaceMode(str, Enum):
    DIAGNOSTICS = "diagnostics"
    RESEARCH = "research"


SHARED_TABS = frozenset({"Capture"})
RESEARCH_TABS = frozenset({"Research"})


def tab_is_visible(tab_name: str, mode: WorkspaceMode) -> bool:
    """Return whether a tab belongs in the selected top-level workspace."""
    if tab_name in SHARED_TABS:
        return True
    if mode is WorkspaceMode.RESEARCH:
        return tab_name in RESEARCH_TABS
    return tab_name not in RESEARCH_TABS


def visible_tab_names(tab_names, mode: WorkspaceMode) -> tuple[str, ...]:
    """Filter tab names while preserving their existing order."""
    return tuple(name for name in tab_names if tab_is_visible(name, mode))
