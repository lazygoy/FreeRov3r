"""Deterministic, clearly synthetic LR4-style sensor data for offline UI testing."""

import math

from .models import SensorSample


def generate_lr4_demo_samples(duration_seconds=120, sample_rate_hz=2,
                              start_timestamp=1_700_000_000.0,
                              start_monotonic=10_000.0):
    """Return illustrative engine traces; values are not OEM specifications."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive.")
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")

    count = max(2, int(duration_seconds * sample_rate_hz) + 1)
    samples = []
    signals = (
        ("demo.engine.rpm", "Engine speed", "rpm"),
        ("demo.coolant.temp", "Coolant temperature", "°C"),
        ("demo.intake.temp", "Intake air temperature", "°C"),
        ("demo.maf", "Mass air flow", "g/s"),
        ("demo.throttle", "Throttle position", "%"),
        ("demo.stft.b1", "Short-term fuel trim bank 1", "%"),
        ("demo.stft.b2", "Short-term fuel trim bank 2", "%"),
        ("demo.ignition", "Ignition timing", "°"),
    )
    for index in range(count):
        elapsed = index / sample_rate_hz
        phase = elapsed / max(duration_seconds, 1)
        warmup = min(1.0, elapsed / min(75.0, duration_seconds))
        # A repeatable idle-to-light-rev demonstration, not a calibration model.
        rev_event = max(0.0, math.sin((elapsed - 24.0) * math.pi / 15.0))
        rpm = 760 + 35 * math.sin(elapsed * 0.7) + 1850 * rev_event ** 5
        throttle = 4.5 + 19 * rev_event ** 5 + 0.5 * math.sin(elapsed * 0.4)
        coolant = 22 + 68 * (1 - math.exp(-4.0 * warmup))
        intake = 24 + 2.5 * math.sin(elapsed * 0.035) + 0.015 * elapsed
        maf = 3.0 + rpm / 1000 * 1.7 + throttle * 0.16
        trim1 = 1.8 * math.sin(elapsed * 0.8) + 0.7 * math.sin(elapsed * 0.17)
        trim2 = 2.1 * math.sin(elapsed * 0.76 + 0.35) - 0.5 * math.sin(elapsed * 0.13)
        ignition = 12 + 2.8 * math.sin(elapsed * 0.31) + rev_event * 5
        values = (rpm, coolant, intake, maf, throttle, trim1, trim2, ignition)
        for (sensor_id, name, unit), value in zip(signals, values):
            samples.append(SensorSample(
                timestamp=start_timestamp + elapsed,
                sensor_id=sensor_id,
                name=name,
                value=float(value),
                unit=unit,
                source="simulated",
                quality="valid",
                metadata={"vin": "DEMO-LR4-NOT-A-REAL-VIN", "demo": True,
                          "warning": "Synthetic illustration, not vehicle measurements"},
                monotonic_timestamp=start_monotonic + elapsed,
            ))
    return samples
