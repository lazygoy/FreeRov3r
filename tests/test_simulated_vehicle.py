from freerov3r.hardware.simulated_vehicle import SimulatedVehicleAdapter, decode_mode01
from freerov3r.models import CanFrame


def test_decode_standard_mode01_rpm_response():
    frame = CanFrame(0x7E8, bytes([4, 0x41, 0x0C, 0x1A, 0xF0, 0, 0, 0]))
    decoded = decode_mode01(frame)
    assert decoded == (0x0C, "Engine speed", 1724.0, "rpm")


def test_decoder_ignores_unrelated_frames():
    assert decode_mode01(CanFrame(0x123, bytes([4, 0x41, 0x0C, 0, 0]))) is None
    assert decode_mode01(CanFrame(0x7E8, bytes([3, 0x7F, 0x01, 0, 0]))) is None


def test_simulator_emits_decodable_obd_frames():
    adapter = SimulatedVehicleAdapter(update_interval=0)
    adapter.open()
    try:
        decoded = []
        for _ in range(12):
            frame = adapter.receive(timeout=0.01)
            assert frame is not None
            assert frame.arbitration_id == 0x7E8
            assert len(frame.data) == 8
            decoded.append(decode_mode01(frame))
        assert all(item is not None for item in decoded)
        assert {item[0] for item in decoded} == set(adapter._pids)
    finally:
        adapter.close()
