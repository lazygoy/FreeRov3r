from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from freerov3r.research_tab import ResearchTab


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _frame():
    return SimpleNamespace(
        timestamp=1.0,
        arbitration_id=0x123,
        data=bytes.fromhex("01 02 03"),
        is_extended_id=False,
        channel="HS-CAN",
    )


def _close(tab):
    tab.refresh_timer.stop()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
    _app().processEvents()


def test_research_live_preview_is_disabled_until_workspace_is_selected():
    _app()
    tab = ResearchTab()
    tab.refresh_timer.stop()
    try:
        assert tab.live_enabled is False
        tab.observe_frame(_frame())
        assert tab._pending_preview == []
        assert tab.live_preview == []

        tab._set_live_enabled(True)
        tab.observe_frame(_frame())
        assert len(tab._pending_preview) == 1
    finally:
        _close(tab)


def test_research_recording_keeps_capturing_when_preview_is_disabled():
    _app()
    tab = ResearchTab()
    tab.refresh_timer.stop()
    try:
        tab.recording = True
        tab.observe_frame(_frame())
        assert len(tab._pending_records) == 1
        assert tab._pending_preview == []
    finally:
        _close(tab)


def test_research_live_display_and_summary_windows_are_bounded():
    assert ResearchTab.MAX_DISPLAY_ROWS == 75
    assert ResearchTab.MAX_LIVE_PREVIEW_FRAMES == 2000
    assert ResearchTab.SUMMARY_FRAME_WINDOW == 500
    assert ResearchTab.TIMESTAMP_HEALTH_WINDOW == 500



def test_live_summary_skips_expensive_dbc_decode():
    _app()
    tab = ResearchTab()
    tab.refresh_timer.stop()

    class SlowDlc:
        database = object()
        path = type("Path", (), {"name": "test.dbc"})()

        def decode_coverage(self, _records):
            raise AssertionError("live summary must not decode DBC signals")

    try:
        tab.dbc_library = SlowDlc()
        tab.live_preview = [
            {
                "timestamp": 1.0,
                "arbitration_id": 0x123,
                "extended": False,
                "data": "010203",
            }
        ]
        tab._update_summary()
        assert "Live DBC decoding paused" in tab.summary.toPlainText()
    finally:
        _close(tab)


def test_recording_summary_skips_expensive_dbc_decode():
    _app()
    tab = ResearchTab()
    tab.refresh_timer.stop()

    class SlowDlc:
        database = object()
        path = type("Path", (), {"name": "test.dbc"})()

        def decode_coverage(self, _records):
            raise AssertionError("recording summary must not decode DBC signals")

    try:
        tab.dbc_library = SlowDlc()
        tab.frames = [
            {
                "timestamp": 1.0,
                "arbitration_id": 0x123,
                "extended": False,
                "data": "010203",
            }
        ]
        tab.recording = True
        tab._update_summary()
        assert "Live DBC decoding paused" in tab.summary.toPlainText()
    finally:
        _close(tab)
