from freerov3r.diagnostics.dbc_signal_behavior import (\n    analyze_dbc_signal_behavior, build_dbc_signal_series,\n)


class FakeDecoded:
    message_name = "EngineData"
    units = {"EngineSpeed": "rpm", "Mode": ""}
    decoded = {"EngineSpeed": 1000.0, "Mode": 1}


class FakeMessage:
    length = 2


class FakeLibrary:
    database = object()
    path = None
    metadata = {"verification_status": "unverified"}
    messages_by_key = {(0x123, False): FakeMessage()}

    def decode(self, can_id, payload, extended=False):
        if can_id != 0x123 or extended or len(payload) != 2:
            return None
        result = FakeDecoded()
        result.decoded = {"EngineSpeed": float(payload[0] * 1000), "Mode": 1}
        return result


def _frame(value, elapsed=None):
    record = {"arbitration_id": 0x123, "extended": False, "data": f"{value:02X}00", "channel": "HS-CAN"}
    if elapsed is not None:
        record["elapsed_seconds"] = elapsed
    return record


def test_signal_behavior_reports_value_and_time_statistics():
    report = analyze_dbc_signal_behavior(
        FakeLibrary(),
        [_frame(1, 0.0), _frame(2, 0.5), _frame(4, 1.0), _frame(4, 1.5)],
    )
    assert report["matched_frames"] == 4
    assert report["signal_count"] == 2
    speed = next(row for row in report["signals"] if row["signal"] == "EngineSpeed")
    assert speed["min"] == 1000.0
    assert speed["max"] == 4000.0
    assert speed["mean"] == 2750.0
    assert speed["net_change"] == 3000.0
    assert speed["value_change_count"] == 2
    assert speed["average_sample_rate_hz"] == 2.0
    assert speed["max_absolute_rate_per_second"] == 4000.0


def test_missing_elapsed_time_keeps_value_samples_but_not_rate_estimates():
    report = analyze_dbc_signal_behavior(FakeLibrary(), [_frame(1), _frame(2)])
    speed = next(row for row in report["signals"] if row["signal"] == "EngineSpeed")
    assert speed["sample_count"] == 2
    assert speed["timed_sample_count"] == 0
    assert speed["average_sample_rate_hz"] is None
    assert speed["max_absolute_rate_per_second"] is None


def test_invalid_and_unmatched_frames_are_counted_separately():
    report = analyze_dbc_signal_behavior(
        FakeLibrary(),
        [_frame(1, 0.0), {"arbitration_id": 0x124, "data": "0100"}, [], {"arbitration_id": 0x123, "data": "01"}],
    )
    assert report["matched_frames"] == 1
    assert report["unmatched_frames"] == 2
    assert report["invalid_records"] == 1


def test_duplicate_and_out_of_order_timestamps_are_not_used_for_rates():
    report = analyze_dbc_signal_behavior(
        FakeLibrary(),
        [_frame(1, 1.0), _frame(2, 1.0), _frame(3, 0.5), _frame(4, 2.0)],
    )
    speed = next(row for row in report["signals"] if row["signal"] == "EngineSpeed")
    assert speed["duplicate_timestamps"] == 1
    assert speed["out_of_order_timestamps"] == 1
    assert speed["average_sample_rate_hz"] == 1.0


def test_no_dbc_returns_explicit_unavailable_report():
    report = analyze_dbc_signal_behavior(None, [_frame(1)])
    assert report["dbc_loaded"] is False
    assert report["unmatched_frames"] == 1
    assert report["signals"] == []



def test_graph_series_preserve_channel_identity_and_sort_timestamps():
    frames = [
        _frame(4, 2.0),
        _frame(1, 0.0),
        {**_frame(2, 1.0), "channel": "MS-CAN"},
        _frame(3, 1.0),
        {**_frame(4, 3.0), "elapsed_seconds": float("nan")},
    ]
    result = build_dbc_signal_series(
        FakeLibrary(), frames,
        [{"elapsed_seconds": 1.5, "operation": "Read live data", "note": "scanner"},
         {"elapsed_seconds": "bad", "operation": "ignored"}],
    )
    assert len(result["signals"]) == 2
    hs = next(item for item in result["signals"] if item["channel"] == "HS-CAN")
    ms = next(item for item in result["signals"] if item["channel"] == "MS-CAN")
    assert hs["samples"] == [(0.0, 1000.0), (1.0, 3000.0), (2.0, 4000.0)]
    assert ms["samples"] == [(1.0, 2000.0)]
    assert hs["minimum"] == 1000.0
    assert hs["maximum"] == 4000.0
    assert result["markers"] == [{
        "elapsed_seconds": 1.5,
        "label": "1. Read live data (scanner)",
    }]


def test_graph_series_without_dbc_is_empty():
    assert build_dbc_signal_series(None, [_frame(1, 0.0)]) == {
        "signals": [], "markers": []
    }
