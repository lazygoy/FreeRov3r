"""Practical statistics for captured sensor streams."""
from dataclasses import dataclass
from math import isfinite
from statistics import fmean
from time import monotonic, time


@dataclass(frozen=True)
class SensorSummary:
    sensor_id: str
    name: str
    unit: str
    current: float
    minimum: float
    average: float
    maximum: float
    rate_hz: float | None
    age_seconds: float
    sample_count: int
    stale: bool


def summarize_sensor_samples(samples, now=None, stale_after=5.0):
    """Summarize valid samples per sensor using one consistent clock domain."""
    if stale_after < 0:
        raise ValueError("stale_after must be non-negative")
    grouped = {}
    for sample in samples or ():
        try:
            value = float(sample.value)
            sensor_id = sample.sensor_id
        except (TypeError, ValueError, AttributeError):
            continue
        if not isfinite(value) or getattr(sample, "quality", "valid") != "valid":
            continue
        grouped.setdefault(sensor_id, []).append((sample, value))
    summaries = []
    for sensor_id, entries in grouped.items():
        use_monotonic = all(getattr(sample, "monotonic_timestamp", None) is not None for sample, _ in entries)
        clock_name = "monotonic_timestamp" if use_monotonic else "timestamp"
        timed = []
        for sample, value in entries:
            try:
                stamp = float(getattr(sample, clock_name))
            except (TypeError, ValueError, AttributeError):
                continue
            if isfinite(stamp):
                timed.append((stamp, sample, value))
        if not timed:
            continue
        timed.sort(key=lambda item: item[0])
        stamps = [item[0] for item in timed]
        values = [item[2] for item in timed]
        current_stamp, latest_sample, current_value = timed[-1]
        clock_now = now
        if clock_now is None:
            clock_now = monotonic() if use_monotonic else time()
        age = max(0.0, float(clock_now) - current_stamp)
        span = stamps[-1] - stamps[0]
        rate = (len(timed) - 1) / span if len(timed) > 1 and span > 0 else None
        summaries.append(SensorSummary(
            sensor_id=str(sensor_id),
            name=str(getattr(latest_sample, "name", sensor_id)),
            unit=str(getattr(latest_sample, "unit", "")),
            current=current_value, minimum=min(values), average=fmean(values),
            maximum=max(values), rate_hz=rate, age_seconds=age,
            sample_count=len(timed), stale=age > stale_after,
        ))
    return sorted(summaries, key=lambda item: (item.name.casefold(), item.sensor_id))
