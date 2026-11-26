"""User-configured sensor alert threshold helpers."""
from math import isfinite


def normalize_sensor_thresholds(config):
    """Return a safe, disabled-by-default threshold configuration."""
    if not isinstance(config, dict):
        config = {}
    values = {}
    for key in ("minimum", "maximum"):
        value = config.get(key)
        if value is None or isinstance(value, bool):
            values[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float("nan")
        values[key] = number if isfinite(number) else None
    minimum, maximum = values["minimum"], values["maximum"]
    if minimum is not None and maximum is not None and minimum >= maximum:
        minimum = maximum = None
    return {"enabled": config.get("enabled") is True, "minimum": minimum, "maximum": maximum}


def evaluate_sensor_threshold(value, config):
    """Return OFF, OK, LOW, or HIGH without inventing vehicle-specific limits."""
    normalized = normalize_sensor_thresholds(config)
    if not normalized["enabled"] or (normalized["minimum"] is None and normalized["maximum"] is None):
        return "OFF"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not isfinite(value):
        return "N/A"
    if normalized["minimum"] is not None and value < normalized["minimum"]:
        return "LOW"
    if normalized["maximum"] is not None and value > normalized["maximum"]:
        return "HIGH"
    return "OK"
