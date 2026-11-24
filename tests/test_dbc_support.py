from pathlib import Path

import pytest

from freerov3r.dbc_support import DBCLibrary, DBCUnavailableError


class FakeSignal:
    def __init__(self, name):
        self.name = name


class FakeMessage:
    frame_id = 0x123
    is_extended_frame = False
    name = "EngineData"
    length = 2
    signals = [FakeSignal("EngineSpeed"), FakeSignal("CoolantTemp")]

    def decode(self, payload, **kwargs):
        assert len(payload) == 2
        return {"EngineSpeed": 1500.0, "CoolantTemp": 88.5}

    def decode(self, payload, **kwargs):
        assert len(payload) == 2
        return {"EngineSpeed": 1500.0, "CoolantTemp": 88.5}


class FakeDatabase:
    messages = [FakeMessage()]

    def decode_message(self, frame_id, payload, **kwargs):
        assert frame_id == 0x123
        assert len(payload) == 2
        return {"EngineSpeed": 1500.0, "CoolantTemp": 88.5}


class FakeCantoolsDatabase:
    @staticmethod
    def load_file(path, strict=True):
        assert strict is True
        return FakeDatabase()


class FakeCantools:
    database = FakeCantoolsDatabase()


def test_dbc_library_imports_validates_and_copies_file(tmp_path, monkeypatch):
    source = tmp_path / "sample.dbc"
    source.write_text('VERSION "test"\n', encoding="utf-8")
    library = DBCLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "_cantools", lambda: FakeCantools)
    destination = library.import_file(source)
    assert destination.parent == tmp_path / "library"
    assert destination.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert library.message_count == 1
    assert library.signal_count == 2


def test_dbc_library_decodes_only_matching_id_format_and_length(tmp_path, monkeypatch):
    source = tmp_path / "sample.dbc"
    source.write_text("test", encoding="utf-8")
    library = DBCLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "_cantools", lambda: FakeCantools)
    library.load_file(source)
    decoded = library.decode(0x123, bytes.fromhex("0102"), extended=False)
    assert decoded.message_name == "EngineData"
    assert decoded.decoded["EngineSpeed"] == 1500.0
    assert library.decode(0x123, bytes.fromhex("0102"), extended=True) is None
    assert library.decode(0x124, bytes.fromhex("0102")) is None
    assert library.decode(0x123, bytes.fromhex("01")) is None


def test_dbc_coverage_reports_numeric_signal_statistics(tmp_path, monkeypatch):
    source = tmp_path / "sample.dbc"
    source.write_text("test", encoding="utf-8")
    library = DBCLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "_cantools", lambda: FakeCantools)
    library.load_file(source)
    coverage = library.decode_coverage([
        {"arbitration_id": 0x123, "extended": False, "data": "0102"},
        {"arbitration_id": 0x123, "extended": False, "data": "0304"},
        {"arbitration_id": 0x124, "extended": False, "data": "0102"},
        {"arbitration_id": 0x123, "extended": False, "data": "not-hex"},
    ])
    assert coverage["matched_frames"] == 2
    assert coverage["unmatched_frames"] == 2
    assert coverage["signals"]["EngineSpeed"]["mean"] == 1500.0
    assert coverage["signals"]["CoolantTemp"]["max"] == 88.5


def test_dbc_library_rejects_non_dbc_paths(tmp_path):
    library = DBCLibrary(tmp_path / "library")
    with pytest.raises(ValueError, match=r"\.dbc"):
        library.load_file(tmp_path / "not-a-dbc.txt")


def test_dbc_dependency_error_is_actionable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "cantools":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(DBCUnavailableError, match="protocols"):
        DBCLibrary._cantools()


def test_real_cantools_dbc_decode_when_optional_dependency_is_installed(tmp_path):
    pytest.importorskip("cantools")
    source = tmp_path / "minimal.dbc"
    source.write_text(
        'VERSION "FreeRov3r test"\n'
        'NS_ :\n'
        'BS_ :\n'
        'BU_: ECU\n'
        'BO_ 291 EngineData: 3 ECU\n'
        ' SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383.75] "rpm" ECU\n',
        encoding="utf-8",
    )
    library = DBCLibrary(tmp_path / "library")
    library.import_file(source)
    result = library.decode(0x123, bytes.fromhex("7017"), extended=False)
    assert result is not None
    assert result.message_name == "EngineData"
    assert result.decoded["EngineSpeed"] == 1500.0



def test_real_cantools_compares_signal_layout_and_scaling(tmp_path):
    pytest.importorskip("cantools")
    left = tmp_path / "left.dbc"
    right = tmp_path / "right.dbc"
    header = (
        'VERSION "test"\nNS_ :\nBS_ :\nBU_: ECU\n'
        'BO_ 291 EngineData: 2 ECU\n'
    )
    left.write_text(
        header + ' SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383.75] "rpm" ECU\n',
        encoding="utf-8",
    )
    right.write_text(
        header + ' SG_ EngineSpeed : 0|16@1+ (0.5,0) [0|32767.5] "rpm" ECU\n'
        ' SG_ CoolantTemp : 16|8@1+ (1,-40) [-40|215] "degC" ECU\n',
        encoding="utf-8",
    )
    report = DBCLibrary.compare_files(left, right)
    assert report["shared_message_count"] == 1
    assert report["message_differences"]
    changes = report["message_differences"][0]["signal_differences"]
    assert any(item["kind"] == "signal_changed" for item in changes)
    assert any(item["kind"] == "signal_added" for item in changes)
    assert report["identical_shared_definitions"] is False



def test_dbc_import_persists_last_selection_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(DBCLibrary, "_cantools", staticmethod(lambda: FakeCantools))
    source = tmp_path / "external.dbc"
    source.write_text("test", encoding="utf-8")
    library_dir = tmp_path / "library"
    first = DBCLibrary(library_dir)
    imported = first.import_file(source)
    assert first.metadata["verification_status"] == "unverified"
    assert first.metadata["source_file"] == "external.dbc"
    assert len(first.metadata["sha256"]) == 64

    restored = DBCLibrary(library_dir)
    assert restored.path == imported
    assert restored.message_count == 1
    assert restored.metadata["sha256"] == first.metadata["sha256"]


def test_dbc_comparison_rejects_non_dbc_paths(tmp_path):
    left = tmp_path / "left.txt"
    right = tmp_path / "right.dbc"
    left.write_text("x", encoding="utf-8")
    right.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.dbc"):
        DBCLibrary.compare_files(left, right)
