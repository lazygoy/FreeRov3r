import json

import pytest

from freerov3r.sensors.capture import SensorCapture
from freerov3r.sensors.correlation import (
    EventMarker,
    correlate_sensor_series,
    make_event_marker,
    normalize_event_markers,
)
from freerov3r.sensors.models import SensorSample


def sample(sensor_id, stamp, value, *, mono=None, quality="valid"):
    return SensorSample(
        timestamp=float(stamp), sensor_id=sensor_id, name=sensor_id,
        value=float(value), unit="u", source="test", quality=quality,
        monotonic_timestamp=mono,
    )


def test_correlation_aligns_different_sample_rates():
    samples = [
        sample("a", 100, 0, mono=10),
        sample("a", 101, 1, mono=11),
        sample("a", 102, 2, mono=12),
        sample("b", 100, 0, mono=10),
        sample("b", 102, 2, mono=12),
    ]
    result = correlate_sensor_series(samples, "a", "b", max_gap_seconds=2)
    assert result.clock == "monotonic_timestamp"
    assert result.sample_count == 3
    assert result.coefficient == pytest.approx(1.0)


def test_correlation_uses_wall_clock_if_any_sample_lacks_monotonic_time():
    samples = [
        sample("a", 100, 1, mono=10),
        sample("a", 101, 2, mono=11),
        sample("a", 102, 3, mono=12),
        sample("b", 100, 2),
        sample("b", 101, 4),
        sample("b", 102, 6),
    ]
    result = correlate_sensor_series(samples, "a", "b")
    assert result.clock == "timestamp"
    assert result.sample_count == 3
    assert result.coefficient == pytest.approx(1.0)


def test_correlation_does_not_extrapolate_or_cross_large_gaps():
    samples = [
        sample("a", 0, 1, mono=0),
        sample("a", 1, 2, mono=1),
        sample("a", 2, 3, mono=2),
        sample("b", 0, 4, mono=0),
        sample("b", 2, 8, mono=2),
    ]
    result = correlate_sensor_series(samples, "a", "b", max_gap_seconds=1)
    assert result.sample_count == 2
    assert result.coefficient is None


def test_invalid_quality_samples_are_ignored():
    samples = [
        sample("a", 0, 1, mono=0),
        sample("a", 1, 2, mono=1),
        sample("a", 2, 3, mono=2, quality="invalid"),
        sample("b", 0, 2, mono=0),
        sample("b", 1, 4, mono=1),
        sample("b", 2, 6, mono=2),
    ]
    result = correlate_sensor_series(samples, "a", "b")
    assert result.sample_count == 2
    assert result.coefficient is None


def test_constant_signal_has_no_pearson_coefficient():
    samples = [
        sample("a", i, 4, mono=i) for i in range(3)
    ] + [
        sample("b", i, i, mono=i) for i in range(3)
    ]
    result = correlate_sensor_series(samples, "a", "b")
    assert result.sample_count == 3
    assert result.coefficient is None


def test_invalid_gap_is_rejected():
    with pytest.raises(ValueError):
        correlate_sensor_series([], "a", "b", max_gap_seconds=0)


def test_event_marker_normalization_and_capture_export(tmp_path):
    capture = SensorCapture(samples=[
        sample("rpm", 100, 800, mono=10),
        sample("rpm", 101, 900, mono=11),
    ])
    marker = make_event_marker(capture.samples, "Throttle blip", "pedal pressed")
    capture.add_event(marker)
    capture.add_event(EventMarker(99, "Earlier event"))
    assert [event["label"] for event in capture.events] == [
        "Earlier event", "Throttle blip"
    ]
    original_samples = list(capture.samples)
    output = tmp_path / "session.json"
    capture.export_session_json(output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["events"][1]["label"] == "Throttle blip"
    assert payload["sample_count_retained"] == 2
    assert capture.samples == original_samples


def test_marker_normalization_discards_malformed_entries():
    values = normalize_event_markers([
        {"timestamp": 3, "label": "later"},
        {"timestamp": 1, "label": "earlier"},
        {"timestamp": float("nan"), "label": "bad"},
        {"timestamp": 2, "label": ""},
    ])
    assert [item["label"] for item in values] == ["earlier", "later"]
