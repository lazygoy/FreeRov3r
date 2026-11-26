from freerov3r.sensors.analysis import summarize_sensor_samples
from freerov3r.sensors.models import SensorSample


def sample(sensor_id, value, stamp, *, mono=None, quality="valid"):
    return SensorSample(timestamp=stamp, sensor_id=sensor_id, name=sensor_id.upper(),
                        value=value, unit="°C", source="ecu", quality=quality,
                        monotonic_timestamp=mono)


def test_summary_reports_current_range_average_rate_and_age():
    samples = [sample("coolant", 80, 10, mono=1), sample("coolant", 90, 11, mono=2),
               sample("coolant", 100, 12, mono=3)]
    result, = summarize_sensor_samples(samples, now=4)
    assert (result.current, result.minimum, result.average, result.maximum) == (100, 80, 90, 100)
    assert result.rate_hz == 1 and result.age_seconds == 1
    assert result.sample_count == 3 and not result.stale


def test_summary_marks_old_imported_stream_stale():
    result, = summarize_sensor_samples([sample("rpm", 800, 100), sample("rpm", 900, 101)],
                                       now=107, stale_after=5)
    assert result.current == 900 and result.rate_hz == 1
    assert result.age_seconds == 6 and result.stale


def test_summary_ignores_invalid_quality_and_non_finite_values():
    samples = [sample("load", 25, 1, mono=1), sample("load", 99, 2, mono=2, quality="invalid"),
               sample("load", float("nan"), 3, mono=3), sample("load", float("inf"), 4, mono=4)]
    result, = summarize_sensor_samples(samples, now=2)
    assert result.sample_count == 1 and result.current == 25
    assert result.minimum == result.maximum == result.average == 25
    assert result.rate_hz is None


def test_summary_separates_sensors_and_sorts_by_name():
    samples = [SensorSample(1, "z", "Zulu", 1, "V", "ecu", monotonic_timestamp=1),
               SensorSample(1, "a", "Alpha", 2, "rpm", "ecu", monotonic_timestamp=1)]
    assert [x.sensor_id for x in summarize_sensor_samples(samples, now=1)] == ["a", "z"]


def test_summary_uses_wall_clock_for_mixed_clock_domains():
    samples = [sample("rpm", 800, 100, mono=1), sample("rpm", 900, 101)]
    result, = summarize_sensor_samples(samples, now=107)
    assert result.current == 900 and result.age_seconds == 6 and result.stale


def test_summary_rejects_negative_stale_threshold():
    import pytest
    with pytest.raises(ValueError, match="stale_after"):
        summarize_sensor_samples([], stale_after=-1)
