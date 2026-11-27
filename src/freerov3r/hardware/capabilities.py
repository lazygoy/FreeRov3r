"""Adapter capability declarations and independent transmit policy.

Capability describes the intended interface contract. Implementation flags
state what the current adapter/firmware can actually execute. Permission is
evaluated separately and never follows merely from capability.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterCapabilities:
    raw_can_receive: bool = False
    raw_can_transmit: bool = False
    raw_can_transmit_implemented: bool = False
    obd2_passive_decode: bool = False
    obd2_active_requests: bool = False
    diagnostic_requests_implemented: bool = False
    uds_active_requests: bool = False
    dual_channel: bool = False
    hardware_timestamp: bool = False
    device_clock_calibration: bool = False
    device_clock_calibration_implemented: bool = False


@dataclass(frozen=True)
class TransmitPolicy:
    diagnostic_requests_enabled: bool = False
    general_can_transmit_enabled: bool = False
    bench_mode: bool = False

    def allows_diagnostic_request(self, capabilities: AdapterCapabilities) -> bool:
        return bool(
            capabilities.obd2_active_requests
            and capabilities.diagnostic_requests_implemented
            and self.diagnostic_requests_enabled
        )

    def allows_general_can_transmit(self, capabilities: AdapterCapabilities) -> bool:
        return bool(
            capabilities.raw_can_transmit
            and capabilities.raw_can_transmit_implemented
            and self.general_can_transmit_enabled
            and self.bench_mode
        )


ELM327_OBD_CAPABILITIES = AdapterCapabilities(
    obd2_active_requests=True,
    diagnostic_requests_implemented=True,
)

ELM327_RAW_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
)

ESP32_SINGLE_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    raw_can_transmit_implemented=False,
    obd2_passive_decode=True,
    obd2_active_requests=True,
    diagnostic_requests_implemented=False,
    device_clock_calibration=True,
    device_clock_calibration_implemented=True,
)

ESP32_DUAL_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    raw_can_transmit_implemented=False,
    obd2_passive_decode=True,
    obd2_active_requests=True,
    diagnostic_requests_implemented=False,
    dual_channel=True,
    hardware_timestamp=True,
    device_clock_calibration=True,
    device_clock_calibration_implemented=True,
)

SOCKETCAN_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    raw_can_transmit_implemented=True,
    obd2_passive_decode=True,
    obd2_active_requests=True,
    diagnostic_requests_implemented=True,
)
