"""Local, VIN-keyed diagnostic event history. No network access."""
import json
from datetime import datetime, timezone
from pathlib import Path


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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder = self.path.parent / "vehicles" / safe_key / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / f"capture_{stamp}.json"
        archive.write_text(json.dumps(capture, indent=2, ensure_ascii=False), encoding="utf-8")
        return archive

    def for_vin(self, vin):
        return [event for event in self.events if event.get("vin") == (vin or "UNASSIGNED")]

    def vehicles(self):
        return sorted({event.get("vin", "UNASSIGNED") for event in self.events})
