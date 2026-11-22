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
