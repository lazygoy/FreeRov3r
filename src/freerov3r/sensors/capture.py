"""Sensor capture session with CSV, JSONL and LLM handoff exports."""
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from .models import SensorSample

@dataclass
class SensorCapture:
    samples: list[SensorSample] = field(default_factory=list)
    vehicle_context: dict = field(default_factory=dict)

    def add(self, sample: SensorSample):
        self.samples.append(sample)

    def export_csv(self, path):
        fields = ["timestamp", "sensor_id", "name", "value", "unit",
                  "source", "ecu", "signal", "quality"]
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for sample in self.samples:
                row = asdict(sample)
                row.pop("metadata", None)
                writer.writerow(row)

    def export_jsonl(self, path):
        with Path(path).open("w", encoding="utf-8") as f:
            for sample in self.samples:
                f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\\n")

    def llm_report(self, include_context=True):
        """Portable, provider-neutral analysis packet. No API calls or secrets."""
        grouped = {}
        for s in self.samples:
            grouped.setdefault((s.sensor_id, s.name, s.unit, s.source), []).append(s)
        lines = [
            "# FreeRov3r sensor capture analysis",
            "",
            "Analyze the supplied measurements. Separate observed facts from hypotheses.",
            "Do not invent manufacturer specifications or normal ranges. State when vehicle-specific",
            "service data is required. Preserve units and timestamps. Flag missing or suspect data.",
            "Do not recommend ECU writes, coding, adaptations, or programming based only on this report.",
            "",
            "## Vehicle / test context",
            json.dumps(self.vehicle_context if include_context else {}, indent=2),
            "",
            "## Captured signals",
        ]
        for (sensor_id, name, unit, source), values in grouped.items():
            nums = [x.value for x in values if x.quality == "valid"]
            lines += ["", f"### {name} ({sensor_id})",
                      f"- Source: {source}; unit: {unit}; samples: {len(values)}"]
            if nums:
                lines += [f"- Min / mean / max: {min(nums):.4g} / {mean(nums):.4g} / {max(nums):.4g} {unit}",
                          f"- First / last: {values[0].timestamp:.3f} / {values[-1].timestamp:.3f}"]
            lines.append("- Data (timestamp,value,quality):")
            lines.extend([f"  - {x.timestamp:.3f},{x.value:.6g},{x.quality}" for x in values])
        lines += ["", "## Requested analysis", 
                  "1. Identify trends, outliers, dropouts, and relationships between signals.",
                  "2. Distinguish confirmed observations from possible causes.",
                  "3. List additional measurements or tests that would discriminate between causes.",
                  "4. Cite the exact samples supporting each conclusion."]
        return "\\n".join(lines)

    def export_llm_report(self, path, include_context=True):
        Path(path).write_text(self.llm_report(include_context), encoding="utf-8")
