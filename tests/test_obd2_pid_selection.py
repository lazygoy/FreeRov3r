from freerov3r.diagnostics.obd2 import (
    PID_CATEGORIES,
    PID_CATEGORIES_ALL,
    search_mode01_pids,
)


def test_pid_categories_cover_every_defined_pid():
    from freerov3r.diagnostics.obd2 import PID_DEFINITIONS

    assert set(PID_CATEGORIES) == set(PID_DEFINITIONS)
    assert "All" in PID_CATEGORIES_ALL


def test_pid_search_finds_common_workshop_sensor_names():
    assert [row[0] for row in search_mode01_pids("coolant")] == ["05"]
    assert [row[0] for row in search_mode01_pids("rpm")] == ["0C"]
    assert [row[0] for row in search_mode01_pids("battery voltage")] == ["42"]


def test_pid_category_filter_is_applied_with_search():
    rows = search_mode01_pids(category="Temperatures")
    assert {row[0] for row in rows} == {"05", "0F", "3C", "3D", "3E", "3F", "46", "5C"}
    assert search_mode01_pids("rpm", "Temperatures") == []


def test_pid_search_matches_hex_pid_and_unit():
    assert [row[0] for row in search_mode01_pids("0C")] == ["0C"]
    from freerov3r.diagnostics.obd2 import PID_DEFINITIONS

    expected = {
        f"{pid:02X}"
        for pid, (_, unit) in PID_DEFINITIONS.items()
        if "%" in unit
    }
    assert {row[0] for row in search_mode01_pids("%")} == expected
