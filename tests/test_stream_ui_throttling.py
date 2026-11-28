from types import SimpleNamespace

from freerov3r import frame_processing
from freerov3r.hardware.dual_channel_simulator import DualChannelSimulator
from freerov3r.hardware.receiver import Receiver
from freerov3r.sensor_graph_tab import SensorGraphTab


class _TextSink:
    def __init__(self):
        self.calls = []

    def appendPlainText(self, value):
        self.calls.append(value)

    def setText(self, value):
        self.calls.append(value)


def test_sample_activity_is_recorded_without_repainting_sensor_list():
    graph = SimpleNamespace(last_sample_time={})

    def unexpected_refresh():
        raise AssertionError("sample arrival must not trigger a full widget refresh")

    graph._update_activity_indicators = unexpected_refresh
    SensorGraphTab.mark_sample(graph, "obd_05")
    assert "obd_05" in graph.last_sample_time


def test_frame_batch_coalesces_sensor_and_obd_widget_updates(monkeypatch):
    window = SimpleNamespace(
        frame_counter=0,
        frame_count_label=_TextSink(),
        log=_TextSink(),
        sensor_log=_TextSink(),
        obd_tab=SimpleNamespace(update_calls=[]),
        graph_tab=SimpleNamespace(refresh_calls=0),
    )
    window.obd_tab.update_value = lambda pid, value: window.obd_tab.update_calls.append((pid, value))
    window.graph_tab.refresh_sensor_list = lambda: setattr(
        window.graph_tab, "refresh_calls", window.graph_tab.refresh_calls + 1
    )

    def fake_process_frame(_window, frame, update_display, display_updates):
        assert update_display is False
        _window.frame_counter += 1
        display_updates["sensor_lines"].append(f"sensor-{frame}")
        display_updates["obd_values"][0x05] = f"value-{frame}"
        display_updates["refresh_sensor_list"] = True
        return f"frame-{frame}"

    monkeypatch.setattr(frame_processing, "process_frame", fake_process_frame)
    frame_processing.process_frames(window, [1, 2, 3])

    assert window.log.calls == ["frame-1\nframe-2\nframe-3"]
    assert window.sensor_log.calls == ["sensor-1\nsensor-2\nsensor-3"]
    assert window.obd_tab.update_calls == [(0x05, "value-3")]
    assert window.graph_tab.refresh_calls == 1
    assert window.frame_count_label.calls == ["Frames: 3"]


def test_simulators_use_ui_friendly_default_rate():
    assert DualChannelSimulator().speed == 0.25
    assert Receiver.FRAME_BATCH_SIZE == 256
    assert Receiver.FRAME_BATCH_INTERVAL == 0.10


def test_hidden_research_preview_buffers_frames_without_rebuilding_table():
    from freerov3r.research_tab import ResearchTab

    preview = [{"arbitration_id": 0x100, "data": "010203"}]
    tab = SimpleNamespace(
        _pending_records=[],
        _pending_preview=preview.copy(),
        live_preview=[],
        frames=[],
        MAX_CAPTURE_FRAMES=100_000,
        MAX_DISPLAY_ROWS=500,
        MAX_LIVE_PREVIEW_FRAMES=2000,
        dropped_recorded_frames=0,
        _display_refresh_pending=False,
        _last_display_refresh=0.0,
        isVisible=lambda: False,
        refresh_table=lambda: (_ for _ in ()).throw(
            AssertionError("hidden research table must not be rebuilt")
        ),
    )

    ResearchTab._flush_pending_frames(tab)

    assert tab.live_preview == preview
    assert tab._pending_preview == []



def test_obd_value_update_does_not_sweep_all_activity_indicators(monkeypatch):
    from types import SimpleNamespace

    from freerov3r import obd_tab

    class _ValueItem:
        value = None

        def setText(self, value):
            self.value = value

    item = _ValueItem()
    tab = SimpleNamespace(
        pid_rows={0x05: 2},
        table=SimpleNamespace(item=lambda _row, _column: item),
        last_sample_time={},
    )
    monkeypatch.setattr(obd_tab.time, "monotonic", lambda: 123.0)

    obd_tab.OBDTab.update_value(tab, 0x05, "91.0 C")

    assert item.value == "91.0 C"
    assert tab.last_sample_time == {0x05: 123.0}


def test_hidden_sensor_activity_refresh_skips_widget_sweeps():
    from types import SimpleNamespace

    from freerov3r.obd_tab import OBDTab
    from freerov3r.sensor_graph_tab import SensorGraphTab

    hidden_obd = SimpleNamespace(isVisible=lambda: False)
    hidden_graph = SimpleNamespace(isVisible=lambda: False)

    OBDTab._update_activity_indicators(hidden_obd)
    SensorGraphTab._update_activity_indicators(hidden_graph)
