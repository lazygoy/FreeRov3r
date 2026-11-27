from freerov3r.hardware.capabilities import (
    AdapterCapabilities,
    ELM327_OBD_CAPABILITIES,
    ELM327_RAW_CAPABILITIES,
    ESP32_DUAL_CAPABILITIES,
    ESP32_SINGLE_CAPABILITIES,
    TransmitPolicy,
)


def test_elm_obd_supports_diagnostic_requests_but_not_raw_can_capture():
    assert ELM327_OBD_CAPABILITIES.obd2_active_requests
    assert not ELM327_OBD_CAPABILITIES.raw_can_receive
    assert not ELM327_OBD_CAPABILITIES.raw_can_transmit


def test_elm_raw_monitor_does_not_claim_raw_can_transmit_or_obd_polling():
    assert ELM327_RAW_CAPABILITIES.raw_can_receive
    assert not ELM327_RAW_CAPABILITIES.raw_can_transmit
    assert not ELM327_RAW_CAPABILITIES.obd2_active_requests


def test_esp32_declares_bidirectional_capability_without_enabling_it():
    policy = TransmitPolicy()

    assert ESP32_SINGLE_CAPABILITIES.raw_can_receive
    assert ESP32_SINGLE_CAPABILITIES.raw_can_transmit
    assert ESP32_SINGLE_CAPABILITIES.obd2_passive_decode
    assert ESP32_SINGLE_CAPABILITIES.obd2_active_requests
    assert not policy.allows_diagnostic_request(ESP32_SINGLE_CAPABILITIES)
    assert not policy.allows_general_can_transmit(ESP32_SINGLE_CAPABILITIES)


def test_diagnostic_request_permission_is_separate_from_general_transmit():
    policy = TransmitPolicy(diagnostic_requests_enabled=True)

    assert policy.allows_diagnostic_request(ESP32_SINGLE_CAPABILITIES)
    assert not policy.allows_general_can_transmit(ESP32_SINGLE_CAPABILITIES)


def test_general_transmit_requires_explicit_enablement_and_bench_mode():
    policy = TransmitPolicy(general_can_transmit_enabled=True)

    assert not policy.allows_general_can_transmit(ESP32_SINGLE_CAPABILITIES)

    bench_policy = TransmitPolicy(
        general_can_transmit_enabled=True,
        bench_mode=True,
    )
    assert bench_policy.allows_general_can_transmit(ESP32_SINGLE_CAPABILITIES)


def test_dual_esp32_declares_two_channels():
    assert ESP32_DUAL_CAPABILITIES.dual_channel
    assert ESP32_DUAL_CAPABILITIES.hardware_timestamp


def test_capabilities_do_not_grant_transmit_to_receive_only_adapter():
    receive_only = AdapterCapabilities(raw_can_receive=True)
    policy = TransmitPolicy(
        diagnostic_requests_enabled=True,
        general_can_transmit_enabled=True,
        bench_mode=True,
    )

    assert not policy.allows_diagnostic_request(receive_only)
    assert not policy.allows_general_can_transmit(receive_only)
