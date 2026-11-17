"""Typed sensor samples. Values always retain source and unit metadata."""
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class SensorSample:
    timestamp: float
    sensor_id: str
    name: str
    value: float
    unit: str
    source: str  # ecu, external, calculated, simulated
    ecu: str | None = None
    signal: str | None = None
    quality: str = "valid"
    metadata: dict | None = None

    @classmethod
    def create(cls, sensor_id: str, name: str, value: float, unit: str,
               source: str, **kwargs):
        return cls(datetime.now(timezone.utc).timestamp(), sensor_id, name,
                   float(value), unit, source, **kwargs)
