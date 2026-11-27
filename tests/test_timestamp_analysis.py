import pytest

from freerov3r.timestamp_analysis import analyze_channel_timestamps


def _record(channel, host, device):
    return {
        "channel": channel,
        "timestamp": host,
        "device_timestamp_us": device,
        "arbitration_id": 0x123,
        "data": "010203",
    }


def test_timestamp_analysis_separates_independent_channels():
    records = [
        _record("HS-CAN", 10.0, 1_000_000),
        _record("MS-CAN", 10.1, 5_000_000),
        _record("HS-CAN", 10.01, 1_010_000),
        _record("MS-CAN", 10.11, 5_010_000),
    ]
    result = analyze_channel_timestamps(records)
    assert result["channel_count"] == 2
    channels = {item["channel"]: item for item in result["channels"]}
    assert channels["HS-CAN"]["timed_frame_count"] == 2
    assert channels["MS-CAN"]["timed_frame_count"] == 2
    assert channels["HS-CAN"]["clock_fit"]["drift_ppm"] == pytest.approx(0)
    assert channels["MS-CAN"]["clock_fit"]["drift_ppm"] == pytest.approx(0)


def test_timestamp_analysis_counts_missing_invalid_and_nonmonotonic_values():
    records = [
        _record("HS-CAN", 1.0, 100),
        {**_record("HS-CAN", 1.01, None)},
        _record("HS-CAN", 1.02, 90),
        {**_record("HS-CAN", 1.03, -1)},
        _record("HS-CAN", 1.04, 90),
    ]
    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["missing_device_timestamp_count"] == 1
    assert item["invalid_device_timestamp_count"] == 1
    assert item["non_monotonic_device_steps"] == 1
    assert item["duplicate_device_timestamps"] == 1


def test_timestamp_analysis_flags_gaps_and_reports_fit_residuals():
    records = [
        _record("HS-CAN", 0.0, 0),
        _record("HS-CAN", 0.1, 100_000),
        _record("HS-CAN", 2.1, 2_100_000),
    ]
    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["suspicious_device_gaps"] == 1
    assert item["suspicious_host_gaps"] == 1
    assert item["clock_fit"]["residual_p95_ms"] == pytest.approx(0)


def test_timestamp_analysis_handles_too_few_samples_and_missing_channels():
    result = analyze_channel_timestamps([
        _record(None, 1.0, 10),
        _record("", 1.1, 20),
    ])
    item = result["channels"][0]
    assert item["channel"] == "unspecified"
    assert result["frames_without_channel"] == 2
    assert item["clock_fit"] is None
    assert item["timing_quality"] == "insufficient data"


def test_timestamp_analysis_rejects_invalid_gap_threshold():
    with pytest.raises(ValueError, match="positive"):
        analyze_channel_timestamps([], suspicious_gap_seconds=0)



def test_timestamp_analysis_detects_host_clock_regressions_and_suppresses_fit():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 1.1, 1_100_000),
        _record("HS-CAN", 1.05, 1_200_000),
    ]

    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["non_monotonic_host_steps"] == 1
    assert item["duplicate_host_timestamps"] == 0
    assert item["clock_fit"] is None
    assert item["timing_quality"] == "check monotonicity/gaps"


def test_timestamp_analysis_detects_duplicate_clocks_and_rejects_fractional_device_time():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 1.1, 1_100_000.5),
    ]

    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["duplicate_device_timestamps"] == 1
    assert item["duplicate_host_timestamps"] == 1
    assert item["invalid_device_timestamp_count"] == 1
    assert item["clock_fit"] is None
    assert item["timing_quality"] == "check monotonicity/gaps"


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf"), True, 0, -1])
def test_timestamp_analysis_rejects_non_finite_or_non_positive_gap_thresholds(threshold):
    with pytest.raises(ValueError, match="finite positive"):
        analyze_channel_timestamps([], suspicious_gap_seconds=threshold)


def test_timestamp_analysis_rejects_boolean_host_timestamps():
    records = [
        _record("HS-CAN", True, 1_000_000),
        _record("HS-CAN", 1.1, 1_100_000),
    ]
    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["invalid_host_timestamp_count"] == 1
    assert item["timed_frame_count"] == 1
    assert item["clock_fit"] is None


def test_host_clock_quality_includes_frames_without_device_timestamps():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 1.1, None),
        _record("HS-CAN", 1.05, 1_200_000),
    ]
    item = analyze_channel_timestamps(records)["channels"][0]
    assert item["missing_device_timestamp_count"] == 1
    assert item["non_monotonic_host_steps"] == 1
    assert item["clock_fit"] is None
    assert item["timing_quality"] == "check monotonicity/gaps"


def test_host_clock_gaps_include_frames_with_invalid_device_timestamps():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 2.5, -1),
        _record("HS-CAN", 2.6, 1_100_000),
    ]
    item = analyze_channel_timestamps(records, suspicious_gap_seconds=1.0)["channels"][0]
    assert item["invalid_device_timestamp_count"] == 1
    assert item["suspicious_host_gaps"] == 1
    assert item["median_host_interval_ms"] == pytest.approx(800.0)



def test_timestamp_analysis_reports_apparent_pairwise_clock_relationship():
    records = [
        _record("HS-CAN", 10.0, 1_000_000),
        _record("MS-CAN", 10.02, 5_000_000),
        _record("HS-CAN", 10.1, 1_100_000),
        _record("MS-CAN", 10.12, 5_100_000),
        _record("HS-CAN", 10.2, 1_200_000),
        _record("MS-CAN", 10.22, 5_200_000),
    ]

    result = analyze_channel_timestamps(records)
    comparison = result["pairwise_clock_comparisons"][0]

    assert comparison["channel_a"] == "HS-CAN"
    assert comparison["channel_b"] == "MS-CAN"
    assert comparison["status"] == "apparent relationship; not synchronized"
    assert comparison["overlap_duration_seconds"] == pytest.approx(0.18)
    assert comparison["apparent_relative_drift_ppm"] == pytest.approx(0, abs=1e-6)
    assert comparison["combined_host_fit_residual_p95_ms"] >= 0
    assert "does not bound" in comparison["uncertainty_note"]


def test_timestamp_analysis_marks_non_overlapping_channel_captures():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("HS-CAN", 1.1, 1_100_000),
        _record("MS-CAN", 5.0, 5_000_000),
        _record("MS-CAN", 5.1, 5_100_000),
    ]

    comparison = analyze_channel_timestamps(records)["pairwise_clock_comparisons"][0]
    assert comparison["status"] == "no overlapping host-time coverage"
    assert comparison["overlap_duration_seconds"] == 0.0


def test_timestamp_analysis_skips_pairwise_comparison_without_valid_clock_fits():
    records = [
        _record("HS-CAN", 1.0, 1_000_000),
        _record("MS-CAN", 1.1, 5_000_000),
    ]

    result = analyze_channel_timestamps(records)
    assert result["pairwise_clock_comparisons"] == []
