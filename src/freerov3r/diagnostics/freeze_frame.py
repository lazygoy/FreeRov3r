"""Conservative SAE J1979 Mode 02 freeze-frame response decoding.

Mode 02 returns the same sensor data formats as Mode 01, but is associated
with a stored freeze-frame number. Only positive responses are decoded.
"""
from ..models import CanFrame
from .obd2 import PID_DEFINITIONS, decode_mode01_measurements


def decode_freeze_frame_response(payload, *, arbitration_id, is_extended_id=False,
                                 channel=None, frame_number=0, scaling_context=None):
    """Decode one complete Mode 02 positive response (42 PID frame A...).

    The caller must reassemble ISO-TP first. The frame number is retained as
    provenance and is not confused with a Mode 01 PID value.
    """
    data = bytes(payload or b"")
    if len(data) < 4 or data[0] != 0x42:
        raise ValueError("Expected a complete Mode 02 positive response")
    pid = data[1]
    response_frame = data[2]
    if response_frame != int(frame_number):
        raise ValueError("Freeze-frame response number does not match request")
    if pid not in PID_DEFINITIONS:
        raise ValueError(f"Unsupported standard Mode 02 PID: 0x{pid:02X}")

    # Reuse the tested Mode 01 scaling rules. Mode 02 carries the same PID
    # data-byte formats, with service 0x42 instead of 0x41.
    mode01_data = bytes((len(data) - 1, 0x41, pid)) + data[3:]
    frame = CanFrame(
        arbitration_id=int(arbitration_id),
        data=mode01_data,
        is_extended_id=bool(is_extended_id),
        channel=channel,
    )
    measurements = decode_mode01_measurements(frame, scaling_context)
    if not measurements:
        raise ValueError(f"Malformed or undecodable freeze-frame data for PID 0x{pid:02X}")

    return {
        "service": "02",
        "pid": f"{pid:02X}",
        "frame_number": response_frame,
        "arbitration_id": int(arbitration_id),
        "is_extended_id": bool(is_extended_id),
        "channel": channel,
        "raw": data.hex().upper(),
        "measurements": [
            {"key": key, "name": name, "value": value, "unit": unit}
            for _pid, key, name, value, unit in measurements
        ],
    }
