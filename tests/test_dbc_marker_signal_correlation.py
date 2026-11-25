import pytest

from freerov3r.diagnostics.dbc_signal_behavior import (
    summarize_dbc_marker_signal_changes,
)


def _series(channel="HS-CAN", can_id=0x123, signal="EngineSpeed", unit="rpm"):
    return {
        "can_id": can_id,
        "format": "STD",
        "channel": channel,
        "message": "EngineData",
        "signal": signal,
        "unit": unit,
        "samples": [
            (8.0, 900.0),
            (9.0, 1000.0),
            (10.0, 1200.0),
            (11.0, 1600.0),
            (12.0, 1800.0),
        ],
    }


def test_marker_signal_summary_reports_pre_post_means_and_first_sample_delay():
    result = summarize_dbc_marker_signal_changes(
        {"signals": [_series()]},
        [{"elapsed_seconds": 10.0, "operation": "Read live data"}],
        before_seconds=2.0,
        after_seconds=2.0,
    )

    assert len(result) == 1
    marker = result[0]
    signal = marker["signals"][0]
    assert signal["before_sample_count"] == 2
    assert signal["after_sample_count"] == 3
    assert signal["before_mean"] == 950.0
    assert signal["after_mean"] == 1533.3333333333333
    assert abs(signal["mean_delta"] - 583.3333333333333) < 1e-9
    assert signal["first_after_marker_seconds"] == 0.0
    assert "does not establish causation" in marker["interpretation"]


def test_marker_signal_summary_keeps_channels_and_signals_separate():
    result = summarize_dbc_marker_signal_changes(
        {"signals": [
            _series(channel="HS-CAN"),
            _series(channel="MS-CAN"),
            _series(channel="HS-CAN", can_id=0x456, signal="Throttle"),
        ]},
        [{"elapsed_seconds": 10.0}],
    )

    assert result[0]["signal_count"] == 3
    assert {item["channel"] for item in result[0]["signals"]} == {"HS-CAN", "MS-CAN"}
    assert {item["can_id"] for item in result[0]["signals"]} == {0x123, 0x456}


def test_marker_signal_summary_reports_missing_window_without_fake_delta():
    series = _series()
    series["samples"] = [(10.5, 42.0), (11.0, 44.0)]
    result = summarize_dbc_marker_signal_changes(
        {"signals": [series]},
        [{"elapsed_seconds": 10.0}],
    )

    signal = result[0]["signals"][0]
    assert signal["before_sample_count"] == 0
    assert signal["after_sample_count"] == 2
    assert signal["before_mean"] is None
    assert signal["mean_delta"] is None


def test_marker_signal_summary_skips_invalid_marker_and_samples():
    series = _series()
    series["samples"] = [(9.0, 1.0), ("bad", 2.0), (10.5, float("nan"))]
    result = summarize_dbc_marker_signal_changes(
        {"signals": [series]},
        [{"elapsed_seconds": "invalid"}, {"elapsed_seconds": 10.0}],
    )
    assert len(result) == 1
    assert result[0]["signals"][0]["before_sample_count"] == 1
    assert result[0]["signals"][0]["after_sample_count"] == 0


def test_marker_signal_summary_rejects_negative_windows():
    with pytest.raises(ValueError):
        summarize_dbc_marker_signal_changes(
            {"signals": []}, [{"elapsed_seconds": 1.0}], before_seconds=-1
        )
