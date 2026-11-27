"""Adapter capability declarations and transmit policy for CAN interfaces.

Capabilities describe what an adapter can do. They do not grant permission
to perform a transmit operation; runtime policy is evaluated separately.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterCapabilities:
    raw_can_receive: bool = False
    raw_can_transmit: bool = False
    obd2_passive_decode: bool = False
    obd2_active_requests: bool = False
    uds_active_requests: bool = False
    dual_channel: bool = False
    hardware_timestamp: bool = False


@dataclass(frozen=True)
class TransmitPolicy:
    diagnostic_requests_enabled: bool = False
    general_can_transmit_enabled: bool = False
    bench_mode: bool = False

    def allows_diagnostic_request(self, capabilities: AdapterCapabilities) -> bool:
        return bool(
            capabilities.raw_can_transmit
            and capabilities.obd2_active_requests
            and self.diagnostic_requests_enabled
        )

    def allows_general_can_transmit(self, capabilities: AdapterCapabilities) -> bool:
        return bool(
            capabilities.raw_can_transmit
            and self.general_can_transmit_enabled
            and self.bench_mode
        )


ELM327_OBD_CAPABILITIES = AdapterCapabilities(
    obd2_active_requests=True,
)

ELM327_RAW_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
)

ESP32_SINGLE_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    obd2_passive_decode=True,
    obd2_active_requests=True,
)

ESP32_DUAL_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    obd2_passive_decode=True,
    obd2_active_requests=True,
    dual_channel=True,
    hardware_timestamp=True,
)

SOCKETCAN_CAPABILITIES = AdapterCapabilities(
    raw_can_receive=True,
    raw_can_transmit=True,
    obd2_passive_decode=True,
    obd2_active_requests=True,
)
