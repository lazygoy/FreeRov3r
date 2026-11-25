from freerov3r.diagnostics.module_discovery import discover_modules


def _sf(payload, can_id, timestamp, channel="HS-CAN"):
    payload = bytes(payload)
    return {
        "timestamp": timestamp,
        "arbitration_id": can_id,
        "extended": False,
        "channel": channel,
        "data": (bytes([len(payload)]) + payload).hex(),
    }


def test_discovery_reports_observed_nodes_without_guessing_module_identity():
    report = discover_modules([
        {"timestamp": 1.0, "arbitration_id": 0x321, "extended": False,
         "channel": "HS-CAN", "data": "0102030405060708"},
    ])
    assert report["transmission_performed"] is False
    assert report["valid_observed_id_count"] == 1
    node = report["nodes"][0]
    assert node["can_id"] == 0x321
    assert node["role"] == "observed_can_node"
    assert node["evidence_level"] == "Observed"
    assert node["services"] == []
    assert "identity unknown" in node["interpretation"]


def test_discovery_marks_only_paired_uds_response_id_as_probable_responder():
    frames = [
        _sf(b"\x22\xF1\x90", 0x7E0, 1.0),
        _sf(b"\x62\xF1\x90", 0x7E8, 1.05),
    ]
    report = discover_modules(frames)
    by_id = {node["can_id"]: node for node in report["nodes"]}
    assert report["probable_uds_transaction_count"] == 1
    assert by_id[0x7E0]["role"] == "observed_can_node"
    assert by_id[0x7E8]["role"] == "candidate_uds_responder"
    assert by_id[0x7E8]["evidence_level"] == "Probable"
    assert by_id[0x7E8]["request_ids"] == [0x7E0]
    assert by_id[0x7E8]["services"] == [0x22]


def test_discovery_keeps_channels_and_can_formats_separate():
    report = discover_modules([
        {"timestamp": 1.0, "arbitration_id": 0x123, "extended": False,
         "channel": "HS-CAN", "data": "010203"},
        {"timestamp": 2.0, "arbitration_id": 0x123, "extended": True,
         "channel": "MS-CAN", "data": "040506"},
    ])
    assert len(report["nodes"]) == 2
    assert {(node["extended"], node["channel"]) for node in report["nodes"]} == {
        (False, "HS-CAN"), (True, "MS-CAN")
    }


def test_discovery_ignores_malformed_capture_records():
    report = discover_modules([
        {"arbitration_id": 0x123, "data": "not-hex"},
        {"arbitration_id": 0x124},
    ])
    assert report["nodes"] == []
    assert report["valid_observed_id_count"] == 0


def test_cross_capture_inventory_tracks_repeatability_without_upgrading_identity():
    from freerov3r.diagnostics.module_discovery import compare_module_discovery

    captures = [
        {"name": "idle", "frames": [
            {"timestamp": 1.0, "arbitration_id": 0x321, "extended": False,
             "channel": "HS-CAN", "data": "010203"},
        ]},
        {"name": "engine-running", "frames": [
            {"timestamp": 2.0, "arbitration_id": 0x321, "extended": False,
             "channel": "HS-CAN", "data": "040506"},
        ]},
    ]
    report = compare_module_discovery(captures)
    assert report["transmission_performed"] is False
    assert report["capture_count"] == 2
    assert report["node_count"] == 1
    node = report["nodes"][0]
    assert node["capture_count"] == 2
    assert node["repeatability"] == "Seen in multiple captures"
    assert node["evidence_level"] == "Observed"
    assert node["role"] == "observed_can_node"


def test_cross_capture_inventory_retains_probable_responder_evidence():
    from freerov3r.diagnostics.module_discovery import compare_module_discovery

    request = _sf(bytes.fromhex("22 F1 90"), 0x7E0, 1.0)
    response = _sf(bytes.fromhex("62 F1 90"), 0x7E8, 1.05)
    report = compare_module_discovery([
        {"name": "scan", "frames": [request, response]},
        {"name": "idle", "frames": [
            {"timestamp": 2.0, "arbitration_id": 0x7E8, "extended": False,
             "channel": "HS-CAN", "data": "010203"},
        ]},
    ])
    node = next(item for item in report["nodes"] if item["can_id"] == 0x7E8)
    assert node["evidence_level"] == "Probable"
    assert node["probable_capture_count"] == 1
    assert node["capture_count"] == 2
    assert node["request_ids"] == [0x7E0]
    assert node["services"] == [0x22]


def test_cross_capture_inventory_keeps_same_id_on_different_channels_separate():
    from freerov3r.diagnostics.module_discovery import compare_module_discovery

    report = compare_module_discovery([
        {"name": "capture", "frames": [
            {"timestamp": 1.0, "arbitration_id": 0x123, "extended": False,
             "channel": "HS-CAN", "data": "010203"},
            {"timestamp": 1.1, "arbitration_id": 0x123, "extended": False,
             "channel": "MS-CAN", "data": "040506"},
        ]},
    ])
    assert len(report["nodes"]) == 2
    assert {node["channel"] for node in report["nodes"]} == {"HS-CAN", "MS-CAN"}


def test_cross_capture_inventory_disambiguates_duplicate_capture_names():
    from freerov3r.diagnostics.module_discovery import compare_module_discovery

    report = compare_module_discovery([
        {"name": "same", "frames": [
            {"timestamp": 1.0, "arbitration_id": 0x123, "data": "010203"},
        ]},
        {"name": "same", "frames": [
            {"timestamp": 2.0, "arbitration_id": 0x123, "data": "040506"},
        ]},
    ])
    node = report["nodes"][0]
    assert node["capture_names"] == ["same [capture 1]", "same [capture 2]"]
    assert node["capture_count"] == 2
