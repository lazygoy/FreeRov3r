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


    def export_vehicle_backup(self, vin, destination):
        """Create a portable ZIP backup of one VIN's history and local artifacts."""
        import zipfile

        if not vin or vin == "UNASSIGNED":
            raise ValueError("Select a specific vehicle VIN before creating a backup.")

        safe_vin = "".join(ch for ch in str(vin) if ch.isalnum() or ch in "-_")
        if not safe_vin:
            raise ValueError("VIN contains no usable filename characters.")

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        events = self.for_vin(vin)
        manifest = {
            "schema_version": 1,
            "vin": vin,
            "event_count": len(events),
            "contents": [
                "history.json",
                "captures/ (when capture archives exist)",
                "simulated_modules.json (when present)",
            ],
            "note": "Simulator module data is synthetic and is not a physical ECU report.",
        }

        vehicle_root = self.path.parent / "vehicles" / safe_vin
        captures_root = vehicle_root / "captures"
        simulator_state = vehicle_root / "simulated_modules.json"

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            bundle.writestr("history.json", json.dumps(events, indent=2, ensure_ascii=False))
            if captures_root.exists():
                for capture in sorted(captures_root.glob("*.json")):
                    if capture.is_file():
                        bundle.write(capture, f"captures/{capture.name}")
            if simulator_state.is_file():
                bundle.write(simulator_state, "simulated_modules.json")
        return destination
