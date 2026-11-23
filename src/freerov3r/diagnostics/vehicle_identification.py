"""Offline VIN validation and conservative vehicle identification.

Only the North American L319 model-year windows are classified automatically.
Unknown or ambiguous VINs remain on the generic OBD-II/CAN profile.
"""
import re

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
YEAR_CODES = {
    **{str(n): 2001 + n - 1 for n in range(1, 10)},
    **dict(zip("ABCDEFGHJKLMNPRSTVWXY", range(2010, 2030))),
}


def validate_vin(value):
    value = str(value or "").strip().upper()
    return value if VIN_RE.fullmatch(value) else None


def model_year_from_vin(vin):
    valid = validate_vin(vin)
    if not valid:
        return None
    code = valid[9]
    year = YEAR_CODES.get(code)
    if year is None:
        return None
    # The code repeats every 30 years. For current production software, keep
    # the result in the 1981-2039 VIN era and let manufacturer data disambiguate.
    return year


def identify_vehicle(vin):
    """Return a conservative profile suggestion; never infer fitment from WMI alone."""
    valid = validate_vin(vin)
    if not valid:
        return {
            "vin": str(vin or "").strip().upper(),
            "valid": False,
            "make": None,
            "model": None,
            "model_year": None,
            "profile_id": "generic",
            "confidence": "unknown",
            "reason": "VIN must contain 17 valid characters.",
        }

    year = model_year_from_vin(valid)
    if valid[:3] == "SAL" and valid[3] == "A" and year is not None:
        if 2005 <= year <= 2009:
            return {
                "vin": valid, "valid": True, "make": "Land Rover",
                "model": "LR3 / Discovery 3", "model_year": year,
                "profile_id": "land_rover_l319_lr3", "confidence": "probable",
                "reason": "SAL manufacturer code, Discovery model-range character A, and LR3 model-year window.",
            }
        if 2010 <= year <= 2016:
            return {
                "vin": valid, "valid": True, "make": "Land Rover",
                "model": "LR4 / Discovery 4", "model_year": year,
                "profile_id": "land_rover_l319_lr4", "confidence": "probable",
                "reason": "SAL manufacturer code, Discovery model-range character A, and LR4 model-year window.",
            }

    return {
        "vin": valid, "valid": True,
        "make": "Land Rover" if valid[:3] == "SAL" else None,
        "model": None, "model_year": year, "profile_id": "generic",
        "confidence": "unknown",
        "reason": "VIN syntax is valid, but no installed vehicle profile matches this VIN pattern.",
    }
