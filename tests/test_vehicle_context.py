from freerov3r.core.vehicle.context import (
    L319_PROFILES,
    resolve_vehicle_context,
)


def test_l319_vin_resolves_to_lr4_profile_without_ui_dependencies():
    settings = {
        "current_vin": "SALAN2D4EAA123456",
        "vehicles": {},
    }

    context = resolve_vehicle_context(settings)

    assert context.vin == "SALAN2D4EAA123456"
    assert context.profile_id == "land_rover_l319_lr4"
    assert context.is_l319
    assert settings["vehicles"][context.vin]["identification_confidence"] == "probable"


def test_explicit_generic_profile_is_not_overridden():
    settings = {
        "current_vin": "SALAN2D4EAA123456",
        "vehicles": {
            "SALAN2D4EAA123456": {
                "make": "Land Rover",
                "model": "Discovery 4",
                "profile_id": "generic",
                "profile_selection_explicit": True,
            }
        },
    }

    context = resolve_vehicle_context(settings)

    assert context.profile_id == "generic"
    assert not context.is_l319


def test_manual_l319_profile_is_preserved():
    settings = {
        "current_vin": "SALAN2D4EAA123456",
        "vehicles": {
            "SALAN2D4EAA123456": {
                "profile_id": "land_rover_l319",
                "identification_confidence": "manual",
            }
        },
    }

    context = resolve_vehicle_context(settings)

    assert context.profile_id in L319_PROFILES
    assert context.identification_confidence == "manual"


def test_unknown_vehicle_stays_on_generic_profile():
    settings = {
        "current_vin": "1HGCM82633A004352",
        "vehicles": {},
    }

    context = resolve_vehicle_context(settings)

    assert context.profile_id == "generic"
    assert not context.is_l319


def test_missing_vehicle_settings_are_safe():
    context = resolve_vehicle_context({})

    assert context.vin is None
    assert context.profile_id == "generic"
    assert not context.is_l319
