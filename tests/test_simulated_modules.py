from freerov3r.diagnostics.simulated_modules import SimulatedModuleNetwork


def test_simulated_module_scan_returns_seeded_dtcs():
    network = SimulatedModuleNetwork()
    module = network.scan_module("ECM")
    assert module.code == "ECM"
    assert module.last_scan is not None
    assert {dtc.code for dtc in module.dtcs} == {"P0420", "P0113"}


def test_scan_all_covers_categories_and_modules():
    network = SimulatedModuleNetwork()
    modules = network.scan_all()
    assert len(modules) >= 10
    assert all(module.last_scan for module in modules)
    assert {module.category for module in modules} >= {"Powertrain", "Chassis", "Body", "Safety"}


def test_clear_one_code_does_not_clear_other_codes_or_modules():
    network = SimulatedModuleNetwork()
    assert network.clear_code("ECM", "P0420")
    assert [dtc.code for dtc in network.get_module("ECM").dtcs] == ["P0113"]
    assert [dtc.code for dtc in network.get_module("TCM").dtcs] == ["P0705"]


def test_clear_module_and_clear_all():
    network = SimulatedModuleNetwork()
    cleared = network.clear_module("ECM")
    assert cleared == 2
    assert network.get_module("ECM").dtcs == []
    total = network.clear_all()
    assert total > 0
    assert all(not module.dtcs for module in network.modules)



def test_simulated_module_state_round_trips_between_instances(tmp_path):
    path = tmp_path / "vehicles" / "VIN123" / "simulated_modules.json"
    original = SimulatedModuleNetwork()
    original.scan_module("ECM")
    original.clear_code("ECM", "P0420")
    original.clear_module("TCM")
    original.save_state(path)

    restored = SimulatedModuleNetwork()
    assert restored.load_state(path)
    assert [dtc.code for dtc in restored.get_module("ECM").dtcs] == ["P0113"]
    assert restored.get_module("ECM").last_scan is not None
    assert restored.get_module("TCM").dtcs == []
    assert restored.get_module("ABS").dtcs[0].code == "C003A"


def test_invalid_or_unknown_state_keeps_safe_seeded_defaults(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")
    network = SimulatedModuleNetwork()
    assert not network.load_state(path)
    assert {dtc.code for dtc in network.get_module("ECM").dtcs} == {"P0420", "P0113"}

    path.write_text('{"schema_version": 99, "modules": []}', encoding="utf-8")
    assert not network.load_state(path)
    assert {dtc.code for dtc in network.get_module("ECM").dtcs} == {"P0420", "P0113"}



def test_invalid_state_does_not_partially_modify_network(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(
        '{"schema_version": 1, "modules": ['
        '{"code": "ECM", "dtcs": []},'
        '{"code": "TCM", "dtcs": [{"description": "missing code"}]}'
        ']}',
        encoding="utf-8",
    )
    network = SimulatedModuleNetwork()
    assert not network.load_state(path)
    assert {dtc.code for dtc in network.get_module("ECM").dtcs} == {"P0420", "P0113"}
    assert {dtc.code for dtc in network.get_module("TCM").dtcs} == {"P0705"}
