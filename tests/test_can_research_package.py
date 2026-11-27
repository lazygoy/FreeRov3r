from freerov3r.can_research import analyze_message_periodicity, discover_modules
from freerov3r.diagnostics.can_timing_analysis import (
    analyze_message_periodicity as legacy_timing,
)
from freerov3r.diagnostics.module_discovery import (
    discover_modules as legacy_discovery,
)


def test_can_research_package_exports_passive_analyzers():
    frames = [
        {"timestamp": 1.0, "arbitration_id": 0x321, "extended": False,
         "channel": "HS-CAN", "data": "0102"},
        {"timestamp": 1.01, "arbitration_id": 0x321, "extended": False,
         "channel": "HS-CAN", "data": "0103"},
    ]

    timing = analyze_message_periodicity(frames)
    discovery = discover_modules(frames)

    assert timing["transmission_performed"] is False
    assert timing["node_count"] == 1
    assert discovery["transmission_performed"] is False
    assert discovery["valid_observed_id_count"] == 1


def test_legacy_diagnostics_imports_remain_compatible():
    assert legacy_timing is analyze_message_periodicity
    assert legacy_discovery is discover_modules
