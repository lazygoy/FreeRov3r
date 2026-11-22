from freerov3r.hardware.esp32_serial_adapter import parse_can_line


def test_parse_standard_classical_can_frame():
    frame = parse_can_line(b"00000123,2,0102\n", channel="COM4")
    assert frame is not None
    assert frame.arbitration_id == 0x123
    assert frame.data == bytes.fromhex("0102")
    assert frame.is_extended_id is False
    assert frame.channel == "COM4"


def test_parse_extended_classical_can_frame():
    frame = parse_can_line(b"18DAF110,8,032201F190000000\n")
    assert frame is not None
    assert frame.arbitration_id == 0x18DAF110
    assert frame.is_extended_id is True
    assert len(frame.data) == 8


def test_ignore_boot_messages_and_malformed_lines():
    assert parse_can_line(b"ESP32 boot complete\n") is None
    assert parse_can_line(b"00000123,3,0102\n") is None
    assert parse_can_line(b"20000000,1,00\n") is None
    assert parse_can_line(b"00000123,9,000000000000000000\n") is None
