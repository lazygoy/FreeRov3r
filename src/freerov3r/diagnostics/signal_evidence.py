"""Persistent, provenance-aware storage for CAN signal research candidates.

The ledger records observations and review history. It does not decode signals,
create DBC definitions, or promote correlations to verified vehicle facts.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA_VERSION = 1
_SIGNATURE_FIELDS = (
    "signal_type", "channel_a", "can_id_a", "format_a", "byte_a", "bit_a",
    "channel_b", "can_id_b", "format_b", "byte_b", "bit_b",
    "match_type", "xor_mask",
)
_ALLOWED_STATUSES = {"observed", "probable", "documented", "verified"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _candidate_signature(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a dictionary")
    missing = [key for key in _SIGNATURE_FIELDS if key not in candidate]
    if missing:
        raise ValueError("candidate is missing signature fields: " + ", ".join(missing))
    signature = {key: candidate[key] for key in _SIGNATURE_FIELDS}
    if signature["signal_type"] not in {"byte", "bit"}:
        raise ValueError("signal_type must be 'byte' or 'bit'")
    for key in ("can_id_a", "can_id_b"):
        value = signature[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0x1FFFFFFF:
            raise ValueError(f"{key} must be a valid CAN identifier")
    for key in ("byte_a", "byte_b"):
        value = signature[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 63:
            raise ValueError(f"{key} must be an integer from 0 to 63")
    for key in ("bit_a", "bit_b"):
        value = signature[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 7
        ):
            raise ValueError(f"{key} must be None or an integer from 0 to 7")
    for key in ("channel_a", "channel_b", "format_a", "format_b", "match_type"):
        if not isinstance(signature[key], str) or not signature[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if signature["signal_type"] == "bit" and (
        signature["bit_a"] is None or signature["bit_b"] is None
    ):
        raise ValueError("bit candidates require bit_a and bit_b")
    return signature


class SignalEvidenceStore:
    """Small JSON-backed evidence ledger for repeatable signal candidates."""

    def __init__(self, path):
        self.path = Path(path)

    def _empty_document(self):
        return {"schema_version": _SCHEMA_VERSION, "records": []}

    def _read(self):
        if not self.path.exists():
            return self._empty_document()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read signal evidence ledger: {exc}") from exc
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("Unsupported or malformed signal evidence ledger schema")
        if not isinstance(document.get("records"), list):
            raise ValueError("Signal evidence ledger records must be a list")
        return document

    def _write(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def _record_id(signature):
        digest = hashlib.sha256(_canonical_json(signature).encode("utf-8")).hexdigest()
        return digest[:20]

    def list_records(self):
        """Return records ordered by creation time without exposing mutable internals."""
        document = self._read()
        return [dict(record) for record in document["records"]]

    def get_record(self, record_id):
        for record in self._read()["records"]:
            if record.get("record_id") == str(record_id):
                return dict(record)
        return None

    def add_candidate(
        self, candidate, *, source_capture_ids=(), vehicle_context=None, notes=""
    ):
        """Add or update a candidate, retaining independent capture provenance."""
        signature = _candidate_signature(candidate)
        capture_ids = []
        for value in source_capture_ids or ():
            capture_id = str(value).strip()
            if capture_id and capture_id not in capture_ids:
                capture_ids.append(capture_id)
        if not capture_ids:
            raise ValueError("at least one source capture ID is required")
        record_id = self._record_id(signature)
        document = self._read()
        record = next(
            (item for item in document["records"] if item.get("record_id") == record_id),
            None,
        )
        now = _utc_now()
        if record is None:
            record = {
                "record_id": record_id,
                "signature": signature,
                "status": "probable",
                "created_at": now,
                "updated_at": now,
                "source_capture_ids": [],
                "vehicle_context": {},
                "notes": "",
                "evidence_summary": {},
                "history": [{
                    "at": now, "event": "candidate_added",
                    "detail": "Repeatable candidate imported from analysis",
                }],
                "source_reference": "",
                "evidence_grade": "",
                "verification_notes": "",
            }
            document["records"].append(record)
        added = [item for item in capture_ids if item not in record["source_capture_ids"]]
        record["source_capture_ids"].extend(added)
        if vehicle_context:
            if not isinstance(vehicle_context, dict):
                raise ValueError("vehicle_context must be a dictionary")
            record["vehicle_context"].update(vehicle_context)
        if notes:
            record["notes"] = str(notes).strip()
        summary_fields = (
            "capture_count", "capture_agreement", "total_transitions",
            "median_transition_agreement", "median_transition_coverage",
            "median_lag_seconds", "lag_spread_seconds", "evidence_level",
        )
        record["evidence_summary"] = {
            key: candidate[key] for key in summary_fields if key in candidate
        }
        if added:
            record["history"].append({
                "at": now, "event": "capture_evidence_added",
                "detail": {"capture_ids": added},
            })
        record["updated_at"] = now
        self._write(document)
        return dict(record)

    def update_review(
        self, record_id, status, *, source_reference="", vehicle_applicability="",
        evidence_grade="", verification_notes="",
    ):
        """Record a review decision; verified requires complete grade-A evidence."""
        status = str(status).strip().lower()
        if status not in _ALLOWED_STATUSES:
            raise ValueError("status must be observed, probable, documented or verified")
        source_reference = str(source_reference).strip()
        vehicle_applicability = str(vehicle_applicability).strip()
        evidence_grade = str(evidence_grade).strip().upper()
        verification_notes = str(verification_notes).strip()
        if status in {"documented", "verified"}:
            missing = [
                label for label, value in (
                    ("source reference", source_reference),
                    ("vehicle applicability", vehicle_applicability),
                ) if not value
            ]
            if missing:
                raise ValueError(f"{status} status requires " + ", ".join(missing))
        if status == "verified":
            if evidence_grade != "A" or not verification_notes:
                raise ValueError(
                    "verified status requires grade A evidence and verification notes"
                )
        elif evidence_grade and evidence_grade not in {"A", "B", "C", "D"}:
            raise ValueError("evidence_grade must be A, B, C or D")
        document = self._read()
        record = next(
            (item for item in document["records"] if item.get("record_id") == str(record_id)),
            None,
        )
        if record is None:
            raise KeyError(f"Unknown signal evidence record: {record_id}")
        previous = record["status"]
        now = _utc_now()
        record.update({
            "status": status,
            "source_reference": source_reference,
            "vehicle_applicability": vehicle_applicability,
            "evidence_grade": evidence_grade,
            "verification_notes": verification_notes,
            "updated_at": now,
        })
        record["history"].append({
            "at": now, "event": "review_updated",
            "detail": {"from": previous, "to": status},
        })
        self._write(document)
        return dict(record)
