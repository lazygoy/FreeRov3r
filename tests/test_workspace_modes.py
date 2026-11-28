from freerov3r.workspace_modes import WorkspaceMode, tab_is_visible, visible_tab_names


def test_diagnostic_workspace_contains_scan_tool_functions():
    for name in (
        "Sensors", "OBD-II", "Special Functions",
        "Topology", "Graph", "Solutions", "Vehicle History", "Settings",
    ):
        assert tab_is_visible(name, WorkspaceMode.DIAGNOSTICS)


def test_diagnostic_workspace_hides_engineering_tools():
    for name in ("Capture", "Modules", "D-PDU", "Research", "Tuning", "Wiring Diagrams"):
        assert not tab_is_visible(name, WorkspaceMode.DIAGNOSTICS)


def test_development_workspace_exposes_engineering_tools():
    for name in (
        "Capture", "Modules", "D-PDU", "Research", "Tuning", "Wiring Diagrams",
        "Sensors", "Graph", "Settings",
    ):
        assert tab_is_visible(name, WorkspaceMode.RESEARCH)


def test_development_workspace_hides_operator_only_scan_pages():
    for name in ("OBD-II", "Special Functions", "Topology", "Solutions", "Vehicle History"):
        assert not tab_is_visible(name, WorkspaceMode.RESEARCH)


def test_shared_vehicle_data_tools_remain_available_in_both_workspaces():
    for name in ("Sensors", "Graph", "Settings"):
        assert tab_is_visible(name, WorkspaceMode.DIAGNOSTICS)
        assert tab_is_visible(name, WorkspaceMode.RESEARCH)


def test_visible_tab_filter_preserves_order_and_workspace_boundaries():
    names = (
        "Capture", "Sensors", "Graph", "Research", "OBD-II",
        "Modules", "Wiring Diagrams", "Settings",
    )
    assert visible_tab_names(names, WorkspaceMode.DIAGNOSTICS) == (
        "Sensors", "Graph", "OBD-II", "Settings"
    )
    assert visible_tab_names(names, WorkspaceMode.RESEARCH) == (
        "Capture", "Sensors", "Graph", "Research", "Modules", "Wiring Diagrams", "Settings"
    )
