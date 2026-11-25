from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from freerov3r.tuning_tab import TuningTab


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_tuning_tab_archive_controls_create_and_verify_both_copies(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(TuningTab, "SETTINGS_PATH", tmp_path / "settings" / "archive.json")
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    source = tmp_path / "stock_read.bin"
    source.write_bytes(b"original ECU calibration image")
    internal = tmp_path / "internal"
    removable = tmp_path / "usb"

    tab = TuningTab(vin_provider=lambda: "TESTVIN12345678901")
    tab.source_file = str(source)
    tab.source_value.setText(str(source))
    tab.internal_root = str(internal)
    tab.internal_value.setText(str(internal))
    tab.removable_root = str(removable)
    tab.removable_value.setText(str(removable))
    tab.hardware_input.setText("HW-TEST")
    tab.software_input.setText("SW-TEST")
    tab.calibration_input.setText("CAL-TEST")

    tab.create_archive()

    archived_internal = internal / "FreeRov3r/recovery/original/stock_read.bin"
    archived_removable = removable / "FreeRov3r/recovery/original/stock_read.bin"
    assert archived_internal.read_bytes() == source.read_bytes()
    assert archived_removable.read_bytes() == source.read_bytes()
    assert "VERIFIED" in tab.archive_status.text()

    tab.verify_archive()
    assert "VERIFIED" in tab.archive_status.text()
    tab.close()


def test_archive_root_selection_persists_local_settings(tmp_path, qapp, monkeypatch):
    settings_path = tmp_path / "settings" / "archive.json"
    monkeypatch.setattr(TuningTab, "SETTINGS_PATH", settings_path)
    tab = TuningTab()
    monkeypatch.setattr(tab, "_select_root", lambda title: str(tmp_path / "selected"))
    tab.select_internal_root()

    assert tab.internal_root == str(tmp_path / "selected")
    assert settings_path.is_file()
    assert settings_path.read_text(encoding="utf-8").find("internal_root") >= 0
    tab.close()
