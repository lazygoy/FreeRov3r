from freerov3r.sensors.thresholds import evaluate_sensor_threshold, normalize_sensor_thresholds


def test_alerts_are_off_when_no_user_configuration_exists():
    assert evaluate_sensor_threshold(100, {}) == "OFF"
    assert normalize_sensor_thresholds(None) == {"enabled": False, "minimum": None, "maximum": None}


def test_user_minimum_and_maximum_alerts():
    config = {"enabled": True, "minimum": 10, "maximum": 90}
    assert evaluate_sensor_threshold(9.9, config) == "LOW"
    assert evaluate_sensor_threshold(90.1, config) == "HIGH"
    assert evaluate_sensor_threshold(50, config) == "OK"


def test_one_sided_thresholds_are_supported():
    assert evaluate_sensor_threshold(4, {"enabled": True, "minimum": 5}) == "LOW"
    assert evaluate_sensor_threshold(6, {"enabled": True, "maximum": 5}) == "HIGH"


def test_disabled_or_invalid_thresholds_never_alert():
    assert evaluate_sensor_threshold(1, {"enabled": False, "minimum": 5}) == "OFF"
    assert evaluate_sensor_threshold(1, {"enabled": True, "minimum": 8, "maximum": 3}) == "OFF"
    assert evaluate_sensor_threshold(float("nan"), {"enabled": True, "minimum": 5}) == "N/A"


def test_threshold_boundaries_are_not_alerts():
    config = {"enabled": True, "minimum": 10, "maximum": 20}
    assert evaluate_sensor_threshold(10, config) == "OK"
    assert evaluate_sensor_threshold(20, config) == "OK"
