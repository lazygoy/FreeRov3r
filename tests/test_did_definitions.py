import pytest

from freerov3r.did_definitions import (
    DIDDefinitionRegistry,
    normalize_did_definition,
)


def definition(**overrides):
    value = {
        "did": "0xF190",
        "vehicle": "Land Rover L319 5.0 petrol",
        "module": "Unassigned module",
        "name": "Example identity record",
        "confidence": "unverified",
        "source": {
            "title": "Locally verified engineering record",
            "reference": "Notebook page 4",
        },
        "fields": [
            {"name": "serial", "offset": 0, "length": 2, "encoding": "hex"},
            {"name": "temperature", "offset": 2, "length": 2,
             "encoding": "signed", "scale": 0.1, "unit": "°C"},
        ],
    }
    value.update(overrides)
    return value


def test_registry_decodes_only_matching_positive_response_with_provenance():
    registry = DIDDefinitionRegistry([definition()])
    result = registry.decode_response(
        0xF190, "62 F1 90 12 34 FF 9C",
        vehicle="Land Rover L319 5.0 petrol",
    )
    assert result["status"] == "decoded"
    assert result["definition"]["confidence"] == "unverified"
    assert result["definition"]["source"]["reference"] == "Notebook page 4"
    assert result["fields"][0]["value"] == "1234"
    assert result["fields"][1]["value"] == -10
    assert result["fields"][1]["unit"] == "°C"


def test_unknown_vehicle_or_did_is_never_decoded_by_guess():
    registry = DIDDefinitionRegistry([definition()])
    result = registry.decode_response(
        0xF190, "62 F1 90 12 34 FF 9C",
        vehicle="Different vehicle",
    )
    assert result["status"] == "unknown_definition"
    assert result["data"] == "1234ff9c"
    assert result["fields"] == []


def test_decoder_rejects_wrong_service_and_wrong_did():
    registry = DIDDefinitionRegistry([definition()])
    assert registry.decode_response(
        0xF190, "7F 22 31", vehicle="Land Rover L319 5.0 petrol"
    )["status"] == "not_positive_did_response"
    assert registry.decode_response(
        0xF190, "62 F1 87 12 34", vehicle="Land Rover L319 5.0 petrol"
    )["status"] == "response_did_mismatch"


def test_decoder_marks_short_fields_as_truncated():
    registry = DIDDefinitionRegistry([definition()])
    result = registry.decode_response(
        0xF190, "62 F1 90 12 34",
        vehicle="Land Rover L319 5.0 petrol",
    )
    assert result["fields"][0]["status"] == "decoded"
    assert result["fields"][1]["status"] == "truncated"
    assert result["fields"][1]["value"] is None


@pytest.mark.parametrize("bad", [
    {"did": "xyz"},
    {"did": 0x10000},
    {"did": 0xF190, "vehicle": "LR4", "name": "bad", "source": {}},
])
def test_definition_requires_valid_did_and_source_provenance(bad):
    value = definition()
    value.update(bad)
    with pytest.raises(ValueError):
        normalize_did_definition(value)


def test_definition_rejects_invalid_field_ranges_and_nonfinite_scaling():
    value = definition()
    value["fields"] = [{"name": "bad", "offset": -1, "length": 1}]
    with pytest.raises(ValueError):
        normalize_did_definition(value)
    value["fields"] = [{"name": "bad", "offset": 0, "length": 1, "scale": float("nan")}]
    with pytest.raises(ValueError):
        normalize_did_definition(value)


def test_json_registry_load(tmp_path):
    import json

    path = tmp_path / "did-definitions.json"
    path.write_text(json.dumps({"definitions": [definition()]}), encoding="utf-8")
    registry = DIDDefinitionRegistry.from_json(path)
    assert registry.get("F190", vehicle="Land Rover L319 5.0 petrol")["name"] == "Example identity record"


def test_capture_decoder_only_decodes_paired_single_did_positive_reads():
    from freerov3r.did_definitions import decode_uds_did_transactions

    registry = DIDDefinitionRegistry([definition()])
    pairs = [
        {
            "confidence": "probable",
            "request_service": 0x22,
            "response_kind": "positive",
            "request": {"payload": "22f190", "arbitration_id": 0x7E0},
            "response": {"payload": "62f1901234ff9c", "arbitration_id": 0x7E8},
        },
        {
            "confidence": "probable",
            "request_service": 0x22,
            "response_kind": "positive",
            "request": {"payload": "22f190f187", "arbitration_id": 0x7E0},
            "response": {"payload": "62f1901234f187", "arbitration_id": 0x7E8},
        },
        {
            "confidence": "probable",
            "request_service": 0x22,
            "response_kind": "negative",
            "request": {"payload": "22f190", "arbitration_id": 0x7E0},
            "response": {"payload": "7f2231", "arbitration_id": 0x7E8},
        },
    ]
    result = decode_uds_did_transactions(
        pairs, registry, vehicle="Land Rover L319 5.0 petrol"
    )
    assert len(result) == 1
    assert result[0]["did"] == 0xF190
    assert result[0]["decoded"]["fields"][0]["value"] == "1234"
    assert result[0]["response_payload"] == "62f1901234ff9c"



def test_validate_registry_file_reports_counts_and_vehicle(tmp_path):
    import json
    from freerov3r.did_definitions import validate_registry_file

    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"definitions": [definition()]}), encoding="utf-8")
    summary = validate_registry_file(path)
    assert summary["definition_count"] == 1
    assert summary["vehicles"] == ["Land Rover L319 5.0 petrol"]
    assert summary["confidence_counts"]["unverified"] == 1


def test_registry_cli_rejects_invalid_definition_file(tmp_path, capsys):
    from freerov3r.did_definitions import main

    path = tmp_path / "invalid.json"
    path.write_text('{"definitions": [{"did": "F190"}]}', encoding="utf-8")
    assert main([str(path)]) == 1
    assert "INVALID:" in capsys.readouterr().err


def test_registry_cli_accepts_empty_template(tmp_path, capsys):
    import json
    from freerov3r.did_definitions import main

    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"schema_version": 1, "definitions": []}), encoding="utf-8")
    assert main([str(path)]) == 0
    assert "VALID: 0 DID definition(s)" in capsys.readouterr().out
