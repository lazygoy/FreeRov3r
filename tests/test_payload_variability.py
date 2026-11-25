from freerov3r.diagnostics.payload_variability import analyze_payload_variability


def _frame(data, can_id=0x321, channel="HS-CAN", extended=False):
    return {"arbitration_id": can_id, "channel": channel,
            "extended": extended, "data": data}


def test_reports_constant_and_variable_bytes_and_bit_transitions():
    report = analyze_payload_variability([
        _frame("AA 00"), _frame("AA 01"), _frame("AA 03"),
    ])
    assert report["transmission_performed"] is False
    assert report["node_count"] == 1
    node = report["nodes"][0]
    assert node["variable_byte_offsets"] == [1]
    assert node["constant_byte_offsets"] == [0]
    assert node["bytes"][0]["constant"] is True
    assert node["bytes"][0]["most_common_value"] == 0xAA
    assert node["bytes"][1]["unique_value_count"] == 3
    assert node["bytes"][1]["bit_transition_counts_msb_first"] == [0, 0, 0, 0, 0, 0, 1, 1]
    assert node["bytes"][1]["variable_bit_mask"] == 0x03


def test_keeps_channels_formats_and_payload_lengths_separate():
    report = analyze_payload_variability([
        _frame("01 02", channel="HS-CAN"),
        _frame("01 02 03", channel="HS-CAN"),
        _frame("01 02", channel="MS-CAN"),
        _frame("01 02", channel="HS-CAN", extended=True),
    ])
    assert report["node_count"] == 4
    assert {(n["channel"], n["extended"], n["dlc"]) for n in report["nodes"]} == {
        ("HS-CAN", False, 2), ("HS-CAN", False, 3),
        ("MS-CAN", False, 2), ("HS-CAN", True, 2),
    }


def test_counts_identical_payloads_without_false_bit_transitions():
    node = analyze_payload_variability([
        _frame("FF 10"), _frame("FF 10"), _frame("FF 10"),
    ])["nodes"][0]
    assert node["frame_count"] == 3
    assert node["variable_byte_offsets"] == []
    assert node["bytes"][0]["bit_transition_counts_msb_first"] == [0] * 8
    assert node["bytes"][1]["unique_value_count"] == 1


def test_rejects_malformed_records_and_out_of_range_identifiers():
    report = analyze_payload_variability([
        _frame("not-hex"), {"data": "00"},
        _frame("00", can_id=0x20000000), _frame("00" * 65),
    ])
    assert report["nodes"] == []
    assert report["invalid_record_count"] == 4


def test_empty_input_returns_empty_report():
    report = analyze_payload_variability([])
    assert report["node_count"] == 0
    assert report["input_frame_count"] == 0
