from collections import deque

import pytest

from freerov3r.hardware.elm327_obd_adapter import Elm327ObdAdapter


class FakeSerial:
    def __init__(self, *args, responses=None, **kwargs):
        self.commands = []
        self.responses = deque(responses or [
            b"ELM327 v1.5\r>",
            b"OK\r>",
            b"OK\r>",
            b"OK\r>",
            b"OK\r>",
            b"OK\r>",
            b"OK\r>",
            # PID 0C is supported; PID 20 is not, so discovery stops here.
            b"7E8 06 41 00 00 10 00 00\r>",
            b"7E8 04 41 0C 1A F8\r>",
        ])
        self.timeout = kwargs.get("timeout", 0.2)

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.commands.append(data.decode("ascii").strip())

    def flush(self):
        pass

    def read_until(self, marker):
        return self.responses.popleft() if self.responses else b""

    def close(self):
        pass


def test_elm327_obd_adapter_discovers_support_before_polling(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial()
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C], request_interval=0.05)
    adapter.open()
    try:
        frame = adapter.receive(timeout=0.1)
        assert frame is not None
        assert frame.arbitration_id == 0x7E8
        assert frame.data == bytes([4, 0x41, 0x0C, 0x1A, 0xF8])
        assert fake.commands.index("0100") < fake.commands.index("010C")
        assert "0120" not in fake.commands
        assert adapter.supported_pids == {0x0C}
        assert adapter.pids == (0x0C,)
        assert adapter.unsupported_pids == set()
        assert adapter.discovery_complete
        assert adapter.requests_sent == 1
        assert adapter.responses_received == 1
    finally:
        adapter.close()


def test_elm327_obd_adapter_refuses_to_poll_unsupported_selection(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x05])
    with pytest.raises(RuntimeError, match="None of the selected PIDs"):
        adapter.open()
    assert "0105" not in fake.commands
    assert adapter.requests_sent == 0


def test_elm327_obd_adapter_rejects_unknown_pids():
    with pytest.raises(ValueError):
        Elm327ObdAdapter("COM9", pids=[0xFE])


def test_elm327_obd_adapter_polls_pid_4f_as_a_hidden_wideband_dependency(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        # PID 20 advertises PID 40; PID 40 advertises PID 4F.
        b"7E8 06 41 00 00 00 00 01\r>",
        b"7E8 06 41 20 10 00 00 01\r>",
        b"7E8 06 41 40 00 02 00 00\r>",
        b"7E8 06 41 24 7D 00 9C 40\r>",
        b"7E8 06 41 4F 04 10 40 00\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x24], request_interval=0.05)
    adapter.open()
    try:
        assert adapter.pids == (0x24,)
        assert adapter._poll_pids == (0x24, 0x4F)
        first = adapter.receive(timeout=0.1)
        second = adapter.receive(timeout=0.1)
        assert first is not None and first.data[2] == 0x24
        assert second is not None and second.data[2] == 0x4F
        assert "0124" in fake.commands
        assert "014F" in fake.commands
    finally:
        adapter.close()



def test_elm327_obd_adapter_accepts_29_bit_physical_response_headers(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"18DAF110 06 41 00 00 10 00 00\r>",
        b"18DAF110 04 41 0C 1A F8\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C], request_interval=0.05)
    adapter.open()
    try:
        frame = adapter.receive(timeout=0.1)
        assert frame is not None
        assert frame.arbitration_id == 0x18DAF110
        assert frame.is_extended_id is True
        assert frame.data == bytes([4, 0x41, 0x0C, 0x1A, 0xF8])
    finally:
        adapter.close()
