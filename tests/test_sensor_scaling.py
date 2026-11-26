import pytest

from freerov3r.sensors.scaling import normalize_values, sample_clock, sample_time
from freerov3r.sensors.models import SensorSample


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


def test_sample_clock_prefers_monotonic_when_all_samples_have_it():
    samples = [
        SensorSample(100.0, "rpm", "RPM", 800, "rpm", "ecu", monotonic_timestamp=5.0),
        SensorSample(101.0, "rpm", "RPM", 900, "rpm", "ecu", monotonic_timestamp=6.0),
    ]
    clock = sample_clock(samples)
    assert clock == "monotonic_timestamp"
    assert [sample_time(item, clock) for item in samples] == [5.0, 6.0]


def test_sample_clock_falls_back_as_a_group_for_legacy_or_imported_samples():
    samples = [
        SensorSample(100.0, "rpm", "RPM", 800, "rpm", "ecu", monotonic_timestamp=5.0),
        SensorSample(101.0, "rpm", "RPM", 900, "rpm", "ecu"),
    ]
    clock = sample_clock(samples)
    assert clock == "timestamp"
    assert [sample_time(item, clock) for item in samples] == [100.0, 101.0]
