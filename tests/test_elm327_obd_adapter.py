from collections import deque

import pytest

from freerov3r.hardware.elm327_obd_adapter import Elm327ObdAdapter


class FakeSerial:
    def __init__(self, *args, responses=None, **kwargs):
        self.commands = []
        self.responses = deque(responses or [
            b"ELM327 v1.5\\r>",
            b"OK\\r>",
            b"OK\\r>",
            b"OK\\r>",
            b"OK\\r>",
            b"OK\\r>",
            b"OK\\r>",
            # PID 0C is supported; PID 20 is not, so discovery stops here.
            b"7E8 06 41 00 00 10 00 00\\r>",
            b"7E8 04 41 0C 1A F8\\r>",
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
        b"ELM327 v1.5\\r>",
        b"OK\\r>", b"OK\\r>", b"OK\\r>", b"OK\\r>",
        b"OK\\r>", b"OK\\r>",
        b"7E8 06 41 00 00 10 00 00\\r>",
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
