"""Read-only loading, validation and comparison of archived CAN captures."""
from collections import Counter, defaultdict
import json
import math
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
        if not math.isfinite(timestamp) or timestamp < 0:
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
        "vin": path.parent.parent.name if path.parent.name == "captures" else None,
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


def filter_capture_frames(frames, can_id="", frame_format="Any", payload_contains=""):
    """Return (source_index, frame) pairs matching display-only replay filters."""
    query = str(can_id or "").strip()
    wanted_id = None
    if query:
        try:
            wanted_id = int(query, 16 if query.lower().startswith("0x") else 10)
        except ValueError as exc:
            raise ValueError("CAN ID filter must be decimal or 0x-prefixed hexadecimal.") from exc
        if wanted_id < 0 or wanted_id > 0x1FFFFFFF:
            raise ValueError("CAN ID filter is outside the valid CAN identifier range.")

    fmt = str(frame_format or "Any").strip().lower()
    if fmt not in {"any", "standard", "extended", "std", "ext"}:
        raise ValueError("Frame format must be Any, Standard or Extended.")
    payload_query = "".join(str(payload_contains or "").split()).upper().replace("0X", "")
    if any(ch not in "0123456789ABCDEF" for ch in payload_query):
        raise ValueError("Payload filter must contain hexadecimal characters only.")

    matches = []
    for index, frame in enumerate(frames):
        if wanted_id is not None and int(frame["arbitration_id"]) != wanted_id:
            continue
        extended = bool(frame.get("extended", False))
        if fmt in {"standard", "std"} and extended:
            continue
        if fmt in {"extended", "ext"} and not extended:
            continue
        if payload_query and payload_query not in str(frame.get("data", "")).upper():
            continue
        matches.append((index, frame))
    return matches


def build_replay_timeline(capture, can_id="", frame_format="Any", payload_contains=""):
    """Merge filtered CAN frames and archived sensor samples into timestamp order.

    Original frame/sample indices are retained so display filters never mutate archives.
    """
    frames = capture.get("frames", [])
    samples = capture.get("sensor_samples", [])
    timeline = []
    for source_index, frame in filter_capture_frames(
        frames, can_id, frame_format, payload_contains
    ):
        timeline.append({
            "kind": "frame", "timestamp": float(frame.get("timestamp", 0.0)),
            "source_index": source_index, "frame": frame, "vin": capture.get("vin"),
        })
    for source_index, sample in enumerate(samples):
        try:
            timestamp = float(sample.get("timestamp", 0.0) or 0.0)
            value = float(sample["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(timestamp) or not math.isfinite(value) or timestamp < 0 or not sample.get("sensor_id"):
            continue
        normalized = dict(sample)
        normalized["timestamp"] = timestamp
        normalized["value"] = value
        timeline.append({
            "kind": "sensor", "timestamp": timestamp,
            "source_index": source_index, "sample": normalized, "vin": capture.get("vin"),
        })
    # Frames precede sensor samples at identical timestamps; stable source order is kept.
    timeline.sort(key=lambda event: (
        event["timestamp"], 0 if event["kind"] == "frame" else 1,
        event["source_index"],
    ))
    return timeline
