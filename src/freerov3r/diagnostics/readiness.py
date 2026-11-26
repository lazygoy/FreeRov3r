"""Conservative SAE J1979 PID 01 readiness decoding.

The decoder reports only the MIL, DTC count, ignition type, and monitor
availability/completion bits actually present in a valid PID 01 response.
"""
from dataclasses import dataclass


SPARK_IGNITION_MONITORS = (
    "misfire",
    "fuel_system",
    "comprehensive_components",
    "catalyst",
    "heated_catalyst",
    "evaporative_system",
    "secondary_air_system",
    "ac_refrigerant",
)

COMMON_MONITORS = (
    "misfire",
    "fuel_system",
    "comprehensive_components",
)


@dataclass(frozen=True)
class ReadinessMonitor:
    name: str
    supported: bool
    complete: bool | None

    def to_dict(self):
        return {
            "name": self.name,
            "supported": self.supported,
            "complete": self.complete,
        }


def decode_obd_readiness(payload):
    """Decode a complete Mode 01 PID 01 positive response.

    Accepts 41 01 A B C D or the four data bytes A B C D. ISO-TP
    reassembly must happen before calling this function.
    """
    data = bytes(payload or b"")
    if len(data) == 6 and data[:2] == bytes((0x41, 0x01)):
        data = data[2:]
    if len(data) != 4:
        raise ValueError("PID 01 readiness response must contain exactly four data bytes")

    mil_and_count, ignition, available, incomplete = data
    compression_ignition = bool(ignition & 0x08)
    names = COMMON_MONITORS if compression_ignition else SPARK_IGNITION_MONITORS
    monitors = []
    for bit, name in enumerate(names):
        supported = bool(available & (1 << bit))
        monitors.append(ReadinessMonitor(
            name=name,
            supported=supported,
            complete=(not bool(incomplete & (1 << bit))) if supported else None,
        ))

    return {
        "mil_on": bool(mil_and_count & 0x80),
        "dtc_count": mil_and_count & 0x7F,
        "ignition_type": "compression" if compression_ignition else "spark",
        "monitors": [monitor.to_dict() for monitor in monitors],
        "raw": data.hex().upper(),
    }
