from freerov3r.core.capture.session_context import CaptureSessionContext


def test_capture_context_keeps_vehicle_and_capture_boundaries_together():
    context = CaptureSessionContext.begin(
        interface="esp32_dual",
        channel="COM4,COM5",
        bitrate=500000,
        vin="SALAN2D4XAA123456",
        frame_start_index=120,
        sample_start_index=450,
        started_at=100.0,
    )

    assert context.interface == "esp32_dual"
    assert context.channel == "COM4,COM5"
    assert context.vin == "SALAN2D4XAA123456"
    assert context.frame_start_index == 120
    assert context.sample_start_index == 450


def test_capture_context_elapsed_time_never_goes_negative():
    context = CaptureSessionContext.begin(
        interface="socketcan", channel="can0", bitrate=500000,
        vin=None, frame_start_index=0, sample_start_index=0,
        started_at=10.0,
    )

    assert context.elapsed_seconds(now=9.0) == 0.0
    assert context.elapsed_seconds(now=12.5) == 2.5


def test_capture_context_event_metadata_preserves_counts_and_identity():
    context = CaptureSessionContext.begin(
        interface="esp32", channel="COM4", bitrate=500000,
        vin="SALAN2D4XAA123456", frame_start_index=3,
        sample_start_index=8, started_at=100.0,
    )

    metadata = context.event_metadata(
        frame_count=25, sample_count=12, dropped_samples=2
    )

    assert metadata == {
        "interface": "esp32",
        "channel": "COM4",
        "bitrate": 500000,
        "frames": 25,
        "sensor_samples": 12,
        "sensor_samples_dropped_from_bounded_buffer": 2,
        "duration_seconds": metadata["duration_seconds"],
    }
