"""Guarded read-only UDS transaction client.

This layer connects the UDS payload codec to an injected ISO-TP endpoint.
It deliberately does not choose ECU addresses or open an adapter. Hardware
capability, separate UDS permission, and the application's safety policy must
all authorize each transaction before any frame can be sent.
"""

import time

from ..hardware.capabilities import AdapterCapabilities, TransmitPolicy
from ..safety import SafetyPolicy
from ..isotp_transport import IsoTpTimeout
from .uds import (
    build_read_data_by_identifier_request,
    build_read_dtc_information_request,
    decode_uds_response,
)


class UdsRequestDenied(PermissionError):
    """The adapter, user policy, or safety policy denied a UDS request."""


class UdsTransactionTimeout(TimeoutError):
    """The UDS response did not complete before the transaction deadline."""


class UdsDiagnosticClient:
    """Execute only the supported read-only UDS services over an injected link.

    transport must expose send_payload(bytes) and receive_payload().
    The transport's own per-frame authorization callback remains mandatory
    and is checked independently for every outgoing CAN frame.
    """

    def __init__(
        self,
        transport,
        capabilities: AdapterCapabilities,
        transmit_policy: TransmitPolicy,
        safety_policy: SafetyPolicy,
    ):
        if not callable(getattr(transport, "send_payload", None)):
            raise TypeError("Transport must implement send_payload(payload)")
        if not callable(getattr(transport, "receive_payload", None)):
            raise TypeError("Transport must implement receive_payload()")
        if not isinstance(capabilities, AdapterCapabilities):
            raise TypeError("capabilities must be AdapterCapabilities")
        if not isinstance(transmit_policy, TransmitPolicy):
            raise TypeError("transmit_policy must be TransmitPolicy")
        if not isinstance(safety_policy, SafetyPolicy):
            raise TypeError("safety_policy must be SafetyPolicy")
        self.transport = transport
        self.capabilities = capabilities
        self.transmit_policy = transmit_policy
        self.safety_policy = safety_policy

    @staticmethod
    def _validate_read_request(request):
        request = bytes(request)
        if not request:
            raise ValueError("UDS request cannot be empty")
        service = request[0]
        if service == 0x22:
            if len(request) < 3 or (len(request) - 1) % 2:
                raise ValueError("ReadDataByIdentifier request must contain one or more complete DIDs")
            dids = [
                int.from_bytes(request[index:index + 2], "big")
                for index in range(1, len(request), 2)
            ]
            if len(dids) > 32 or len(set(dids)) != len(dids):
                raise ValueError("Invalid or duplicate DID list")
            return request
        if service == 0x19:
            if len(request) == 3 and request[1] in (0x01, 0x02):
                return request
            if len(request) == 2 and request[1] == 0x0A:
                return request
            raise ValueError("Only UDS ReadDTCInformation subfunctions 01, 02, and 0A are allowed")
        raise ValueError(f"UDS service 0x{service:02X} is not allowed by the read-only client")

    def execute_read_request(self, request, *, confirmed=False, timeout=3.0, max_pending=8):
        """Execute one authorized read request and decode its final response.

        confirmed is an explicit operator confirmation for this transaction.
        NRC 0x78 response-pending is awaited within the same overall deadline,
        with a bounded number of pending responses.
        """
        request = self._validate_read_request(request)
        if timeout <= 0:
            raise ValueError("Transaction timeout must be positive")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 0:
            raise ValueError("max_pending must be a non-negative integer")

        if not self.transmit_policy.allows_uds_request(self.capabilities):
            raise UdsRequestDenied(
                "UDS request denied: adapter capability, implementation, and separate UDS permission are all required"
            )
        try:
            self.safety_policy.authorize_transmit(
                operation=f"read-only UDS service 0x{request[0]:02X}",
                confirmed=confirmed,
            )
        except PermissionError as exc:
            raise UdsRequestDenied(str(exc)) from exc

        deadline = time.monotonic() + float(timeout)
        self.transport.send_payload(request)
        pending_count = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UdsTransactionTimeout("UDS response deadline expired")
            try:
                response = self.transport.receive_payload()
            except IsoTpTimeout as exc:
                raise UdsTransactionTimeout("Timed out waiting for UDS response") from exc

            decoded = decode_uds_response(response, request=request)
            if decoded["kind"] != "negative" or not decoded["response_pending"]:
                return decoded

            pending_count += 1
            if pending_count > max_pending:
                raise UdsTransactionTimeout("Exceeded configured UDS response-pending limit")

    def read_data_by_identifier(self, dids, *, confirmed=False, timeout=3.0):
        request = build_read_data_by_identifier_request(dids)
        return self.execute_read_request(
            request, confirmed=confirmed, timeout=timeout
        )

    def read_dtcs(self, *, subfunction=0x02, status_mask=0xFF,
                  confirmed=False, timeout=3.0):
        request = build_read_dtc_information_request(
            subfunction=subfunction, status_mask=status_mask
        )
        return self.execute_read_request(
            request, confirmed=confirmed, timeout=timeout
        )
