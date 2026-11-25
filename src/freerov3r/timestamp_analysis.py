"""Per-channel ESP32 device/host timestamp quality analysis.

Device clocks are independent per receiver. This compares each channel's clock
progression with the shared host monotonic timeline; it does not claim clock
synchronization or absolute one-way transport latency.
"""
from __future__ import annotations

import math
from collections import defaultdict


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _linear_fit(points):
    """Return host_seconds ~= intercept + slope * device_seconds."""
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    # A very short device-clock baseline makes drift dominated by timestamp
    # resolution and host scheduling noise. Keep raw statistics, but omit fit.
    if max(xs) - min(xs) < 0.001:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance
    intercept = mean_y - slope * mean_x
    residuals_ms = [abs((y - (intercept + slope * x)) * 1000.0) for x, y in points]
    drift_ppm = (slope - 1.0) * 1_000_000.0
    if abs(drift_ppm) < 1e-6:
        drift_ppm = 0.0
    return {
        "slope": slope,
        "intercept": intercept,
        "drift_ppm": drift_ppm,
        "residual_p95_ms": _percentile(residuals_ms, 0.95),
        "residual_max_ms": max(residuals_ms),
    }


def analyze_channel_timestamps(records, *, suspicious_gap_seconds=1.0):
    """Summarize timestamp coverage, monotonicity, gaps, drift and jitter by channel.

    Input records use host monotonic seconds in timestamp and may include
    device_timestamp_us from an ESP32 receiver. Missing optional timestamps
    never invalidate the associated CAN frame.
    """
    if (
        isinstance(suspicious_gap_seconds, bool)
        or not isinstance(suspicious_gap_seconds, (int, float))
        or not math.isfinite(suspicious_gap_seconds)
        or suspicious_gap_seconds <= 0
    ):
        raise ValueError("Suspicious gap threshold must be a finite positive number")

    grouped = defaultdict(list)
    total = 0
    missing_channel = 0
    for record in records or []:
        if not isinstance(record, dict):
            continue
        total += 1
        channel = record.get("channel")
        if channel is None or str(channel).strip() == "":
            channel = "unspecified"
            missing_channel += 1
        grouped[str(channel)].append(record)

    channels = []
    for channel, channel_records in sorted(grouped.items()):
        points = []
        invalid_host = 0
        missing_device = 0
        invalid_device = 0
        non_monotonic = 0
        duplicate_device_time = 0
        non_monotonic_host = 0
        duplicate_host_time = 0
        device_gaps = 0
        host_gaps = 0
        device_deltas = []
        host_deltas = []
        previous = None

        for record in channel_records:
            try:
                raw_host = record.get("timestamp")
                if isinstance(raw_host, bool):
                    raise ValueError
                host_time = float(raw_host)
                if not math.isfinite(host_time):
                    raise ValueError
            except (TypeError, ValueError):
                invalid_host += 1
                continue

            raw_device = record.get("device_timestamp_us")
            if raw_device is None:
                missing_device += 1
                continue
            try:
                if isinstance(raw_device, bool):
                    raise ValueError
                device_time = int(raw_device)
                if isinstance(raw_device, float) and (
                    not math.isfinite(raw_device) or raw_device != device_time
                ):
                    raise ValueError
                if device_time < 0:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                invalid_device += 1
                continue

            device_seconds = device_time / 1_000_000.0
            points.append((device_seconds, host_time))
            if previous is not None:
                device_delta = device_seconds - previous[0]
                host_delta = host_time - previous[1]
                if device_delta < 0:
                    non_monotonic += 1
                elif device_delta == 0:
                    duplicate_device_time += 1
                else:
                    device_deltas.append(device_delta)
                    if device_delta >= suspicious_gap_seconds:
                        device_gaps += 1
                if host_delta < 0:
                    non_monotonic_host += 1
                elif host_delta == 0:
                    duplicate_host_time += 1
                else:
                    host_deltas.append(host_delta)
                    if host_delta >= suspicious_gap_seconds:
                        host_gaps += 1
            previous = (device_seconds, host_time)

        # A regression or duplicate in either clock makes a linear drift fit
        # misleading. Keep the raw counts, but do not publish a fit.
        fit = (
            None if (
                non_monotonic or duplicate_device_time
                or non_monotonic_host or duplicate_host_time
            ) else _linear_fit(points)
        )
        channels.append({
            "channel": channel,
            "frame_count": len(channel_records),
            "timed_frame_count": len(points),
            "missing_device_timestamp_count": missing_device,
            "invalid_device_timestamp_count": invalid_device,
            "invalid_host_timestamp_count": invalid_host,
            "device_timestamp_coverage": (
                len(points) / len(channel_records) if channel_records else 0.0
            ),
            "non_monotonic_device_steps": non_monotonic,
            "duplicate_device_timestamps": duplicate_device_time,
            "non_monotonic_host_steps": non_monotonic_host,
            "duplicate_host_timestamps": duplicate_host_time,
            "suspicious_device_gaps": device_gaps,
            "suspicious_host_gaps": host_gaps,
            "median_device_interval_ms": (
                _percentile(device_deltas, 0.5) * 1000.0 if device_deltas else None
            ),
            "median_host_interval_ms": (
                _percentile(host_deltas, 0.5) * 1000.0 if host_deltas else None
            ),
            "clock_fit": fit,
            "timing_quality": (
                "check monotonicity/gaps" if (
                    non_monotonic or duplicate_device_time
                    or non_monotonic_host or duplicate_host_time
                    or device_gaps or host_gaps
                )
                else "insufficient data" if fit is None
                else "measured; not synchronized"
            ),
        })

    return {
        "frame_count": total,
        "channel_count": len(channels),
        "frames_without_channel": missing_channel,
        "suspicious_gap_threshold_seconds": float(suspicious_gap_seconds),
        "channels": channels,
        "clock_note": (
            "Host timestamps share the PC monotonic clock. ESP32 device clocks are "
            "independent and unsynchronized. Drift and residual jitter are estimates "
            "over the captured interval, not absolute transport latency."
        ),
    }
