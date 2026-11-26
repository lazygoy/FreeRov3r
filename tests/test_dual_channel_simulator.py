import pytest

from freerov3r.hardware.dual_channel_simulator import DualChannelSimulator


def test_simulator_emits_both_channels_with_expected_bitrates():
    simulator = DualChannelSimulator()
    simulator.open()
    try:
        frames = [simulator.receive(timeout=0.1) for _ in range(7)]
        assert {frame.channel for frame in frames} == {"HS-CAN", "MS-CAN"}
        assert all(frame.timestamp_clock_domain == "host_monotonic" for frame in frames)
        assert all(frame.timestamp_source == "simulator" for frame in frames)
        assert all(frame.source_timestamp_clock_domain == "simulator_elapsed" for frame in frames)
        assert simulator.diagnostics["frames_generated"] == 7
    finally:
        simulator.close()


def test_simulator_is_repeatable_after_reopen():
    simulator = DualChannelSimulator(speed=1000)
    simulator.open()
    first = [(f.channel, f.arbitration_id, f.data) for f in
             (simulator.receive(0.1), simulator.receive(0.1), simulator.receive(0.1))]
    simulator.close()
    simulator.open()
    second = [(f.channel, f.arbitration_id, f.data) for f in
              (simulator.receive(0.1), simulator.receive(0.1), simulator.receive(0.1))]
    simulator.close()
    assert first == second


def test_simulator_can_run_one_channel_only():
    simulator = DualChannelSimulator(channels=("MS-CAN",), speed=1000)
    simulator.open()
    try:
        frames = [simulator.receive(0.1) for _ in range(4)]
        assert all(frame.channel == "MS-CAN" for frame in frames)
    finally:
        simulator.close()


def test_simulator_rejects_invalid_channel_and_speed():
    with pytest.raises(ValueError):
        DualChannelSimulator(channels=("HS-CAN", "unknown"))
    for speed in (0, -1, float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            DualChannelSimulator(speed=speed)


def test_simulator_requires_open_before_receive():
    simulator = DualChannelSimulator()
    with pytest.raises(RuntimeError, match="not open"):
        simulator.receive(0)
