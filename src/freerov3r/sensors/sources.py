"""Sensor source contracts; ECU decoders and external DAQ drivers plug in here."""
from abc import ABC, abstractmethod
from collections.abc import Iterator
from .models import SensorSample

class SensorSource(ABC):
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def read(self, timeout: float = 0.2) -> SensorSample | None: ...

class SensorRegistry:
    def __init__(self):
        self._sources: dict[str, SensorSource] = {}
    def register(self, source_id: str, source: SensorSource):
        if source_id in self._sources:
            raise ValueError(f"Sensor source already registered: {source_id}")
        self._sources[source_id] = source
    def get(self, source_id: str) -> SensorSource:
        return self._sources[source_id]
    def ids(self):
        return tuple(self._sources)
