from freerov3r.hardware.esp32_serial_adapter import parse_can_line


def test_parse_standard_classical_can_frame():
    frame = parse_can_line(b"S,00000123,2,0102\n", channel="COM4")
    assert frame is not None
    assert frame.arbitration_id == 0x123
    assert frame.data == bytes.fromhex("0102")
    assert frame.is_extended_id is False
    assert frame.channel == "COM4"


def test_parse_extended_classical_can_frame():
    frame = parse_can_line(b"E,18DAF110,8,032201F190000000\n")
    assert frame is not None
    assert frame.arbitration_id == 0x18DAF110
    assert frame.is_extended_id is True
    assert len(frame.data) == 8


def test_explicit_extended_flag_is_preserved_for_low_numeric_id():
    frame = parse_can_line(b"E,00000123,1,AA\n")
    assert frame is not None
    assert frame.arbitration_id == 0x123
    assert frame.is_extended_id is True


def test_legacy_three_field_protocol_remains_supported():
    standard = parse_can_line(b"00000123,2,0102\n")
    extended = parse_can_line(b"18DAF110,8,032201F190000000\n")
    assert standard is not None and not standard.is_extended_id
    assert extended is not None and extended.is_extended_id


def test_ignore_status_lines_boot_messages_and_malformed_frames():
    assert parse_can_line(b"#MODE,LISTEN_ONLY\n") is None
    assert parse_can_line(b"ESP32 boot complete\n") is None
    assert parse_can_line(b"00000123,3,0102\n") is None
    assert parse_can_line(b"S,20000000,1,00\n") is None
    assert parse_can_line(b"S,00000123,9,000000000000000000\n") is None



class FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.timeout = 0.2
        self.is_open = True

    def readline(self):
        return next(self.lines, b"")

    def close(self):
        self.is_open = False


def test_adapter_diagnostics_track_status_alerts_errors_and_frames():
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    adapter = Esp32SerialAdapter(port="COM9")
    adapter.connection = FakeSerial([
        b"#MODE,LISTEN_ONLY\n",
        b"#ALERT,RX_QUEUE_HIGH_WATER\n",
        b"#ERROR,BUS_OFF\n",
        b"S,00000123,2,0102\n",
    ])

    assert adapter.receive() is None
    assert adapter.receive() is None
    assert adapter.receive() is None
    frame = adapter.receive()

    assert frame is not None
    diagnostics = adapter.diagnostics
    assert diagnostics["connected"] is True
    assert diagnostics["frames_received"] == 1
    assert diagnostics["status_lines"] == 3
    assert diagnostics["alert_count"] == 1
    assert diagnostics["firmware_error_count"] == 1
    assert diagnostics["last_frame_age_seconds"] is not None
    assert diagnostics["last_status_age_seconds"] is not None
    assert diagnostics["last_error"] is None


def test_adapter_diagnostics_report_no_frame_age_before_first_frame():
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    diagnostics = Esp32SerialAdapter().diagnostics
    assert diagnostics["frames_received"] == 0
    assert diagnostics["last_frame_age_seconds"] is None
    assert diagnostics["status_lines"] == 0



def test_adapter_diagnostics_distinguish_connected_silent_and_receiving():
    import time
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    adapter = Esp32SerialAdapter(port="COM9")
    adapter.connection = FakeSerial([])
    assert adapter.diagnostics["receiver_state"] == "connected/silent"

    adapter.last_frame_monotonic = time.monotonic()
    assert adapter.diagnostics["receiver_state"] == "receiving"

    adapter.last_frame_monotonic = time.monotonic() - 3.0
    assert adapter.diagnostics["receiver_state"] == "connected/silent"


def test_adapter_diagnostics_report_disconnected_and_error_states():
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    adapter = Esp32SerialAdapter(port="COM9")
    assert adapter.diagnostics["receiver_state"] == "disconnected"

    adapter.last_error = "Port access denied"
    assert adapter.diagnostics["receiver_state"] == "disconnected/error"

    adapter.connection = FakeSerial([])
    adapter.firmware_error_count = 1
    assert adapter.diagnostics["receiver_state"] == "connected/error"


def test_adapter_alert_does_not_mark_receiver_as_fatal_error():
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    adapter = Esp32SerialAdapter(port="COM9")
    adapter.connection = FakeSerial([b"#ALERT,RX_QUEUE_HIGH_WATER\\n"])
    adapter.receive()
    assert adapter.diagnostics["receiver_state"] == "connected/silent"



def test_adapter_can_assign_logical_bus_name_independent_of_com_port():
    from freerov3r.hardware.esp32_serial_adapter import Esp32SerialAdapter

    adapter = Esp32SerialAdapter(port="COM7", channel_name="HS-CAN")
    adapter.connection = FakeSerial([b"S,00000123,1,AA\\n"])
    frame = adapter.receive()
    assert frame is not None
    assert frame.channel == "HS-CAN"
    assert adapter.diagnostics["port"] == "COM7"
