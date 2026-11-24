"""Read-only loading, validation and comparison of archived CAN captures."""
from collections import Counter, defaultdict
import json
from pathlib import Path


def _safe_vin(vin):
    return "".join(ch for ch in str(vin or "") if ch.isalnum() or ch in "-_")


def list_capture_archives(history_path, vin):
    """Return archived capture paths for one VIN, newest first."""
    safe_vin = _safe_vin(vin)
    if not safe_vin or vin == "UNASSIGNED":
        return []
    folder = Path(history_path).parent / "vehicles" / safe_vin / "captures"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("capture_*.json"), reverse=True)


def load_capture(path):
    """Load a capture and validate frame fields before exposing them to replay."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Capture archive must contain a JSON object.")
    raw_frames = data.get("frames")
    if not isinstance(raw_frames, list):
        raise ValueError("Capture archive has no valid frames list.")

    frames = []
    for index, item in enumerate(raw_frames):
        if not isinstance(item, dict):
            raise ValueError(f"Frame {index + 1} is not an object.")
        try:
            arbitration_id = int(item["arbitration_id"])
            timestamp = float(item.get("timestamp", 0.0) or 0.0)
            payload = bytes.fromhex(str(item.get("data", "")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Frame {index + 1} contains invalid CAN data: {exc}") from exc
        extended = bool(item.get("extended", False))
        if arbitration_id < 0 or arbitration_id > 0x1FFFFFFF:
            raise ValueError(f"Frame {index + 1} has an invalid arbitration ID.")
        if not extended and arbitration_id > 0x7FF:
            raise ValueError(f"Frame {index + 1} uses an extended ID but is marked standard.")
        if len(payload) > 64:
            raise ValueError(f"Frame {index + 1} exceeds the 64-byte CAN FD payload limit.")
        if timestamp < 0:
            raise ValueError(f"Frame {index + 1} has a negative timestamp.")
        frames.append({
            "timestamp": timestamp,
            "arbitration_id": arbitration_id,
            "extended": extended,
            "data": payload.hex(),
            "channel": item.get("channel"),
        })

    samples = data.get("sensor_samples", [])
    if not isinstance(samples, list):
        samples = []
    return {
        "path": str(path),
        "interface": data.get("interface", "unknown"),
        "started_at": data.get("started_at"),
        "duration_seconds": float(data.get("duration_seconds", 0.0) or 0.0),
        "frames": frames,
        "sensor_samples": [sample for sample in samples if isinstance(sample, dict)],
    }


def _sensor_stats(samples):
    grouped = defaultdict(list)
    for sample in samples:
        sensor_id = sample.get("sensor_id")
        unit = sample.get("unit", "")
        value = sample.get("value")
        if not sensor_id:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        grouped[(str(sensor_id), str(unit))].append(numeric)
    result = {}
    for (sensor_id, unit), values in grouped.items():
        result[(sensor_id, unit)] = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "first": values[0],
            "last": values[-1],
        }
    return result


def compare_captures(left, right):
    """Compare two loaded captures without assuming synchronized clocks."""
    left_frames, right_frames = left["frames"], right["frames"]
    left_ids = Counter((f["arbitration_id"], f["extended"]) for f in left_frames)
    right_ids = Counter((f["arbitration_id"], f["extended"]) for f in right_frames)
    identifiers = sorted(set(left_ids) | set(right_ids))
    frame_ids = [
        {
            "arbitration_id": arbitration_id,
            "extended": extended,
            "left_count": left_ids[(arbitration_id, extended)],
            "right_count": right_ids[(arbitration_id, extended)],
            "delta": right_ids[(arbitration_id, extended)] - left_ids[(arbitration_id, extended)],
        }
        for arbitration_id, extended in identifiers
    ]

    left_payloads = Counter(
        (f["arbitration_id"], f["extended"], f["data"].upper()) for f in left_frames
    )
    right_payloads = Counter(
        (f["arbitration_id"], f["extended"], f["data"].upper()) for f in right_frames
    )
    payload_keys = sorted(set(left_payloads) | set(right_payloads))
    payloads = [
        {
            "arbitration_id": arbitration_id,
            "extended": extended,
            "data": payload,
            "left_count": left_payloads[(arbitration_id, extended, payload)],
            "right_count": right_payloads[(arbitration_id, extended, payload)],
            "delta": (
                right_payloads[(arbitration_id, extended, payload)]
                - left_payloads[(arbitration_id, extended, payload)]
            ),
        }
        for arbitration_id, extended, payload in payload_keys
    ]

    left_sensors = _sensor_stats(left["sensor_samples"])
    right_sensors = _sensor_stats(right["sensor_samples"])
    sensor_keys = sorted(set(left_sensors) | set(right_sensors))
    sensors = []
    for sensor_id, unit in sensor_keys:
        a, b = left_sensors.get((sensor_id, unit)), right_sensors.get((sensor_id, unit))
        sensors.append({
            "sensor_id": sensor_id, "unit": unit,
            "left": a, "right": b,
            "mean_delta": (b["mean"] - a["mean"]) if a and b else None,
        })

    return {
        "left_frames": len(left_frames),
        "right_frames": len(right_frames),
        "left_duration": left.get("duration_seconds", 0.0),
        "right_duration": right.get("duration_seconds", 0.0),
        "frame_ids": frame_ids,
        "payloads": payloads,
        "sensors": sensors,
    }
