from freerov3r.workspace_modes import WorkspaceMode, tab_is_visible, visible_tab_names


def test_capture_is_shared_between_diagnostic_and_research_workspaces():
    assert tab_is_visible("Capture", WorkspaceMode.DIAGNOSTICS)
    assert tab_is_visible("Capture", WorkspaceMode.RESEARCH)


def test_research_tab_is_isolated_from_diagnostic_workspace():
    assert not tab_is_visible("Research", WorkspaceMode.DIAGNOSTICS)
    assert tab_is_visible("Research", WorkspaceMode.RESEARCH)


def test_diagnostic_tabs_remain_in_diagnostic_workspace():
    for name in ("Graph", "OBD-II", "Modules", "Topology", "Wiring Diagrams"):
        assert tab_is_visible(name, WorkspaceMode.DIAGNOSTICS)
        assert not tab_is_visible(name, WorkspaceMode.RESEARCH)


def test_visible_tab_filter_preserves_order():
    names = ("Capture", "Graph", "Research", "OBD-II")
    assert visible_tab_names(names, WorkspaceMode.DIAGNOSTICS) == (
        "Capture", "Graph", "OBD-II"
    )
    assert visible_tab_names(names, WorkspaceMode.RESEARCH) == (
        "Capture", "Research"
    )
