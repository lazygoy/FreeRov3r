from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from freerov3r.research_tab import ResearchTab


_APP = QApplication.instance() or QApplication([])


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
    _APP.processEvents()


def test_research_live_preview_is_disabled_until_workspace_is_selected():
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
    assert ResearchTab.MAX_DISPLAY_ROWS == 150
    assert ResearchTab.MAX_LIVE_PREVIEW_FRAMES == 2000
    assert ResearchTab.SUMMARY_FRAME_WINDOW == 2000
