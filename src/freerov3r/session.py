import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import CanFrame, DiagnosticEvent


@dataclass
class CaptureSession:
    frames: list[CanFrame] = field(default_factory=list)
    diagnostic_events: list[DiagnosticEvent] = field(default_factory=list)

    def add(self, frame: CanFrame):
        self.frames.append(frame)

    def add_diagnostic_event(self, event: DiagnosticEvent):
        """Store protocol events separately from raw CAN frames."""
        if not isinstance(event, DiagnosticEvent):
            raise TypeError("event must be a DiagnosticEvent")
        self.diagnostic_events.append(event)

    def export_diagnostic_jsonl(self, path, events=None):
        """Export protocol events as JSONL without flattening them into CAN rows."""
        selected = self.diagnostic_events if events is None else events
        with Path(path).open("w", encoding="utf-8") as stream:
            for event in selected:
                stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\\n")

    def export_csv(self, path):
        fields = [
            "timestamp", "timestamp_clock_domain", "timestamp_source",
            "source_timestamp", "source_timestamp_clock_domain",
            "device_timestamp_us", "device_timestamp_clock_domain",
            "channel", "id", "extended", "dlc", "data",
        ]
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for frame in self.frames:
                writer.writerow({
                    "timestamp": frame.timestamp if frame.timestamp is not None else "",
                    "timestamp_clock_domain": frame.timestamp_clock_domain,
                    "timestamp_source": frame.timestamp_source,
                    "source_timestamp": (
                        frame.source_timestamp if frame.source_timestamp is not None else ""
                    ),
                    "source_timestamp_clock_domain": frame.source_timestamp_clock_domain or "",
                    "device_timestamp_us": (
                        frame.device_timestamp_us if frame.device_timestamp_us is not None else ""
                    ),
                    "device_timestamp_clock_domain": frame.device_timestamp_clock_domain or "",
                    "channel": frame.channel or "",
                    "id": f"{frame.arbitration_id:X}",
                    "extended": int(frame.is_extended_id),
                    "dlc": len(frame.data),
                    "data": frame.data.hex(" ").upper(),
                })

    def export_candump(self, path):
        with Path(path).open("w", encoding="utf-8") as f:
            for frame in self.frames:
                ident = (
                    f"{frame.arbitration_id:08X}"
                    if frame.is_extended_id else f"{frame.arbitration_id:03X}"
                )
                f.write(
                    f"({frame.timestamp or 0:.6f}) "
                    f"{frame.channel or 'can0'} {ident}#{frame.data.hex().upper()}\n"
                )
