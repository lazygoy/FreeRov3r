def test_responsive_banner_remains_available_from_app_module():
    from freerov3r.app import ResponsiveBanner as app_banner
    from freerov3r.responsive_banner import ResponsiveBanner

    assert app_banner is ResponsiveBanner


def test_vehicle_history_tab_remains_available_from_app_module():
    from freerov3r.app import VehicleHistoryTab as app_history_tab
    from freerov3r.vehicle_history_tab import VehicleHistoryTab

    assert app_history_tab is VehicleHistoryTab
