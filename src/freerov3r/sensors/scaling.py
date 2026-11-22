"""Pure helpers for plotting sensor streams with different physical ranges."""

from math import isfinite


def normalize_values(values):
    """Map one sensor's values to 0..100 while retaining its original range.

    Constant-valued signals are placed at 50% to avoid division by zero.
    Non-finite values are rejected rather than contaminating chart axes.
    """
    cleaned = [float(value) for value in values if isfinite(float(value))]
    if not cleaned:
        return [], 0.0, 0.0
    low, high = min(cleaned), max(cleaned)
    if high == low:
        return [50.0 for _ in cleaned], low, high
    span = high - low
    return [((value - low) / span) * 100.0 for value in cleaned], low, high
