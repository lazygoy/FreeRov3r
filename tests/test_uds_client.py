import pytest

from freerov3r.diagnostics.uds_client import (
    UdsDiagnosticClient,
    UdsRequestDenied,
    UdsTransactionTimeout,
)
from freerov3r.hardware.capabilities import AdapterCapabilities, TransmitPolicy
from freerov3r.safety import SafetyPolicy


class FakeTransport:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []

    def send_payload(self, payload):
        self.sent.append(bytes(payload))

    def receive_payload(self):
        if not self.responses:
            raise TimeoutError("no response")
        return self.responses.pop(0)


def enabled_capabilities(**overrides):
    values = {
        "uds_active_requests": True,
        "uds_diagnostic_requests_implemented": True,
    }
    values.update(overrides)
    return AdapterCapabilities(**values)


def enabled_transmit_policy(**overrides):
    values = {"uds_requests_enabled": True}
    values.update(overrides)
    return TransmitPolicy(**values)


def enabled_safety_policy(**overrides):
    values = {"allow_transmit": True}
    values.update(overrides)
    return SafetyPolicy(**values)


def make_client(transport, *, capabilities=None, transmit_policy=None, safety_policy=None):
    return UdsDiagnosticClient(
        transport,
        capabilities or enabled_capabilities(),
        transmit_policy or enabled_transmit_policy(),
        safety_policy or enabled_safety_policy(),
    )


def test_read_did_requires_explicit_confirmation():
    transport = FakeTransport([bytes.fromhex("62 F1 90 12 34")])
    client = make_client(transport)

    with pytest.raises(UdsRequestDenied, match="confirmation"):
        client.read_data_by_identifier([0xF190])

    assert transport.sent == []


def test_read_did_sends_and_decodes_after_all_gates_pass():
    transport = FakeTransport([bytes.fromhex("62 F1 90 12 34")])
    client = make_client(transport)

    result = client.read_data_by_identifier([0xF190], confirmed=True)

    assert transport.sent == [bytes.fromhex("22 F1 90")]
    assert result["kind"] == "positive"
    assert result["did"] == 0xF190
    assert result["record_data"] == "1234"


@pytest.mark.parametrize(
    "capabilities,policy",
    [
        (enabled_capabilities(uds_active_requests=False), enabled_transmit_policy()),
        (enabled_capabilities(uds_diagnostic_requests_implemented=False), enabled_transmit_policy()),
        (enabled_capabilities(), TransmitPolicy(diagnostic_requests_enabled=True)),
    ],
)
def test_uds_capability_and_permission_are_independent(capabilities, policy):
    transport = FakeTransport()
    client = make_client(transport, capabilities=capabilities, transmit_policy=policy)

    with pytest.raises(UdsRequestDenied, match="capability"):
        client.read_data_by_identifier([0xF190], confirmed=True)

    assert transport.sent == []


def test_safety_transmit_gate_is_independent_of_uds_permission():
    transport = FakeTransport()
    client = make_client(transport, safety_policy=SafetyPolicy())

    with pytest.raises(UdsRequestDenied, match="Transmit disabled"):
        client.read_data_by_identifier([0xF190], confirmed=True)

    assert transport.sent == []


def test_write_service_is_rejected_before_any_transport_activity():
    transport = FakeTransport()
    client = make_client(transport)

    with pytest.raises(ValueError, match="not allowed"):
        client.execute_read_request(bytes.fromhex("2E F1 90"), confirmed=True)

    assert transport.sent == []


def test_unsupported_dtc_subfunction_is_rejected():
    transport = FakeTransport()
    client = make_client(transport)

    with pytest.raises(ValueError, match="Only UDS ReadDTCInformation"):
        client.execute_read_request(bytes.fromhex("19 04"), confirmed=True)

    assert transport.sent == []


def test_response_pending_is_followed_by_final_positive_response():
    transport = FakeTransport([
        bytes.fromhex("7F 22 78"),
        bytes.fromhex("62 F1 90 AB CD"),
    ])
    client = make_client(transport)

    result = client.read_data_by_identifier([0xF190], confirmed=True)

    assert len(transport.sent) == 1
    assert result["kind"] == "positive"
    assert result["record_data"] == "abcd"


def test_pending_response_limit_is_bounded():
    transport = FakeTransport([bytes.fromhex("7F 22 78")] * 3)
    client = make_client(transport)

    with pytest.raises(UdsTransactionTimeout, match="pending limit"):
        client.execute_read_request(
            bytes.fromhex("22 F1 90"),
            confirmed=True,
            max_pending=2,
        )

    assert len(transport.sent) == 1


def test_read_dtc_information_decodes_dtc_records():
    transport = FakeTransport([bytes.fromhex("59 02 FF 01 23 45 0F")])
    client = make_client(transport)

    result = client.read_dtcs(confirmed=True)

    assert transport.sent == [bytes.fromhex("19 02 FF")]
    assert result["dtcs"] == [{"dtc": 0x012345, "status": 0x0F}]
