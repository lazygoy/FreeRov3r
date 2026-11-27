"""UI-independent CAN frame analysis shared by Diagnostic and Research."""

from dataclasses import dataclass

from ...diagnostics.obd2 import decode_mode01_measurements


@dataclass(frozen=True)
class FrameAnalysis:
    detected_vin: str | None = None
    measurements: tuple = ()


def analyze_frame(frame, *, vin_decoder, scaling_context) -> FrameAnalysis:
    """Decode supported observations from one frame without touching UI state.

    The VIN decoder is stateful because ISO-TP responses may span multiple CAN
    frames. Call this once per received frame and preserve the decoder for the
    duration of the capture.
    """
    detected_vin = vin_decoder.feed(
        frame.arbitration_id, bytes(frame.data)
    )
    measurements = tuple(decode_mode01_measurements(frame, scaling_context) or ())
    return FrameAnalysis(
        detected_vin=detected_vin,
        measurements=measurements,
    )
