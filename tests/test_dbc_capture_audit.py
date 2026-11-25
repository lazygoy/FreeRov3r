from pathlib import Path

from freerov3r.diagnostics.dbc_capture_audit import audit_dbc_capture
from freerov3r.dbc_support import DBCLibrary


class FakeSignal:
    name = "EngineSpeed"
    unit = "rpm"
    minimum = 0
    maximum = 6000


class FakeMessage:
    frame_id = 0x123
    is_extended_frame = False
    name = "EngineData"
    length = 2
    signals = [FakeSignal()]

    def decode(self, payload, **kwargs):
        return {"EngineSpeed": float(payload[0] * 100)}


class FakeDatabase:
    messages = [FakeMessage()]


class FakeCantoolsDatabase:
    @staticmethod
    def load_file(path, strict=True):
        return FakeDatabase()


class FakeCantools:
    database = FakeCantoolsDatabase()


def _library(tmp_path, monkeypatch):
    source = tmp_path / "sample.dbc"
    source.write_text("test", encoding="utf-8")
    monkeypatch.setattr(DBCLibrary, "_cantools", staticmethod(lambda: FakeCantools))
    library = DBCLibrary(tmp_path / "library")
    library.load_file(source)
    return library


def test_audit_classifies_matches_unknown_ids_lengths_and_invalid_records(tmp_path, monkeypatch):
    library = _library(tmp_path, monkeypatch)
    report = audit_dbc_capture(library, [
        {"arbitration_id": 0x123, "extended": False, "channel": "HS-CAN", "data": "0102"},
        {"arbitration_id": 0x124, "extended": False, "channel": "HS-CAN", "data": "0102"},
        {"arbitration_id": 0x123, "extended": False, "channel": "HS-CAN", "data": "01"},
        {"arbitration_id": 0x123, "extended": False, "data": "not-hex"},
        [],
    ])
    assert report["matched_frames"] == 1
    assert report["unmatched_frames"] == 2
    assert report["invalid_records"] == 2
    assert report["coverage_percent"] == 100 / 3
    assert report["unmatched_reasons"] == {
        "no_matching_id_and_format": 1,
        "payload_length_mismatch": 1,
        "invalid_record": 2,
    }
    assert report["message_frame_counts"] == {"0x123 STD EngineData": 1}
    assert report["signal_coverage"]["signals_with_numeric_samples"] == 1


def test_audit_separates_standard_and_extended_definitions(tmp_path, monkeypatch):
    library = _library(tmp_path, monkeypatch)
    report = audit_dbc_capture(library, [
        {"arbitration_id": 0x123, "extended": True, "data": "0102"},
    ])
    assert report["matched_frames"] == 0
    assert report["unmatched_signatures"][0]["reason"] == "no_matching_id_and_format"


def test_audit_without_loaded_dbc_is_explicit(tmp_path):
    library = DBCLibrary(tmp_path / "library")
    report = audit_dbc_capture(library, [{"arbitration_id": 0x123, "data": "0102"}])
    assert report["dbc_loaded"] is False
    assert report["unmatched_reasons"] == {"dbc_not_loaded": 1}


def test_audit_empty_capture_has_no_division_error(tmp_path, monkeypatch):
    library = _library(tmp_path, monkeypatch)
    report = audit_dbc_capture(library, [])
    assert report["coverage_percent"] is None
    assert report["matched_frames"] == 0
    assert report["unmatched_frames"] == 0
