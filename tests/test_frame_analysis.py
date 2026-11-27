from freerov3r.core.capture.frame_analysis import FrameAnalysis, analyze_frame
from freerov3r.diagnostics.obd2 import Mode01ScalingContext
from freerov3r.diagnostics.vin_decoder import VinFrameDecoder
from freerov3r.models import CanFrame


VIN = "SALXXXXXXXXXXXX12"


def _isotp_frames(payload, can_id=0x7E8):
    payload = bytes(payload)
    first = bytes([
        0x10 | ((len(payload) >> 8) & 0x0F),
        len(payload) & 0xFF,
    ]) + payload[:6]
    frames = [first]
    remaining = payload[6:]
    sequence = 1
    while remaining:
        frames.append(bytes([0x20 | sequence]) + remaining[:7])
        remaining = remaining[7:]
        sequence = (sequence + 1) & 0x0F
    return [frame.ljust(8, b"\\x00") for frame in frames]


def test_frame_analysis_is_qt_independent_and_returns_empty_result():
    result = analyze_frame(
        CanFrame(arbitration_id=0x123, data=b""),
        vin_decoder=VinFrameDecoder(),
        scaling_context=Mode01ScalingContext(),
    )

    assert result == FrameAnalysis()


def test_frame_analysis_reassembles_vin_across_multiple_frames():
    decoder = VinFrameDecoder()
    context = Mode01ScalingContext()
    payload = b"\\x49\\x02\\x01" + VIN.encode("ascii")
    results = [
        analyze_frame(
            CanFrame(arbitration_id=0x7E8, data=frame),
            vin_decoder=decoder,
            scaling_context=context,
        )
        for frame in _isotp_frames(payload)
    ]

    assert results[-1].detected_vin == VIN
    assert all(isinstance(result, FrameAnalysis) for result in results)
    assert all(not result.measurements for result in results)
