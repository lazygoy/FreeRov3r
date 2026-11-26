"""Named, read-only sensor dashboard layouts built from observed signal IDs.

Preset entries are convenience groupings, not claims that a vehicle supports a PID.
Only signals already present in the active capture are selected.
"""

# Each panel is a group of related signals. Standard Mode 01 IDs are generic
# SAE PIDs; demo aliases are clearly synthetic and are never mixed with live data.
PRESET_GROUPS = {
    "Warm-up": (
        ("obd_05", "obd_0F", "demo.coolant.temp", "demo.intake.temp"),
        ("obd_0C", "demo.engine.rpm"),
    ),
    "Idle overview": (
        ("obd_0C", "obd_04", "obd_10", "demo.engine.rpm", "demo.maf"),
        ("obd_05", "obd_0E", "demo.coolant.temp", "demo.ignition"),
    ),
    "Fuel trims": (
        ("obd_06", "obd_07", "demo.stft.b1"),
        ("obd_08", "obd_09", "demo.stft.b2"),
        ("obd_10", "obd_0B", "demo.maf"),
    ),
    "Voltage monitor": (
        ("obd_42",),
        ("obd_0C", "obd_04", "demo.engine.rpm"),
    ),
    "Road test": (
        ("obd_0D", "obd_0C", "demo.engine.rpm"),
        ("obd_11", "obd_04", "demo.throttle"),
        ("obd_42",),
    ),
}


def build_sensor_preset(name, available_sensor_ids):
    """Return a dashboard layout containing only signals in the active capture."""
    if name not in PRESET_GROUPS:
        raise ValueError(f"unknown sensor dashboard preset: {name}")
    available = {str(value) for value in (available_sensor_ids or ())}
    groups = [
        [sensor_id for sensor_id in group if sensor_id in available]
        for group in PRESET_GROUPS[name]
    ]
    groups = [group for group in groups if group]
    if not groups:
        return None
    panels = [
        {"sensor_ids": group, "window_seconds": 60, "auto_scale": True}
        for group in groups
    ]
    while len(panels) < 8:
        panels.append({"sensor_ids": [], "window_seconds": 60, "auto_scale": True})
    count = 1 if len(groups) == 1 else 2 if len(groups) == 2 else 4
    return {"version": 1, "panel_count": count, "panels": panels}
