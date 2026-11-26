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


def test_elm327_obd_adapter_reads_stored_pending_and_permanent_dtcs(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 05 43 01 33 00 00\r>",
        b"7E8 03 47 01 33\r>",
        b"7E8 03 4A 01 33\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        codes = adapter.read_dtcs()
        assert [(item["code"], item["status"]) for item in codes] == [
            ("P0133", "Stored"),
            ("P0133", "Pending"),
            ("P0133", "Permanent"),
        ]
        assert [item["arbitration_id"] for item in codes] == [0x7E8] * 3
        assert fake.commands[-3:] == ["03", "07", "0A"]
    finally:
        adapter.close()


def test_elm327_obd_adapter_reassembles_multiframe_dtc_response(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 10 09 43 01 33 01 34\r7E8 21 01 35 01 36 00 00 00\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        codes = adapter.read_dtcs(services=(0x03,))
        assert [item["code"] for item in codes] == [
            "P0133", "P0134", "P0135", "P0136"
        ]
    finally:
        adapter.close()


def test_elm327_obd_adapter_rejects_unsupported_dtc_service(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial()
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        with pytest.raises(ValueError, match="Unsupported DTC service"):
            adapter.read_dtcs(services=(0x04,))
        assert "04" not in fake.commands
    finally:
        adapter.close()



def test_elm327_obd_adapter_reads_pid_01_readiness(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 06 41 01 81 00 0F 08\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        results = adapter.read_readiness()
        assert len(results) == 1
        result = results[0]
        assert result["mil_on"] is True
        assert result["dtc_count"] == 1
        assert result["ignition_type"] == "spark"
        assert result["arbitration_id"] == 0x7E8
        assert result["channel"] == "COM9"
        assert fake.commands[-1] == "0101"
        monitors = {item["name"]: item for item in result["monitors"]}
        assert monitors["misfire"]["complete"] is True
        assert monitors["catalyst"]["complete"] is False
    finally:
        adapter.close()


def test_elm327_obd_adapter_readiness_requires_open_connection():
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    with pytest.raises(RuntimeError, match="not open"):
        adapter.read_readiness()



def test_elm327_obd_adapter_reads_mode02_freeze_frame_pid(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 05 42 0C 00 1A F8\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        results = adapter.read_freeze_frame([0x0C])
        assert len(results) == 1
        assert results[0]["pid"] == "0C"
        assert results[0]["frame_number"] == 0
        assert results[0]["measurements"][0]["value"] == 1726.0
        assert fake.commands[-1] == "020C00"
    finally:
        adapter.close()


def test_elm327_obd_adapter_freeze_frame_rejects_unknown_pid(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial()
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        with pytest.raises(ValueError, match="Unsupported Mode 02 PID"):
            adapter.read_freeze_frame([0xFE])
        assert not any(command.startswith("02") for command in fake.commands)
    finally:
        adapter.close()


def test_elm327_obd_adapter_freeze_frame_requires_open_connection():
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    with pytest.raises(RuntimeError, match="not open"):
        adapter.read_freeze_frame([0x0C])



def test_elm327_obd_adapter_reads_mode09_vehicle_information(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 07 49 06 01 01 02 03 04\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        results = adapter.read_vehicle_info(pids=(0x06,))
        assert len(results) == 1
        assert results[0]["name"] == "Calibration verification number"
        assert results[0]["items"] == [{"type": "cvn", "value": "01020304"}]
        assert results[0]["arbitration_id"] == 0x7E8
        assert fake.commands[-1] == "0906"
    finally:
        adapter.close()


def test_elm327_obd_adapter_reassembles_mode09_vin_response(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 10 14 49 02 01 31 47 4E\r"
        b"7E8 21 45 4B 31 33 5A 35 34\r"
        b"7E8 22 52 31 32 33 34 35 36\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        results = adapter.read_vehicle_info(pids=(0x02,))
        assert results[0]["items"] == [
            {"type": "vin", "value": "1GNEK13Z54R123456"}
        ]
    finally:
        adapter.close()


def test_elm327_obd_adapter_rejects_unknown_mode09_pid_without_request(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial()
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        with pytest.raises(ValueError, match="Unsupported Mode 09 PID"):
            adapter.read_vehicle_info(pids=(0x03,))
        assert "0903" not in fake.commands
    finally:
        adapter.close()


def test_elm327_obd_adapter_reads_mode06_supported_monitor_results(monkeypatch):
    import freerov3r.hardware.elm327_obd_adapter as module

    fake = FakeSerial(responses=[
        b"ELM327 v1.5\r>",
        b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",
        b"OK\r>", b"OK\r>",
        b"7E8 06 41 00 00 10 00 00\r>",
        b"7E8 06 46 00 80 00 00 00\r>",
        b"7E8 0A 46 01 80 24 00 64 00 00 00 C8\r>",
    ])
    monkeypatch.setattr(module.serial, "Serial", lambda *a, **k: fake)
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    adapter.open()
    try:
        result = adapter.read_monitor_tests()
        assert result["supported_monitor_ids"] == [0x01]
        assert result["responses"][0]["monitor_id"] == 0x01
        assert result["responses"][0]["results"][0]["value_raw"] == 100
        assert result["responses"][0]["results"][0]["status"] == "within_limits"
        assert fake.commands[-2:] == ["0600", "0601"]
    finally:
        adapter.close()


def test_elm327_obd_adapter_monitor_tests_requires_open_connection():
    adapter = Elm327ObdAdapter("COM9", pids=[0x0C])
    with pytest.raises(RuntimeError, match="not open"):
        adapter.read_monitor_tests()
