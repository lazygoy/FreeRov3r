"""NTP-style clock calibration for independent FreeRov3r ESP32 receivers.

The estimate assumes approximately symmetric request/response transport delay.
The reported half-RTT is a precision indicator under that assumption, not a
hard bound: unknown path asymmetry and host scheduling can create additional
error. The algorithm never claims hardware clocks are physically synchronized.
"""
from __future__ import annotations

import math


def calculate_clock_sync_sample(
    *,
    host_send_time_ns: int,
    device_receive_time_us: int,
    device_send_time_us: int,
    host_receive_time_ns: int,
) -> dict:
    """Calculate one four-timestamp exchange using NTP offset/delay equations."""
    values = (
        host_send_time_ns,
        device_receive_time_us,
        device_send_time_us,
        host_receive_time_ns,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("Clock synchronization timestamps must be non-negative integers")
    if host_receive_time_ns < host_send_time_ns:
        raise ValueError("Host receive timestamp precedes host send timestamp")
    if device_send_time_us < device_receive_time_us:
        raise ValueError("Device send timestamp precedes device receive timestamp")

    t1 = host_send_time_ns
    t2 = device_receive_time_us * 1000
    t3 = device_send_time_us * 1000
    t4 = host_receive_time_ns
    round_trip_ns = (t4 - t1) - (t3 - t2)
    if round_trip_ns < 0:
        raise ValueError("Calculated network round-trip delay is negative")

    device_minus_host_offset_ns = ((t2 - t1) + (t3 - t4)) / 2.0
    return {
        "host_send_time_ns": t1,
        "device_receive_time_us": device_receive_time_us,
        "device_send_time_us": device_send_time_us,
        "host_receive_time_ns": t4,
        "host_midpoint_time_ns": (t1 + t4) / 2.0,
        "device_midpoint_time_ns": (t2 + t3) / 2.0,
        "device_minus_host_offset_ns": device_minus_host_offset_ns,
        "round_trip_delay_ns": round_trip_ns,
        "symmetric_path_uncertainty_floor_ns": round_trip_ns / 2.0,
    }


def estimate_clock_mapping(samples, *, best_sample_count=8) -> dict:
    """Fit host monotonic time against device time using the lowest-RTT samples."""
    usable = [
        sample for sample in (samples or [])
        if isinstance(sample, dict)
        and all(
            isinstance(sample.get(key), (int, float))
            and math.isfinite(sample[key])
            for key in (
                "host_midpoint_time_ns",
                "device_midpoint_time_ns",
                "round_trip_delay_ns",
                "device_minus_host_offset_ns",
            )
        )
        and sample["round_trip_delay_ns"] >= 0
    ]
    if isinstance(best_sample_count, bool) or not isinstance(best_sample_count, int) or best_sample_count < 1:
        raise ValueError("best_sample_count must be a positive integer")
    if len(usable) < 2:
        return {
            "status": "insufficient samples",
            "sample_count": len(usable),
            "mapping": None,
        }

    selected = sorted(usable, key=lambda item: item["round_trip_delay_ns"])[:best_sample_count]
    xs = [float(item["device_midpoint_time_ns"]) for item in selected]
    ys = [float(item["host_midpoint_time_ns"]) for item in selected]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance <= 0:
        return {
            "status": "insufficient device clock span",
            "sample_count": len(selected),
            "mapping": None,
        }

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
    intercept = mean_y - slope * mean_x
    residuals = sorted(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys))
    p95_index = min(len(residuals) - 1, math.ceil(0.95 * len(residuals)) - 1)
    min_rtt = min(item["round_trip_delay_ns"] for item in selected)
    return {
        "status": "estimated; transport asymmetry unbounded",
        "sample_count": len(selected),
        "available_sample_count": len(usable),
        "minimum_round_trip_delay_ns": min_rtt,
        "symmetric_path_uncertainty_floor_ns": min_rtt / 2.0,
        "fit_residual_p95_ns": residuals[p95_index],
        "drift_ppm": (slope - 1.0) * 1_000_000.0,
        "host_coverage_start_ns": min(ys),
        "host_coverage_end_ns": max(ys),
        "mapping": {
            "host_monotonic_ns": "intercept + slope * device_time_ns",
            "intercept_ns": intercept,
            "slope": slope,
        },
        "uncertainty_note": (
            "Half the minimum round-trip delay is a precision floor only under "
            "a symmetric-path assumption. Unknown transport asymmetry and host "
            "scheduling latency are not bounded by this estimate."
        ),
    }



def compare_clock_mappings(mapping_a: dict, mapping_b: dict) -> dict:
    """Compare two independently calibrated device clocks on common host time."""
    if not isinstance(mapping_a, dict) or not isinstance(mapping_b, dict):
        raise ValueError("Two valid clock mapping results are required")
    fit_a = mapping_a.get("mapping")
    fit_b = mapping_b.get("mapping")
    if not fit_a or not fit_b:
        return {"status": "insufficient calibration", "comparison": None}

    start = max(
        mapping_a.get("host_coverage_start_ns", 0),
        mapping_b.get("host_coverage_start_ns", 0),
    )
    end = min(
        mapping_a.get("host_coverage_end_ns", 0),
        mapping_b.get("host_coverage_end_ns", 0),
    )
    if end <= start:
        return {
            "status": "no overlapping calibration coverage",
            "comparison": None,
        }

    def device_time(mapping, host_ns):
        return (
            host_ns - mapping["intercept_ns"]
        ) / mapping["slope"]

    offset_start = device_time(fit_b, start) - device_time(fit_a, start)
    offset_end = device_time(fit_b, end) - device_time(fit_a, end)
    duration = end - start
    return {
        "status": "calibrated apparent relationship; asymmetry unbounded",
        "host_overlap_start_ns": start,
        "host_overlap_end_ns": end,
        "apparent_device_offset_start_ns": offset_start,
        "apparent_device_offset_end_ns": offset_end,
        "apparent_relative_drift_ppm": (
            (offset_end - offset_start) / duration
        ) * 1_000_000.0,
        "combined_fit_residual_p95_ns": (
            mapping_a.get("fit_residual_p95_ns", 0.0)
            + mapping_b.get("fit_residual_p95_ns", 0.0)
        ),
        "combined_symmetric_path_uncertainty_floor_ns": (
            mapping_a.get("symmetric_path_uncertainty_floor_ns", 0.0)
            + mapping_b.get("symmetric_path_uncertainty_floor_ns", 0.0)
        ),
        "uncertainty_note": (
            "Fit residual and half-RTT precision indicators assume symmetric "
            "transport. Unknown path asymmetry and host scheduling are not "
            "bounded; this is software clock calibration, not hardware sync."
        ),
    }



def calibrate_two_devices(
    adapter_a,
    adapter_b,
    *,
    sample_count=12,
    timeout=1.0,
    interval_seconds=0.02,
) -> dict:
    """Interleave probes to calibrate two ESP32 clocks over shared host time.

    Both adapters must already be connected and have active background receive
    loops. Probes alternate order to reduce systematic ordering bias.
    """
    if adapter_a is adapter_b:
        raise ValueError("Two distinct ESP32 adapters are required")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 3:
        raise ValueError("Dual-device calibration requires at least three sample pairs")
    if interval_seconds < 0 or not math.isfinite(interval_seconds):
        raise ValueError("Calibration interval must be finite and non-negative")

    samples_a = []
    samples_b = []
    for index in range(sample_count):
        if index % 2 == 0:
            samples_a.append(adapter_a.request_clock_sync(timeout=timeout))
            samples_b.append(adapter_b.request_clock_sync(timeout=timeout))
        else:
            samples_b.append(adapter_b.request_clock_sync(timeout=timeout))
            samples_a.append(adapter_a.request_clock_sync(timeout=timeout))
        if index + 1 < sample_count and interval_seconds:
            import time
            time.sleep(interval_seconds)

    mapping_a = estimate_clock_mapping(samples_a)
    mapping_b = estimate_clock_mapping(samples_b)
    mapping_a["samples"] = samples_a
    mapping_b["samples"] = samples_b
    mapping_a["transport"] = getattr(adapter_a, "transport_label", "adapter A")
    mapping_b["transport"] = getattr(adapter_b, "transport_label", "adapter B")
    adapter_a.clock_calibration = mapping_a
    adapter_b.clock_calibration = mapping_b
    return {
        "device_a": mapping_a,
        "device_b": mapping_b,
        "comparison": compare_clock_mappings(mapping_a, mapping_b),
        "sample_pair_count": sample_count,
        "calibration_method": "interleaved four-timestamp host/device probes",
    }
