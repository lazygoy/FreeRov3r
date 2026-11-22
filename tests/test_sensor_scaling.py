import pytest

from freerov3r.sensors.scaling import normalize_values


def test_normalize_values_maps_each_sensor_to_full_range():
    scaled, low, high = normalize_values([100, 150, 200])
    assert scaled == [0.0, 50.0, 100.0]
    assert (low, high) == (100.0, 200.0)


def test_normalize_values_handles_constant_signal():
    scaled, low, high = normalize_values([12, 12, 12])
    assert scaled == [50.0, 50.0, 50.0]
    assert (low, high) == (12.0, 12.0)


def test_normalize_values_rejects_non_finite_samples():
    scaled, low, high = normalize_values([1, float("nan"), 3])
    assert scaled == [0.0, 100.0]
    assert (low, high) == (1.0, 3.0)


def test_normalize_values_empty_input():
    assert normalize_values([]) == ([], 0.0, 0.0)
