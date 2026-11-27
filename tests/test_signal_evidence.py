import json

import pytest

from freerov3r.diagnostics.signal_evidence import SignalEvidenceStore


def _candidate(**overrides):
    item = {
        "signal_type": "byte",
        "channel_a": "HS-CAN",
        "can_id_a": 0x120,
        "format_a": "STD",
        "byte_a": 0,
        "bit_a": None,
        "channel_b": "MS-CAN",
        "can_id_b": 0x321,
        "format_b": "STD",
        "byte_b": 0,
        "bit_b": None,
        "match_type": "exact",
        "xor_mask": 0,
        "capture_count": 2,
        "capture_agreement": 1.0,
        "total_transitions": 12,
        "median_transition_agreement": 1.0,
        "median_transition_coverage": 1.0,
        "median_lag_seconds": 0.02,
        "lag_spread_seconds": 0.001,
        "evidence_level": "repeatable_candidate",
    }
    item.update(overrides)
    return item


def test_add_candidate_persists_signature_and_provenance(tmp_path):
    path = tmp_path / "research" / "signal-evidence.json"
    store = SignalEvidenceStore(path)

    record = store.add_candidate(
        _candidate(),
        source_capture_ids=["capture-a", "capture-b"],
        vehicle_context={"platform": "L319", "engine": "5.0L NA"},
    )

    assert path.is_file()
    assert record["status"] == "probable"
    assert record["source_capture_ids"] == ["capture-a", "capture-b"]
    assert record["vehicle_context"]["platform"] == "L319"
    assert record["evidence_summary"]["capture_agreement"] == 1.0
    assert store.get_record(record["record_id"])["signature"]["can_id_a"] == 0x120


def test_same_signature_merges_capture_provenance_without_duplicate_record(tmp_path):
    store = SignalEvidenceStore(tmp_path / "ledger.json")
    first = store.add_candidate(_candidate(), source_capture_ids=["one"])
    second = store.add_candidate(
        _candidate(total_transitions=30),
        source_capture_ids=["one", "two"],
    )

    records = store.list_records()
    assert len(records) == 1
    assert first["record_id"] == second["record_id"]
    assert second["source_capture_ids"] == ["one", "two"]
    assert second["evidence_summary"]["total_transitions"] == 30


def test_verified_review_requires_grade_a_and_complete_evidence(tmp_path):
    store = SignalEvidenceStore(tmp_path / "ledger.json")
    record = store.add_candidate(_candidate(), source_capture_ids=["capture"])
    record_id = record["record_id"]

    with pytest.raises(ValueError, match="grade A"):
        store.update_review(
            record_id, "verified",
            source_reference="service document",
            vehicle_applicability="2010 LR4 5.0L",
            evidence_grade="B",
            verification_notes="Checked on vehicle",
        )
    with pytest.raises(ValueError, match="source reference"):
        store.update_review(record_id, "documented")

    verified = store.update_review(
        record_id, "verified",
        source_reference="controlled vehicle test record #17",
        vehicle_applicability="2010 LR4 5.0L, VIN-specific fitment checked",
        evidence_grade="A",
        verification_notes="Repeated on vehicle and cross-checked against known-value behavior",
    )
    assert verified["status"] == "verified"
    assert verified["history"][-1]["event"] == "review_updated"


def test_rejects_malformed_candidate_and_missing_capture_provenance(tmp_path):
    store = SignalEvidenceStore(tmp_path / "ledger.json")
    with pytest.raises(ValueError, match="signature fields"):
        store.add_candidate({"can_id_a": 0x120}, source_capture_ids=["capture"])
    with pytest.raises(ValueError, match="capture ID"):
        store.add_candidate(_candidate(), source_capture_ids=[])


def test_rejects_corrupt_or_unsupported_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"schema_version": 99, "records": []}), encoding="utf-8")
    store = SignalEvidenceStore(path)
    with pytest.raises(ValueError, match="Unsupported"):
        store.list_records()


def test_bit_candidate_requires_bit_positions(tmp_path):
    store = SignalEvidenceStore(tmp_path / "ledger.json")
    candidate = _candidate(signal_type="bit", bit_a=None, bit_b=2)
    with pytest.raises(ValueError, match="require bit_a"):
        store.add_candidate(candidate, source_capture_ids=["capture"])



def test_byte_candidate_does_not_require_bit_offset_fields(tmp_path):
    store = SignalEvidenceStore(tmp_path / "ledger.json")
    candidate = _candidate()
    candidate.pop("bit_a")
    candidate.pop("bit_b")
    record = store.add_candidate(candidate, source_capture_ids=["capture-a", "capture-b"])
    assert record["signature"]["bit_a"] is None
    assert record["signature"]["bit_b"] is None
