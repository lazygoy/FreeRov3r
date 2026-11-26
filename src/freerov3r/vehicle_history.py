"""Local, VIN-keyed diagnostic event history. No network access."""
import json
from datetime import datetime, timezone
from pathlib import Path


DTC_SCAN_EVENT_TYPES = {"dtc_scan_completed", "dtc_scan_failed"}


def filter_dtc_scan_events(events):
    """Return completed and failed OBD-II DTC scan events, preserving order."""
    return [event for event in events if event.get("type") in DTC_SCAN_EVENT_TYPES]


def format_dtc_scan_event(event):
    """Format a stored DTC scan as readable text without inventing descriptions."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "dtc_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\\n".join(lines)

    services = details.get("services") or []
    lines.extend([
        f"Services: {', '.join(str(service) for service in services) or 'Not recorded'}",
        f"Code records: {details.get('count', len(details.get('dtcs') or []))}",
        "",
        "TROUBLE CODES",
    ])
    codes = details.get("dtcs") or []
    if not codes:
        lines.append("No codes were returned.")
    for code in codes:
        lines.append(
            f"{code.get('code', 'Unknown')} | {code.get('status', 'Unknown')} | "
            f"ECU {int(code.get('arbitration_id', 0)):08X} "
            f"({'29-bit' if code.get('is_extended_id') else '11-bit'}) | "
            f"Channel {code.get('channel', 'Unknown')} | Raw {code.get('raw', '')}"
        )
    lines.extend(["", "OEM-specific descriptions are not inferred by this report."])
    return "\\n".join(lines)


class VehicleHistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.load()

    def load(self):
        if not self.path.exists():
            self.events = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.events = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            self.events = []

    def record(self, vin, event_type, summary, details=None):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "vin": vin or "UNASSIGNED",
            "type": str(event_type),
            "summary": str(summary),
            "details": details or {},
        }
        self.events.append(event)
        self.save()
        return event

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.events, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def archive_capture(self, vin, capture):
        vehicle_key = vin or "UNASSIGNED"
        safe_key = "".join(ch for ch in vehicle_key if ch.isalnum() or ch in "-_")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = self.path.parent / "vehicles" / safe_key / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / f"capture_{stamp}.json"
        archive.write_text(json.dumps(capture, indent=2, ensure_ascii=False), encoding="utf-8")
        return archive

    def for_vin(self, vin):
        return [event for event in self.events if event.get("vin") == (vin or "UNASSIGNED")]

    def vehicles(self):
        return sorted({event.get("vin", "UNASSIGNED") for event in self.events})
