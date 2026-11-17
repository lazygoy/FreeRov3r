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
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "id", "extended", "dlc", "data"])
            for x in self.frames:
                w.writerow([x.timestamp or 0, f"{x.arbitration_id:X}",
                            int(x.is_extended_id), len(x.data), x.data.hex(" ").upper()])

    def export_candump(self, path):
        with Path(path).open("w", encoding="utf-8") as f:
            for x in self.frames:
                ident = f"{x.arbitration_id:08X}" if x.is_extended_id else f"{x.arbitration_id:03X}"
                f.write(f"({x.timestamp or 0:.6f}) {x.channel or 'can0'} {ident}#{x.data.hex().upper()}\n")
