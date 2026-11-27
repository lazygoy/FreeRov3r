"""Persistent, applicability-aware knowledge catalog shared by Research and Diagnostics.

Research observations remain evidence records. Only explicitly reviewed and
implemented items marked supported are exposed as production capabilities.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA_VERSION = 1
_STATUSES = {"observed", "candidate", "documented", "verified", "supported"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _copy_json(value):
    """Return a detached JSON-compatible copy and reject unserializable values."""
    return json.loads(json.dumps(value, sort_keys=True))


def _validate_applicability(value):
    if not isinstance(value, dict):
        raise ValueError("applicability must be a dictionary")
    result = _copy_json(value)
    if "platform_independent" in result and not isinstance(result["platform_independent"], bool):
        raise ValueError("applicability.platform_independent must be a boolean")
    profile_ids = result.get("profile_ids", [])
    if not isinstance(profile_ids, list) or any(
        not isinstance(item, str) or not item.strip() for item in profile_ids
    ):
        raise ValueError("applicability.profile_ids must be a list of non-empty strings")
    if not profile_ids and not result.get("platform_independent", False):
        raise ValueError("applicability requires profile_ids or platform_independent=True")
    for key in ("model_year_start", "model_year_end"):
        year = result.get(key)
        if year is not None and (
            isinstance(year, bool) or not isinstance(year, int) or not 1886 <= year <= 2200
        ):
            raise ValueError(f"applicability.{key} must be a valid model year")
    start = result.get("model_year_start")
    end = result.get("model_year_end")
    if start is not None and end is not None and start > end:
        raise ValueError("applicability model-year range is reversed")
    engine_ids = result.get("engine_ids", [])
    if not isinstance(engine_ids, list) or any(
        not isinstance(item, str) or not item.strip() for item in engine_ids
    ):
        raise ValueError("applicability.engine_ids must be a list of non-empty strings")
    return result


def _matches(record, profile_id, model_year=None, engine_id=None):
    applicability = record.get("applicability") or {}
    if not applicability.get("platform_independent") and profile_id not in applicability.get("profile_ids", []):
        return False
    start = applicability.get("model_year_start")
    end = applicability.get("model_year_end")
    if start is not None or end is not None:
        if model_year is None:
            return False
        if start is not None and model_year < start:
            return False
        if end is not None and model_year > end:
            return False
    engines = applicability.get("engine_ids", [])
    if engines and engine_id not in engines:
        return False
    return True


class VehicleKnowledgeStore:
    """Atomic JSON catalog for reusable and manufacturer-specific knowledge."""

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _record_id(artifact_type, artifact_key, applicability):
        identity = {
            "artifact_type": artifact_type,
            "artifact_key": artifact_key,
            "applicability": applicability,
        }
        return hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:20]

    def _empty(self):
        return {"schema_version": _SCHEMA_VERSION, "records": []}

    def _read(self):
        if not self.path.exists():
            return self._empty()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read vehicle knowledge catalog: {exc}") from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(document.get("records"), list)
        ):
            raise ValueError("Unsupported or malformed vehicle knowledge catalog")
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

    def add_observation(
        self, artifact_type, artifact_key, data, *, applicability,
        source_references=(), source_capture_ids=(), notes="",
    ):
        """Record a research finding without treating it as production support."""
        artifact_type = str(artifact_type).strip().lower()
        artifact_key = str(artifact_key).strip()
        if not artifact_type or not artifact_key:
            raise ValueError("artifact_type and artifact_key are required")
        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")
        applicable = _validate_applicability(applicability)
        if isinstance(source_references, (str, bytes)):
            raise ValueError("source_references must be an iterable, not a string")
        if isinstance(source_capture_ids, (str, bytes)):
            raise ValueError("source_capture_ids must be an iterable, not a string")
        references = list(dict.fromkeys(
            str(item).strip() for item in source_references if str(item).strip()
        ))
        capture_ids = list(dict.fromkeys(
            str(item).strip() for item in source_capture_ids if str(item).strip()
        ))
        if not references and not capture_ids:
            raise ValueError("at least one source reference or capture ID is required")
        payload = _copy_json(data)
        record_id = self._record_id(artifact_type, artifact_key, applicable)
        document = self._read()
        record = next(
            (item for item in document["records"] if item.get("record_id") == record_id),
            None,
        )
        now = _now()
        if record is None:
            record = {
                "record_id": record_id,
                "artifact_type": artifact_type,
                "artifact_key": artifact_key,
                "data": payload,
                "applicability": applicable,
                "status": "observed",
                "source_references": [],
                "source_capture_ids": [],
                "notes": "",
                "created_at": now,
                "updated_at": now,
                "history": [{
                    "at": now, "event": "observation_added",
                    "detail": "Research finding recorded; not production-supported",
                }],
                "evidence_grade": "",
                "verification_notes": "",
                "implementation_reference": "",
                "test_reference": "",
            }
            document["records"].append(record)
        else:
            changed_data = any(record["data"].get(key) != value for key, value in payload.items())
            if changed_data:
                previous_status = record["status"]
                record["data"].update(payload)
                record.update({
                    "status": "observed",
                    "evidence_grade": "",
                    "verification_notes": "",
                    "implementation_reference": "",
                    "test_reference": "",
                    "source_reference": "",
                    "vehicle_applicability_note": "",
                })
                record["history"].append({
                    "at": now,
                    "event": "data_changed_review_reset",
                    "detail": {
                        "previous_status": previous_status,
                        "reason": "A knowledge payload changed and requires fresh review",
                    },
                })
        added_refs = [item for item in references if item not in record["source_references"]]
        added_captures = [item for item in capture_ids if item not in record["source_capture_ids"]]
        record["source_references"].extend(added_refs)
        record["source_capture_ids"].extend(added_captures)
        if notes:
            record["notes"] = str(notes).strip()
        if added_refs or added_captures:
            record["history"].append({
                "at": now,
                "event": "evidence_added",
                "detail": {
                    "source_references": added_refs,
                    "source_capture_ids": added_captures,
                },
            })
        record["updated_at"] = now
        self._write(document)
        return deepcopy(record)

    def review(
        self, record_id, status, *, source_reference="", vehicle_applicability="",
        evidence_grade="", verification_notes="", implementation_reference="",
        test_reference="",
    ):
        """Apply an explicit evidence review or production-support decision."""
        status = str(status).strip().lower()
        if status not in _STATUSES:
            raise ValueError("status must be observed, candidate, documented, verified or supported")
        source_reference = str(source_reference).strip()
        vehicle_applicability = str(vehicle_applicability).strip()
        grade = str(evidence_grade).strip().upper()
        verification_notes = str(verification_notes).strip()
        implementation_reference = str(implementation_reference).strip()
        test_reference = str(test_reference).strip()
        if status in {"documented", "verified", "supported"}:
            if not source_reference or not vehicle_applicability:
                raise ValueError(f"{status} requires a source reference and vehicle applicability")
        if status in {"verified", "supported"}:
            if grade != "A" or not verification_notes:
                raise ValueError(f"{status} requires grade A evidence and verification notes")
        elif grade and grade not in {"A", "B", "C", "D"}:
            raise ValueError("evidence_grade must be A, B, C or D")
        if status == "supported":
            if not implementation_reference or not test_reference:
                raise ValueError("supported requires implementation_reference and test_reference")
        document = self._read()
        record = next(
            (item for item in document["records"] if item.get("record_id") == str(record_id)),
            None,
        )
        if record is None:
            raise KeyError(f"Unknown vehicle knowledge record: {record_id}")
        previous = record["status"]
        if status == "supported" and previous != "verified":
            raise ValueError("supported requires the record to be verified first")
        now = _now()
        record.update({
            "status": status,
            "source_reference": source_reference,
            "vehicle_applicability_note": vehicle_applicability,
            "evidence_grade": grade,
            "verification_notes": verification_notes,
            "implementation_reference": implementation_reference,
            "test_reference": test_reference,
            "updated_at": now,
        })
        record["history"].append({
            "at": now, "event": "review_updated",
            "detail": {"from": previous, "to": status},
        })
        self._write(document)
        return deepcopy(record)

    def import_signal_evidence(self, evidence_store, record_id, *, applicability):
        """Import documented/verified research evidence without claiming support.

        The source ledger remains intact. Candidate-only records are deliberately
        rejected so correlation output cannot leak into the production catalog.
        """
        source = evidence_store.get_record(record_id)
        if source is None:
            raise KeyError(f"Unknown signal evidence record: {record_id}")
        source_status = source.get("status")
        if source_status not in {"documented", "verified"}:
            raise ValueError(
                "Only documented or verified signal evidence can enter vehicle knowledge"
            )
        signature = source.get("signature")
        if not isinstance(signature, dict):
            raise ValueError("Signal evidence record has no valid signature")
        source_reference = str(source.get("source_reference") or "").strip()
        vehicle_applicability = str(source.get("vehicle_applicability") or "").strip()
        if not source_reference or not vehicle_applicability:
            raise ValueError("Reviewed signal evidence is missing its source or vehicle applicability")
        imported = self.add_observation(
            "signal_definition",
            str(source.get("record_id") or record_id),
            {
                "signature": signature,
                "evidence_summary": source.get("evidence_summary") or {},
                "research_record_id": str(source.get("record_id") or record_id),
            },
            applicability=applicability,
            source_references=[source_reference],
            source_capture_ids=source.get("source_capture_ids") or [],
            notes="Imported from the permanent Research signal evidence ledger.",
        )
        return self.review(
            imported["record_id"],
            source_status,
            source_reference=source_reference,
            vehicle_applicability=vehicle_applicability,
            evidence_grade=source.get("evidence_grade") or "",
            verification_notes=source.get("verification_notes") or "",
        )

    def import_module_discovery_report(
        self, report, *, applicability, capture_id=None, capture_ids=None,
    ):
        """Persist passive CAN-node observations without inventing ECU identities.

        capture_ids maps capture names in a multi-capture comparison to stable
        capture/session identifiers. A single-capture report uses capture_id.
        The report must explicitly state that no transmission occurred.
        """
        if not isinstance(report, dict):
            raise ValueError("module discovery report must be a dictionary")
        if report.get("method") not in {
            "passive_capture_analysis",
            "independent_passive_capture_comparison",
        }:
            raise ValueError("unsupported module discovery report method")
        if report.get("transmission_performed") is not False:
            raise ValueError("only explicitly passive, receive-only reports can be imported")
        nodes = report.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError("module discovery report nodes must be a list")
        if capture_ids is not None and not isinstance(capture_ids, dict):
            raise ValueError("capture_ids must map capture names to stable identifiers")
        capture_ids = capture_ids or {}
        if report.get("method") == "independent_passive_capture_comparison" and not capture_ids:
            raise ValueError("multi-capture imports require stable capture_ids for every capture name")
        records = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            can_id = node.get("can_id")
            if isinstance(can_id, bool) or not isinstance(can_id, int) or not 0 <= can_id <= 0x1FFFFFFF:
                continue
            extended = node.get("extended")
            if not isinstance(extended, bool):
                continue
            channel = str(node.get("channel") or "unknown").strip() or "unknown"
            frame_format = "EXT" if extended else "STD"
            names = node.get("capture_names") or []
            if not isinstance(names, list):
                names = []
            if report.get("method") == "independent_passive_capture_comparison":
                missing_names = [str(name) for name in names if str(name) not in capture_ids]
                if missing_names:
                    raise ValueError(
                        "missing stable capture identifiers for: " + ", ".join(missing_names)
                    )
                provenance = [
                    str(capture_ids[str(name)]).strip()
                    for name in names if str(capture_ids[str(name)]).strip()
                ]
            else:
                provenance = [str(capture_id).strip()] if capture_id else []
            provenance = list(dict.fromkeys(item for item in provenance if item))
            if not provenance:
                raise ValueError(
                    f"CAN node 0x{can_id:X} has no traceable source capture identifier"
                )
            key = f"{channel}:{frame_format}:{can_id:X}"
            data = {
                "can_id": can_id,
                "extended": extended,
                "channel": channel,
                "frame_count": int(node.get("frame_count") or node.get("observed_frame_count") or 0),
                "role": str(node.get("role") or "observed_can_node"),
                "reported_evidence_level": str(node.get("evidence_level") or "Observed"),
                "uds_pair_count": int(node.get("uds_pair_count") or 0),
                "positive_response_count": int(node.get("positive_response_count") or 0),
                "negative_response_count": int(node.get("negative_response_count") or 0),
                "request_ids": list(node.get("request_ids") or []),
                "services": list(node.get("services") or []),
                "addressing_hints": list(node.get("addressing_hints") or []),
                "capture_names": [str(name) for name in names],
                "interpretation": str(node.get("interpretation") or ""),
                "identity_confirmed": False,
            }
            records.append(self.add_observation(
                "observed_can_node",
                key,
                data,
                applicability=applicability,
                source_capture_ids=provenance,
                notes=(
                    "Imported from passive CAN discovery. CAN ID and probable UDS "
                    "role are observations, not a physical ECU identity."
                ),
            ))
        return records

    def get_record(self, record_id):
        for record in self._read()["records"]:
            if record.get("record_id") == str(record_id):
                return deepcopy(record)
        return None

    def list_records(self, *, status=None, artifact_type=None):
        records = self._read()["records"]
        if status is not None:
            records = [item for item in records if item.get("status") == status]
        if artifact_type is not None:
            records = [item for item in records if item.get("artifact_type") == artifact_type]
        return deepcopy(records)

    def for_vehicle(self, profile_id, *, model_year=None, engine_id=None):
        """Return applicable knowledge at every evidence level for Research."""
        return [
            deepcopy(item) for item in self._read()["records"]
            if _matches(item, profile_id, model_year, engine_id)
        ]

    def diagnostic_catalog(self, profile_id, *, model_year=None, engine_id=None):
        """Return only verified facts and explicitly supported capabilities.

        Candidate and documented research remains available through for_vehicle()
        but is never presented as an executable or supported diagnostic feature.
        """
        applicable = self.for_vehicle(
            profile_id, model_year=model_year, engine_id=engine_id
        )
        return {
            "profile_id": profile_id,
            "verified_knowledge": [
                item for item in applicable if item["status"] == "verified"
            ],
            "supported_capabilities": [
                item for item in applicable if item["status"] == "supported"
            ],
        }
