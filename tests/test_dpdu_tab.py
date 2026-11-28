import pytest

from freerov3r.dpdu_tab import parse_hex_bytes, parse_uint32


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("600", 600),
        ("0x258", 600),
        ("4294967295", 0xFFFFFFFF),
    ],
)
def test_parse_uint32_accepts_decimal_and_hex(text, expected):
    assert parse_uint32(text, "Resource ID") == expected


@pytest.mark.parametrize("text", ["", "-1", "0x100000000", "12.5", "nope"])
def test_parse_uint32_rejects_invalid_values(text):
    with pytest.raises(ValueError):
        parse_uint32(text, "Resource ID")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FF", b"\xff"),
        ("62 F1 90", b"\x62\xf1\x90"),
        ("0x7E8", b"\x7e\x08"),
        ("7E:8F", b"\x7e\x8f"),
        ("7E,8F", b"\x7e\x8f"),
    ],
)
def test_parse_hex_bytes_accepts_common_separators(text, expected):
    assert parse_hex_bytes(text, "Response filter") == expected


@pytest.mark.parametrize("text", ["", "F", "GG", "0x"])
def test_parse_hex_bytes_rejects_invalid_or_incomplete_bytes(text):
    with pytest.raises(ValueError):
        parse_hex_bytes(text, "Response filter")
