import csv
from dataclasses import dataclass, field
from pathlib import Path

from .models import CanFrame


@dataclass
class CaptureSession:
    frames: list[CanFrame] = field(default_factory=list)

    def add(self, frame: CanFrame):
        self.frames.append(frame)

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
