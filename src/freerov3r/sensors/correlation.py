"""Time-aligned sensor comparison and capture-session annotations.

Analysis is read-only: source SensorSample objects are never modified.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from time import monotonic, time


@dataclass(frozen=True)
class CorrelationResult:
    sensor_a: str
    sensor_b: str
    coefficient: float | None
    sample_count: int
    start_time: float | None
    end_time: float | None
    clock: str
    max_gap_seconds: float


@dataclass(frozen=True)
class EventMarker:
    timestamp: float
    label: str
    note: str = ""
    monotonic_timestamp: float | None = None
    created_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("event marker must be an object")
        timestamp = float(value["timestamp"])
        if not isfinite(timestamp):
            raise ValueError("event timestamp must be finite")
        label = str(value.get("label", "")).strip()
        if not label:
            raise ValueError("event label cannot be empty")
        mono = value.get("monotonic_timestamp")
        mono = None if mono is None else float(mono)
        if mono is not None and not isfinite(mono):
            raise ValueError("monotonic timestamp must be finite")
        return cls(timestamp, label[:120], str(value.get("note", ""))[:2000],
                   mono, str(value.get("created_at", "")))


def _clean_series(samples, sensor_id, clock):
    points = []
    for sample in samples or ():
        if getattr(sample, "sensor_id", None) != sensor_id:
            continue
        if getattr(sample, "quality", "valid") != "valid":
            continue
        try:
            stamp = float(getattr(sample, clock))
            value = float(sample.value)
        except (TypeError, ValueError, AttributeError):
            continue
        if isfinite(stamp) and isfinite(value):
            points.append((stamp, value))
    points.sort(key=lambda point: point[0])
    # Collapse duplicate timestamps deterministically, keeping the last sample.
    unique = {}
    for stamp, value in points:
        unique[stamp] = value
    return sorted(unique.items())


def _interpolate(points, stamp, max_gap):
    if not points or stamp < points[0][0] or stamp > points[-1][0]:
        return None
    low, high = 0, len(points) - 1
    while low <= high:
        middle = (low + high) // 2
        current = points[middle][0]
        if current == stamp:
            return points[middle][1]
        if current < stamp:
            low = middle + 1
        else:
            high = middle - 1
    left, right = points[high], points[low]
    gap = right[0] - left[0]
    if gap <= 0 or gap > max_gap:
        return None
    ratio = (stamp - left[0]) / gap
    return left[1] + ratio * (right[1] - left[1])


def correlate_sensor_series(samples, sensor_a, sensor_b, max_gap_seconds=1.0,
                            min_samples=3):
    """Pearson correlation on overlapping timestamps, without extrapolation.

    Samples use a shared monotonic clock only when every sample has one;
    otherwise both series use wall-clock timestamps. Values in series B are
    linearly interpolated at A's timestamps only across bounded gaps.
    """
    if not isfinite(float(max_gap_seconds)) or max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be positive and finite")
    if int(min_samples) < 2:
        raise ValueError("min_samples must be at least 2")
    relevant = [s for s in (samples or ())
                if getattr(s, "sensor_id", None) in {sensor_a, sensor_b}]
    use_monotonic = bool(relevant) and all(
        getattr(s, "monotonic_timestamp", None) is not None for s in relevant
    )
    clock = "monotonic_timestamp" if use_monotonic else "timestamp"
    a = _clean_series(relevant, sensor_a, clock)
    b = _clean_series(relevant, sensor_b, clock)
    paired = []
    for stamp, value_a in a:
        value_b = _interpolate(b, stamp, float(max_gap_seconds))
        if value_b is not None:
            paired.append((stamp, value_a, value_b))
    coefficient = None
    if len(paired) >= int(min_samples):
        values_a = [p[1] for p in paired]
        values_b = [p[2] for p in paired]
        mean_a = sum(values_a) / len(values_a)
        mean_b = sum(values_b) / len(values_b)
        covariance = sum((x - mean_a) * (y - mean_b)
                         for x, y in zip(values_a, values_b))
        variance_a = sum((x - mean_a) ** 2 for x in values_a)
        variance_b = sum((y - mean_b) ** 2 for y in values_b)
        denominator = sqrt(variance_a * variance_b)
        if denominator > 0:
            coefficient = max(-1.0, min(1.0, covariance / denominator))
    return CorrelationResult(
        str(sensor_a), str(sensor_b), coefficient, len(paired),
        paired[0][0] if paired else None,
        paired[-1][0] if paired else None, clock, float(max_gap_seconds),
    )


def make_event_marker(samples, label, note=""):
    """Create a marker at the latest valid capture timestamp."""
    label = str(label).strip()
    if not label:
        raise ValueError("event label cannot be empty")
    timed = []
    for sample in samples or ():
        try:
            stamp = float(sample.timestamp)
            mono = getattr(sample, "monotonic_timestamp", None)
            mono = None if mono is None else float(mono)
        except (TypeError, ValueError, AttributeError):
            continue
        if isfinite(stamp) and (mono is None or isfinite(mono)):
            timed.append((stamp, mono))
    if not timed:
        raise ValueError("there are no timestamped samples in this capture")
    stamp, mono = max(timed, key=lambda item: item[0])
    return EventMarker(stamp, label[:120], str(note)[:2000], mono,
                       datetime.now(timezone.utc).isoformat())


def normalize_event_markers(values):
    """Validate and chronologically sort serialized session markers."""
    markers = []
    for value in values or ():
        try:
            markers.append(EventMarker.from_dict(value))
        except (TypeError, ValueError, KeyError):
            continue
    return [marker.to_dict() for marker in sorted(markers, key=lambda item: item.timestamp)]
