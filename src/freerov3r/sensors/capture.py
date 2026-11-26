"""Sensor capture session with CSV, JSONL and LLM handoff exports."""
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from .models import SensorSample
from .correlation import EventMarker, normalize_event_markers

@dataclass
class SensorCapture:
    samples: list[SensorSample] = field(default_factory=list)
    vehicle_context: dict = field(default_factory=dict)
    max_samples: int = 100000
    total_samples_added: int = 0
    dropped_samples: int = 0
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.max_samples < 1:
            raise ValueError("max_samples must be at least 1.")
        if len(self.samples) > self.max_samples:
            overflow = len(self.samples) - self.max_samples
            del self.samples[:overflow]
            self.dropped_samples += overflow
        self.total_samples_added = max(self.total_samples_added, len(self.samples) + self.dropped_samples)

    def add_event(self, marker):
        """Attach an annotation to the session without changing raw samples."""
        value = marker.to_dict() if isinstance(marker, EventMarker) else marker
        self.events = normalize_event_markers([*self.events, value])

    def export_session_json(self, path):
        """Export session context and annotations separately from raw sample data."""
        payload = {
            "format": "freerov3r-sensor-session",
            "version": 1,
            "vehicle_context": self.vehicle_context,
            "sample_count_retained": len(self.samples),
            "total_samples_added": self.total_samples_added,
            "dropped_samples": self.dropped_samples,
            "events": normalize_event_markers(self.events),
        }
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add(self, sample: SensorSample):
        self.samples.append(sample)
        self.total_samples_added += 1
        overflow = len(self.samples) - self.max_samples
        if overflow > 0:
            # Trim in batches to avoid shifting a large list on every new sample.
            batch = min(
                len(self.samples),
                max(overflow, min(1000, max(1, self.max_samples // 20))),
            )
            del self.samples[:batch]
            self.dropped_samples += batch

    def samples_since(self, sequence_index):
        """Return retained samples added at or after an absolute capture index."""
        start = max(0, int(sequence_index) - self.dropped_samples)
        return self.samples[start:]

    def export_csv(self, path, vin=None, samples=None):
        fields = ["vin", "timestamp", "sensor_id", "name", "value", "unit",
                  "source", "ecu", "signal", "quality", "monotonic_timestamp"]
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for sample in (self.samples if samples is None else samples):
                sample_vin = (sample.metadata or {}).get("vin", "UNASSIGNED")
                if vin and sample_vin != vin:
                    continue
                row = asdict(sample)
                row["vin"] = sample_vin
                row.pop("metadata", None)
                writer.writerow(row)

    def export_jsonl(self, path, samples=None, vin=None):
        with Path(path).open("w", encoding="utf-8") as f:
            for sample in (self.samples if samples is None else samples):
                if vin and (sample.metadata or {}).get("vin", "UNASSIGNED") != vin:
                    continue
                f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")

    def llm_report(self, include_context=True, vin=None):
        """Portable, provider-neutral analysis packet. No API calls or secrets."""
        grouped = {}
        selected_samples = [s for s in self.samples
                            if not vin or (s.metadata or {}).get("vin", "UNASSIGNED") == vin]
        for s in selected_samples:
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
        return "\n".join(lines)

    def export_llm_report(self, path, include_context=True, vin=None):
        Path(path).write_text(self.llm_report(include_context, vin=vin), encoding="utf-8")
