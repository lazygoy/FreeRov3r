from freerov3r.sensors.demo import generate_lr4_demo_samples


def test_lr4_demo_generates_repeatable_multisensor_history():
    first = generate_lr4_demo_samples(duration_seconds=10, sample_rate_hz=2)
    second = generate_lr4_demo_samples(duration_seconds=10, sample_rate_hz=2)

    assert len(first) == 11 * 8
    assert [(s.sensor_id, s.value) for s in first] == [
        (s.sensor_id, s.value) for s in second
    ]
    assert {s.name for s in first} >= {
        "Engine speed", "Coolant temperature", "Mass air flow",
        "Throttle position", "Short-term fuel trim bank 1",
        "Short-term fuel trim bank 2",
    }
    assert all(s.source == "simulated" for s in first)
    assert all(s.metadata["demo"] is True for s in first)
    assert all("not vehicle measurements" in s.metadata["warning"] for s in first)


def test_lr4_demo_rejects_invalid_duration_and_rate():
    import pytest

    with pytest.raises(ValueError):
        generate_lr4_demo_samples(duration_seconds=0)
    with pytest.raises(ValueError):
        generate_lr4_demo_samples(sample_rate_hz=0)


def test_lr4_demo_timestamps_advance_consistently():
    samples = generate_lr4_demo_samples(duration_seconds=2, sample_rate_hz=2)
    rpm = [s for s in samples if s.sensor_id == "demo.engine.rpm"]
    assert [s.monotonic_timestamp for s in rpm] == [10_000.0, 10_000.5, 10_001.0, 10_001.5, 10_002.0]
