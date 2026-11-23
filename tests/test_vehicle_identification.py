from freerov3r.diagnostics.vehicle_identification import (
    identify_vehicle, model_year_from_vin, validate_vin,
)


def test_vin_validation_and_year():
    assert validate_vin("SALAE25458A444549") == "SALAE25458A444549"
    assert model_year_from_vin("SALAE25458A444549") == 2008


def test_lr3_vin_suggests_lr3_profile():
    result = identify_vehicle("SALAE25458A444549")
    assert result["profile_id"] == "land_rover_l319"
    assert result["variant_id"] == "lr3"
    assert result["model_year"] == 2008
    assert result["confidence"] == "probable"


def test_lr4_vin_suggests_lr4_profile():
    result = identify_vehicle("SALAG2V62GA780105")
    assert result["profile_id"] == "land_rover_l319"
    assert result["variant_id"] == "lr4"
    assert result["model_year"] == 2016


def test_unknown_vehicle_stays_generic():
    result = identify_vehicle("1HGCM82633A004352")
    assert result["valid"] is True
    assert result["profile_id"] == "generic"


def test_invalid_vin_is_not_classified():
    result = identify_vehicle("SAL")
    assert result["valid"] is False
    assert result["profile_id"] == "generic"
