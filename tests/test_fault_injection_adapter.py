import pytest

from freerov3r.hardware.fault_injection_adapter import FaultInjectingCanAdapter
from freerov3r.models import CanFrame


class FakeAdapter:
    description = "fake receive-only adapter"

    def __init__(self, frames):
        self.frames = list(frames)
        self.opened = False
        self.received = 0

    def open(self):
        self.opened = True
        self.received = 0

    def close(self):
        self.opened = False

    def receive(self, timeout=0.2):
        if not self.opened:
            raise RuntimeError("underlying adapter closed")
        if self.received >= len(self.frames):
            return None
        frame = self.frames[self.received]
        self.received += 1
        return frame


def _frames(count=5):
    return [CanFrame(0x100 + index, bytes([index])) for index in range(count)]


def test_fault_adapter_requires_open_and_never_changes_source_frames():
    source_frames = _frames(2)
    source = FakeAdapter(source_frames)
    adapter = FaultInjectingCanAdapter(source)

    with pytest.raises(RuntimeError, match="not open"):
        adapter.receive(0)

    adapter.open()
    assert adapter.receive(0) == source_frames[0]
    assert adapter.receive(0) == source_frames[1]
    assert adapter.diagnostics["transmission_performed"] is False
    adapter.close()
    assert source.opened is False


def test_fault_adapter_drops_every_nth_source_frame_deterministically():
    adapter = FaultInjectingCanAdapter(FakeAdapter(_frames()), drop_every=2)
    adapter.open()

    received = [adapter.receive(0) for _ in range(5)]

    assert [frame.arbitration_id for frame in received if frame] == [0x100, 0x102, 0x104]
    assert adapter.diagnostics["frames_seen"] == 5
    assert adapter.diagnostics["frames_dropped"] == 2
    assert adapter.diagnostics["frames_emitted"] == 3
    adapter.close()


def test_fault_adapter_duplicates_every_nth_source_frame_in_order():
    adapter = FaultInjectingCanAdapter(FakeAdapter(_frames(3)), duplicate_every=2)
    adapter.open()

    received = [adapter.receive(0) for _ in range(4)]

    assert [frame.arbitration_id for frame in received] == [
        0x100, 0x101, 0x101, 0x102
    ]
    assert adapter.diagnostics["frames_duplicated"] == 1
    assert adapter.diagnostics["frames_emitted"] == 4
    adapter.close()


def test_fault_adapter_simulates_disconnect_after_configured_source_frames():
    adapter = FaultInjectingCanAdapter(FakeAdapter(_frames()), disconnect_after=2)
    adapter.open()

    assert adapter.receive(0).arbitration_id == 0x100
    assert adapter.receive(0).arbitration_id == 0x101
    with pytest.raises(ConnectionError, match="Simulated CAN adapter disconnect"):
        adapter.receive(0)
    with pytest.raises(ConnectionError, match="Simulated CAN adapter disconnect"):
        adapter.receive(0)
    assert adapter.diagnostics["disconnected"] is True
    adapter.close()


def test_reopening_fault_adapter_resets_fault_state_and_counters():
    adapter = FaultInjectingCanAdapter(FakeAdapter(_frames(3)), disconnect_after=1)
    adapter.open()
    adapter.receive(0)
    with pytest.raises(ConnectionError):
        adapter.receive(0)
    adapter.close()

    adapter.open()
    assert adapter.diagnostics["disconnected"] is False
    assert adapter.diagnostics["frames_seen"] == 0
    assert adapter.receive(0).arbitration_id == 0x100
    adapter.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"drop_every": -1},
        {"drop_every": True},
        {"drop_every": 1.5},
        {"duplicate_every": -1},
        {"duplicate_every": "2"},
        {"disconnect_after": 0},
        {"disconnect_after": False},
    ],
)
def test_fault_adapter_rejects_invalid_fault_intervals(kwargs):
    with pytest.raises(ValueError):
        FaultInjectingCanAdapter(FakeAdapter(_frames()), **kwargs)
