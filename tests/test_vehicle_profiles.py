from freerov3r.vehicle_profiles.registry import VehicleProfileRegistry


def test_registry_includes_generic_core_and_l319_package():
    registry = VehicleProfileRegistry()
    assert registry.get("generic").profile_id == "generic"
    l319 = registry.get("land_rover_l319")
    assert l319.make == "Land Rover"
    assert "l319_wiring_reference" in l319.capabilities


def test_unknown_profile_falls_back_to_generic():
    registry = VehicleProfileRegistry()
    assert registry.get("not-installed").profile_id == "generic"
