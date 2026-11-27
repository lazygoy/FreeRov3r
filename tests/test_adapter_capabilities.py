from freerov3r.hardware.capabilities import (
    AdapterCapabilities,
    ELM327_OBD_CAPABILITIES,
    ELM327_RAW_CAPABILITIES,
    ESP32_DUAL_CAPABILITIES,
    ESP32_SINGLE_CAPABILITIES,
    TransmitPolicy,
)


def test_elm_obd_supports_active_diagnostics_but_not_raw_can_capture():
    assert ELM327_OBD_CAPABILITIES.obd2_active_requests
    assert ELM327_OBD_CAPABILITIES.diagnostic_requests_implemented
    assert not ELM327_OBD_CAPABILITIES.raw_can_receive
    assert not ELM327_OBD_CAPABILITIES.raw_can_transmit


def test_elm_raw_monitor_does_not_claim_active_obd_polling_or_raw_transmit():
    assert ELM327_RAW_CAPABILITIES.raw_can_receive
    assert not ELM327_RAW_CAPABILITIES.raw_can_transmit
    assert not ELM327_RAW_CAPABILITIES.obd2_active_requests


def test_esp32_declares_future_bidirectional_capability_but_firmware_is_receive_only():
    policy = TransmitPolicy(diagnostic_requests_enabled=True)

    assert ESP32_SINGLE_CAPABILITIES.raw_can_receive
    assert ESP32_SINGLE_CAPABILITIES.raw_can_transmit
    assert not ESP32_SINGLE_CAPABILITIES.raw_can_transmit_implemented
    assert ESP32_SINGLE_CAPABILITIES.obd2_passive_decode
    assert ESP32_SINGLE_CAPABILITIES.obd2_active_requests
    assert not ESP32_SINGLE_CAPABILITIES.diagnostic_requests_implemented
    assert not policy.allows_diagnostic_request(ESP32_SINGLE_CAPABILITIES)
    assert not policy.allows_general_can_transmit(ESP32_SINGLE_CAPABILITIES)


def test_elm_diagnostic_requests_require_explicit_policy_enablement():
    assert not TransmitPolicy().allows_diagnostic_request(ELM327_OBD_CAPABILITIES)
    assert TransmitPolicy(
        diagnostic_requests_enabled=True
    ).allows_diagnostic_request(ELM327_OBD_CAPABILITIES)


def test_general_can_transmit_requires_implementation_permission_and_bench_mode():
    planned_esp32 = AdapterCapabilities(
        raw_can_receive=True,
        raw_can_transmit=True,
        raw_can_transmit_implemented=False,
    )
    assert not TransmitPolicy(
        general_can_transmit_enabled=True,
        bench_mode=True,
    ).allows_general_can_transmit(planned_esp32)

    implemented = AdapterCapabilities(
        raw_can_receive=True,
        raw_can_transmit=True,
        raw_can_transmit_implemented=True,
    )
    assert not TransmitPolicy(
        general_can_transmit_enabled=True
    ).allows_general_can_transmit(implemented)
    assert TransmitPolicy(
        general_can_transmit_enabled=True,
        bench_mode=True,
    ).allows_general_can_transmit(implemented)


def test_dual_esp32_declares_two_channels_and_hardware_timestamps():
    assert ESP32_DUAL_CAPABILITIES.dual_channel
    assert ESP32_DUAL_CAPABILITIES.hardware_timestamp


def test_receive_only_adapter_cannot_transmit_even_with_all_policy_switches():
    receive_only = AdapterCapabilities(raw_can_receive=True)
    policy = TransmitPolicy(
        diagnostic_requests_enabled=True,
        general_can_transmit_enabled=True,
        bench_mode=True,
    )

    assert not policy.allows_diagnostic_request(receive_only)
    assert not policy.allows_general_can_transmit(receive_only)
