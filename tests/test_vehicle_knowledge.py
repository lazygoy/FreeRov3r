import json

import pytest

from freerov3r.core.vehicle.knowledge import VehicleKnowledgeStore
from freerov3r.diagnostics.signal_evidence import SignalEvidenceStore


def _store(tmp_path):
    return VehicleKnowledgeStore(tmp_path / "knowledge" / "catalog.json")


def _applicability(**overrides):
    value = {
        "profile_ids": ["land_rover_l319_lr4"],
        "model_year_start": 2010,
        "model_year_end": 2016,
        "engine_ids": ["508PN"],
    }
    value.update(overrides)
    return value


def _record(store):
    return store.add_observation(
        "signal_definition",
        "engine_coolant_temperature",
        {"can_id": 0x123, "byte_offset": 2, "unit": "degC"},
        applicability=_applicability(),
        source_capture_ids=["capture-001"],
    )


def test_observation_is_research_only_until_explicitly_supported(tmp_path):
    store = _store(tmp_path)
    record = _record(store)
    assert record["status"] == "observed"

    catalog = store.diagnostic_catalog(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )
    assert catalog["verified_knowledge"] == []
    assert catalog["supported_capabilities"] == []
    assert len(store.for_vehicle(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )) == 1


def test_supported_requires_verified_evidence_and_implementation_tests(tmp_path):
    store = _store(tmp_path)
    record = _record(store)
    with pytest.raises(ValueError, match="verified first"):
        store.review(
            record["record_id"], "supported",
            source_reference="capture review",
            vehicle_applicability="2010-2016 LR4 5.0L",
            evidence_grade="A",
            verification_notes="Repeated on vehicle",
            implementation_reference="src/freerov3r/signals/l319.py",
            test_reference="tests/test_l319_signals.py",
        )

    verified = store.review(
        record["record_id"], "verified",
        source_reference="controlled vehicle test #12",
        vehicle_applicability="2010-2016 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Measured on vehicle and independently checked",
    )
    assert verified["status"] == "verified"

    with pytest.raises(ValueError, match="implementation_reference"):
        store.review(
            record["record_id"], "supported",
            source_reference="controlled vehicle test #12",
            vehicle_applicability="2010-2016 LR4 5.0L 508PN",
            evidence_grade="A",
            verification_notes="Measured on vehicle and independently checked",
        )

    supported = store.review(
        record["record_id"], "supported",
        source_reference="controlled vehicle test #12",
        vehicle_applicability="2010-2016 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Measured on vehicle and independently checked",
        implementation_reference="src/freerov3r/signals/l319.py",
        test_reference="tests/test_l319_signals.py",
    )
    catalog = store.diagnostic_catalog(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )
    assert supported["status"] == "supported"
    assert len(catalog["verified_knowledge"]) == 0
    assert catalog["supported_capabilities"][0]["record_id"] == record["record_id"]


def test_vehicle_applicability_filters_profile_year_and_engine(tmp_path):
    store = _store(tmp_path)
    _record(store)
    assert store.for_vehicle("generic", model_year=2012, engine_id="508PN") == []
    assert store.for_vehicle(
        "land_rover_l319_lr4", model_year=2009, engine_id="508PN"
    ) == []
    assert store.for_vehicle(
        "land_rover_l319_lr4", model_year=2012, engine_id="306DT"
    ) == []


def test_platform_independent_knowledge_can_be_reused(tmp_path):
    store = _store(tmp_path)
    record = store.add_observation(
        "protocol_definition", "uds_service_0x22",
        {"service_id": 0x22, "name": "ReadDataByIdentifier"},
        applicability={"platform_independent": True},
        source_references=["ISO 14229-1"],
    )
    assert record["status"] == "observed"
    assert len(store.for_vehicle("land_rover_l319_lr4")) == 1
    assert len(store.for_vehicle("another_manufacturer_profile")) == 1


def test_rejects_missing_provenance_and_invalid_applicability(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="source reference"):
        store.add_observation(
            "module", "module_x", {}, applicability=_applicability()
        )
    with pytest.raises(ValueError, match="profile_ids"):
        store.add_observation(
            "module", "module_x", {}, applicability={"profile_ids": "lr4"},
            source_capture_ids=["capture"],
        )


def test_store_persists_and_deduplicates_by_identity(tmp_path):
    store = _store(tmp_path)
    first = _record(store)
    second = store.add_observation(
        "signal_definition",
        "engine_coolant_temperature",
        {"scale": 0.1},
        applicability=_applicability(),
        source_capture_ids=["capture-002"],
    )
    assert first["record_id"] == second["record_id"]
    assert second["data"]["scale"] == 0.1
    assert second["source_capture_ids"] == ["capture-001", "capture-002"]
    assert len(store.list_records()) == 1
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_supported_is_not_auto_promoted_by_repeated_observations(tmp_path):
    store = _store(tmp_path)
    first = _record(store)
    second = store.add_observation(
        "signal_definition",
        "engine_coolant_temperature",
        {"can_id": 0x123},
        applicability=_applicability(),
        source_capture_ids=["capture-002", "capture-003"],
    )
    assert first["status"] == second["status"] == "observed"



def test_only_reviewed_signal_evidence_imports_into_vehicle_knowledge(tmp_path):
    research = SignalEvidenceStore(tmp_path / "research.json")
    candidate = {
        "signal_type": "byte",
        "channel_a": "HS-CAN",
        "can_id_a": 0x120,
        "format_a": "STD",
        "byte_a": 1,
        "channel_b": "MS-CAN",
        "can_id_b": 0x321,
        "format_b": "STD",
        "byte_b": 2,
        "match_type": "exact",
        "xor_mask": 0,
    }
    observed = research.add_candidate(candidate, source_capture_ids=["capture-a"])
    knowledge = _store(tmp_path)

    with pytest.raises(ValueError, match="Only documented or verified"):
        knowledge.import_signal_evidence(
            research, observed["record_id"], applicability=_applicability()
        )

    research.update_review(
        observed["record_id"], "verified",
        source_reference="controlled L319 vehicle test #24",
        vehicle_applicability="2010-2016 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Repeated under controlled conditions and independently checked",
    )
    imported = knowledge.import_signal_evidence(
        research, observed["record_id"], applicability=_applicability()
    )
    assert imported["status"] == "verified"
    catalog = knowledge.diagnostic_catalog(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )
    assert len(catalog["verified_knowledge"]) == 1
    assert catalog["supported_capabilities"] == []
    assert research.get_record(observed["record_id"])["status"] == "verified"



def test_changed_payload_resets_prior_verification_and_support(tmp_path):
    store = _store(tmp_path)
    record = _record(store)
    verified = store.review(
        record["record_id"], "verified",
        source_reference="controlled vehicle test #12",
        vehicle_applicability="2010-2016 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Measured and independently checked",
    )
    store.review(
        verified["record_id"], "supported",
        source_reference="controlled vehicle test #12",
        vehicle_applicability="2010-2016 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Measured and independently checked",
        implementation_reference="src/freerov3r/signals/l319.py",
        test_reference="tests/test_l319_signals.py",
    )

    updated = store.add_observation(
        "signal_definition",
        "engine_coolant_temperature",
        {"scale": 0.5},
        applicability=_applicability(),
        source_capture_ids=["capture-002"],
    )
    assert updated["status"] == "observed"
    assert updated["implementation_reference"] == ""
    assert any(
        item["event"] == "data_changed_review_reset" for item in updated["history"]
    )


def test_source_provenance_arguments_reject_bare_strings(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="source_references"):
        store.add_observation(
            "protocol", "uds",
            {"service": 0x22},
            applicability={"platform_independent": True},
            source_references="ISO 14229",
        )
    with pytest.raises(ValueError, match="source_capture_ids"):
        store.add_observation(
            "protocol", "uds",
            {"service": 0x22},
            applicability={"platform_independent": True},
            source_capture_ids="capture-001",
        )


def test_platform_independent_flag_must_be_boolean(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="must be a boolean"):
        store.add_observation(
            "protocol", "uds",
            {"service": 0x22},
            applicability={"platform_independent": "false"},
            source_references=["ISO 14229"],
        )



def test_passive_module_discovery_is_retained_as_observation_not_ecu_identity(tmp_path):
    store = _store(tmp_path)
    report = {
        "method": "passive_capture_analysis",
        "transmission_performed": False,
        "nodes": [{
            "can_id": 0x7E8,
            "extended": False,
            "channel": "HS-CAN",
            "frame_count": 18,
            "role": "candidate_uds_responder",
            "evidence_level": "Probable",
            "uds_pair_count": 4,
            "services": [0x22, 0x3E],
            "request_ids": [0x7E0],
            "interpretation": "Probable UDS response association; physical ECU unknown",
        }],
    }

    records = store.import_module_discovery_report(
        report,
        applicability=_applicability(),
        capture_id="capture-lr4-001",
    )
    assert len(records) == 1
    assert records[0]["status"] == "observed"
    assert records[0]["artifact_type"] == "observed_can_node"
    assert records[0]["data"]["identity_confirmed"] is False
    assert records[0]["data"]["role"] == "candidate_uds_responder"
    assert records[0]["source_capture_ids"] == ["capture-lr4-001"]
    assert store.diagnostic_catalog(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )["verified_knowledge"] == []


def test_multi_capture_module_comparison_preserves_each_capture_id(tmp_path):
    store = _store(tmp_path)
    report = {
        "method": "independent_passive_capture_comparison",
        "transmission_performed": False,
        "nodes": [{
            "can_id": 0x7E8,
            "extended": False,
            "channel": "HS-CAN",
            "observed_frame_count": 30,
            "role": "candidate_uds_responder",
            "evidence_level": "Probable",
            "capture_names": ["ignition_on", "engine_running"],
            "capture_count": 2,
            "probable_capture_count": 2,
        }],
    }
    records = store.import_module_discovery_report(
        report,
        applicability=_applicability(),
        capture_ids={
            "ignition_on": "session-001",
            "engine_running": "session-002",
        },
    )
    assert records[0]["source_capture_ids"] == ["session-001", "session-002"]
    assert records[0]["status"] == "observed"


def test_module_discovery_import_rejects_transmitting_or_untraceable_reports(tmp_path):
    store = _store(tmp_path)
    report = {
        "method": "passive_capture_analysis",
        "transmission_performed": True,
        "nodes": [{"can_id": 0x123, "extended": False}],
    }
    with pytest.raises(ValueError, match="passive"):
        store.import_module_discovery_report(
            report, applicability=_applicability(), capture_id="capture"
        )

    report["transmission_performed"] = False
    with pytest.raises(ValueError, match="traceable"):
        store.import_module_discovery_report(
            report, applicability=_applicability()
        )



def test_multi_capture_import_requires_stable_ids_for_each_capture(tmp_path):
    store = _store(tmp_path)
    report = {
        "method": "independent_passive_capture_comparison",
        "transmission_performed": False,
        "nodes": [{
            "can_id": 0x7E8,
            "extended": False,
            "channel": "HS-CAN",
            "capture_names": ["ignition_on", "engine_running"],
        }],
    }
    with pytest.raises(ValueError, match="stable capture_ids"):
        store.import_module_discovery_report(
            report, applicability=_applicability()
        )
    with pytest.raises(ValueError, match="missing stable capture identifiers"):
        store.import_module_discovery_report(
            report,
            applicability=_applicability(),
            capture_ids={"ignition_on": "session-001"},
        )



def test_module_inventory_separates_observed_nodes_from_verified_identities(tmp_path):
    store = _store(tmp_path)
    node = store.add_observation(
        "observed_can_node",
        "HS-CAN:STD:7E8",
        {
            "can_id": 0x7E8,
            "extended": False,
            "channel": "HS-CAN",
            "identity_confirmed": False,
            "role": "candidate_uds_responder",
        },
        applicability=_applicability(),
        source_capture_ids=["capture-001"],
    )
    candidate = store.add_observation(
        "module_identity",
        "engine_control_module",
        {"name": "Engine control module", "can_id": 0x7E8},
        applicability=_applicability(),
        source_references=["Land Rover workshop manual, section 303"],
    )
    inventory = store.module_inventory(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )
    assert [item["record_id"] for item in inventory["observed_can_nodes"]] == [
        node["record_id"]
    ]
    assert [item["record_id"] for item in inventory["candidate_module_identities"]] == [
        candidate["record_id"]
    ]
    assert inventory["verified_module_identities"] == []
    assert inventory["supported_module_identities"] == []
    assert "not physical ECU identities" in inventory["identity_warning"]


def test_module_inventory_only_lists_verified_or_supported_module_identities(tmp_path):
    store = _store(tmp_path)
    record = store.add_observation(
        "module_identity",
        "body_control_module",
        {"name": "Body control module", "network": "MS-CAN"},
        applicability=_applicability(),
        source_references=["verified wiring diagram reference"],
    )
    store.review(
        record["record_id"], "verified",
        source_reference="Land Rover electrical library, 2012 LR4",
        vehicle_applicability="2012 LR4 5.0L 508PN",
        evidence_grade="A",
        verification_notes="Confirmed against the applicable wiring diagram and vehicle connector identification",
    )
    inventory = store.module_inventory(
        "land_rover_l319_lr4", model_year=2012, engine_id="508PN"
    )
    assert [item["record_id"] for item in inventory["verified_module_identities"]] == [
        record["record_id"]
    ]
    assert inventory["supported_module_identities"] == []
