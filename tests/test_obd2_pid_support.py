from freerov3r.diagnostics.obd2 import parse_mode01_supported_pids


def test_supported_pid_bitmap_decodes_msb_first():
    response = "7E8 06 41 00 00 10 00 00"
    assert parse_mode01_supported_pids(response, 0x00) == {0x0C}


def test_supported_pid_bitmap_decodes_next_range_and_continuation_bit():
    response = "7E8 06 41 20 80 00 00 01"
    assert parse_mode01_supported_pids(response, 0x20) == {0x21, 0x40}


def test_supported_pid_bitmap_accepts_multiple_ecu_lines():
    response = (
        "7E8 06 41 00 00 10 00 00\r"
        "7E9 06 41 00 00 08 00 00"
    )
    assert parse_mode01_supported_pids(response, 0x00) == {0x0C, 0x0D}


def test_supported_pid_bitmap_returns_empty_for_no_data():
    assert parse_mode01_supported_pids("NO DATA", 0x00) == set()


def test_supported_pid_bitmap_rejects_invalid_base():
    import pytest

    with pytest.raises(ValueError):
        parse_mode01_supported_pids("NO DATA", 0x10)
