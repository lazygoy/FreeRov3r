import pytest

from freerov3r.hardware.clock_sync import (
    calculate_clock_sync_sample,
    estimate_clock_mapping,
    compare_clock_mappings,
)


def test_clock_sync_sample_calculates_offset_and_round_trip_delay():
    sample = calculate_clock_sync_sample(
        host_send_time_ns=1_000_000_000,
        device_receive_time_us=1_000_100,
        device_send_time_us=1_000_110,
        host_receive_time_ns=1_000_030_000,
    )

    assert sample["device_minus_host_offset_ns"] == pytest.approx(90_000)
    assert sample["round_trip_delay_ns"] == pytest.approx(29_990_000)
    assert sample["symmetric_path_uncertainty_floor_ns"] == pytest.approx(14_995_000)


def test_clock_sync_rejects_invalid_timestamp_order_and_types():
    with pytest.raises(ValueError, match="non-negative integers"):
        calculate_clock_sync_sample(
            host_send_time_ns=True,
            device_receive_time_us=1,
            device_send_time_us=2,
            host_receive_time_ns=3,
        )
    with pytest.raises(ValueError, match="precedes"):
        calculate_clock_sync_sample(
            host_send_time_ns=10,
            device_receive_time_us=1,
            device_send_time_us=2,
            host_receive_time_ns=9,
        )
    with pytest.raises(ValueError, match="negative"):
        calculate_clock_sync_sample(
            host_send_time_ns=0,
            device_receive_time_us=10,
            device_send_time_us=11,
            host_receive_time_ns=500,
        )


def test_clock_mapping_selects_lowest_round_trip_samples_and_estimates_drift():
    samples = []
    for index in range(5):
        device_ns = index * 1_000_000_000
        host_ns = 5_000_000_000 + device_ns * 1.0001
        samples.append({
            "device_midpoint_time_ns": device_ns,
            "host_midpoint_time_ns": host_ns,
            "round_trip_delay_ns": 10_000_000 if index == 0 else 1_000_000,
            "device_minus_host_offset_ns": host_ns - device_ns,
        })

    result = estimate_clock_mapping(samples, best_sample_count=4)

    assert result["status"] == "estimated; transport asymmetry unbounded"
    assert result["sample_count"] == 4
    assert result["minimum_round_trip_delay_ns"] == 1_000_000
    assert result["drift_ppm"] == pytest.approx(100.0)
    assert result["mapping"]["slope"] == pytest.approx(1.0001)
    assert "not bounded" in result["uncertainty_note"]


def test_clock_mapping_reports_insufficient_samples_or_clock_span():
    assert estimate_clock_mapping([])["mapping"] is None
    samples = [
        {
            "device_midpoint_time_ns": 100,
            "host_midpoint_time_ns": 200,
            "round_trip_delay_ns": 10,
            "device_minus_host_offset_ns": 100,
        },
        {
            "device_midpoint_time_ns": 100,
            "host_midpoint_time_ns": 201,
            "round_trip_delay_ns": 10,
            "device_minus_host_offset_ns": 101,
        },
    ]
    assert estimate_clock_mapping(samples)["status"] == "insufficient device clock span"



def test_compare_clock_mappings_uses_only_shared_host_calibration_coverage():
    mapping_a = {
        "host_coverage_start_ns": 100,
        "host_coverage_end_ns": 1_000_000_100,
        "fit_residual_p95_ns": 100,
        "symmetric_path_uncertainty_floor_ns": 500,
        "mapping": {"intercept_ns": 0, "slope": 1.0},
    }
    mapping_b = {
        "host_coverage_start_ns": 200,
        "host_coverage_end_ns": 900_000_200,
        "fit_residual_p95_ns": 200,
        "symmetric_path_uncertainty_floor_ns": 700,
        "mapping": {"intercept_ns": 1_000_000, "slope": 1.0},
    }

    result = compare_clock_mappings(mapping_a, mapping_b)

    assert result["status"] == "calibrated apparent relationship; asymmetry unbounded"
    assert result["host_overlap_start_ns"] == 200
    assert result["host_overlap_end_ns"] == 900_000_200
    assert result["apparent_device_offset_start_ns"] == pytest.approx(-1_000_000)
    assert result["apparent_device_offset_end_ns"] == pytest.approx(-1_000_000)
    assert result["combined_fit_residual_p95_ns"] == 300
    assert result["combined_symmetric_path_uncertainty_floor_ns"] == 1200


def test_compare_clock_mappings_rejects_missing_or_non_overlapping_calibration():
    missing = {"mapping": None}
    valid = {
        "host_coverage_start_ns": 10,
        "host_coverage_end_ns": 20,
        "mapping": {"intercept_ns": 0, "slope": 1.0},
    }
    assert compare_clock_mappings(missing, valid)["comparison"] is None
    later = {
        "host_coverage_start_ns": 30,
        "host_coverage_end_ns": 40,
        "mapping": {"intercept_ns": 0, "slope": 1.0},
    }
    assert compare_clock_mappings(valid, later)["status"] == "no overlapping calibration coverage"
