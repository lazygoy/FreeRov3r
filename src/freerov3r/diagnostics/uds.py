"""Conservative, vehicle-independent UDS read-service codec.

This module builds and decodes application payloads only. It does not select
CAN identifiers, open adapters, transmit frames, change diagnostic sessions,
or authorize a physical request. Transport and authorization remain separate.
"""

from dataclasses import dataclass


READ_ONLY_SERVICES = frozenset({0x19, 0x22})
NEGATIVE_RESPONSE_CODES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


def _byte(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be an integer from 0x00 to 0xFF")
    return value


def _did(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError("DID values must be integers from 0x0000 to 0xFFFF")
    return value


def build_read_data_by_identifier_request(dids):
    """Build UDS 0x22 for one or more explicitly supplied DIDs."""
    values = tuple(_did(value) for value in dids)
    if not values:
        raise ValueError("At least one DID is required")
    if len(values) > 32:
        raise ValueError("A single request is limited to 32 DIDs")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate DIDs are not permitted")
    return bytes((0x22,)) + b"".join(value.to_bytes(2, "big") for value in values)


def build_read_dtc_information_request(subfunction=0x02, status_mask=0xFF):
    """Build the bounded UDS 0x19 read-DTC subfunctions 01, 02, or 0A."""
    subfunction = _byte(subfunction, "subfunction")
    if subfunction in (0x01, 0x02):
        return bytes((0x19, subfunction, _byte(status_mask, "status_mask")))
    if subfunction == 0x0A:
        return bytes((0x19, subfunction))
    raise ValueError(
        "Only UDS ReadDTCInformation subfunctions 0x01, 0x02, and 0x0A "
        "are enabled by this read-only codec"
    )


def _as_payload(response):
    if isinstance(response, str):
        try:
            return bytes.fromhex(response.replace(" ", "").replace(":", ""))
        except ValueError as exc:
            raise ValueError("Response must contain valid hexadecimal bytes") from exc
    try:
        return bytes(response)
    except (TypeError, ValueError) as exc:
        raise ValueError("Response must be bytes-like or a hexadecimal string") from exc


def decode_uds_response(response, *, request=None):
    """Decode a UDS positive/negative response without guessing ECU identity."""
    payload = _as_payload(response)
    if not payload:
        raise ValueError("Empty UDS response")

    request_payload = _as_payload(request) if request is not None else None
    request_sid = request_payload[0] if request_payload else None
    sid = payload[0]

    if sid == 0x7F:
        if len(payload) != 3:
            raise ValueError("Negative UDS response must contain exactly three bytes")
        original_sid, nrc = payload[1], payload[2]
        if request_sid is not None and original_sid != request_sid:
            raise ValueError("Negative response service does not match the request")
        return {
            "kind": "negative",
            "service": original_sid,
            "response_sid": sid,
            "nrc": nrc,
            "nrc_name": NEGATIVE_RESPONSE_CODES.get(nrc, "unknownNRC"),
            "response_pending": nrc == 0x78,
            "payload": payload.hex(),
        }

    if sid < 0x40:
        raise ValueError("Response SID is not a UDS positive-response service")
    service = sid - 0x40
    if request_sid is not None and service != request_sid:
        raise ValueError("Positive response service does not match the request")
    if service not in READ_ONLY_SERVICES:
        raise ValueError(f"Service 0x{service:02X} is not enabled in this read-only codec")

    result = {
        "kind": "positive",
        "service": service,
        "response_sid": sid,
        "payload": payload.hex(),
        "data": payload[1:].hex(),
    }

    if service == 0x22:
        if len(payload) < 3 or (len(payload) - 1) % 2 == 1:
            # A DID response needs at least one echoed two-byte DID.
            if len(payload) < 3:
                raise ValueError("ReadDataByIdentifier response is missing its DID")
        echoed_dids = []
        offset = 1
        requested_dids = []
        if request_payload is not None:
            if len(request_payload) < 3 or (len(request_payload) - 1) % 2:
                raise ValueError("Malformed ReadDataByIdentifier request")
            requested_dids = [
                int.from_bytes(request_payload[index:index + 2], "big")
                for index in range(1, len(request_payload), 2)
            ]
        # DID positions cannot be safely inferred for arbitrary multi-DID
        # responses without a DID length catalogue. For one requested DID,
        # the echoed DID and raw record boundary are unambiguous.
        if requested_dids:
            if len(payload) < 3:
                raise ValueError("ReadDataByIdentifier response is truncated")
            echoed = int.from_bytes(payload[1:3], "big")
            if echoed != requested_dids[0]:
                raise ValueError("Response DID does not match the requested DID")
            echoed_dids.append(echoed)
            if len(requested_dids) == 1:
                result["did"] = echoed
                result["record_data"] = payload[3:].hex()
            else:
                result["requested_dids"] = requested_dids
                result["raw_records"] = payload[1:].hex()
                result["record_boundaries"] = "unknown_without_did_length_definitions"
        else:
            result["raw_records"] = payload[1:].hex()
            result["record_boundaries"] = "unknown_without_did_length_definitions"

    elif service == 0x19:
        if len(payload) < 2:
            raise ValueError("ReadDTCInformation response is missing its subfunction")
        result["subfunction"] = payload[1] & 0x7F
        result["subfunction_echo"] = bool(payload[1] & 0x80)
        if request_payload is not None:
            if len(request_payload) < 2 or request_payload[0] != 0x19:
                raise ValueError("Malformed ReadDTCInformation request")
            if result["subfunction"] != request_payload[1]:
                raise ValueError("Response subfunction does not match the request")
        result["data"] = payload[2:].hex()
        if result["subfunction"] == 0x02:
            if len(payload) < 3:
                raise ValueError("DTC status availability mask is missing")
            availability = payload[2]
            records = payload[3:]
            if len(records) % 4:
                raise ValueError("DTC/status records must be four bytes each")
            result["dtc_status_availability_mask"] = availability
            result["dtcs"] = [
                {
                    "dtc": int.from_bytes(records[index:index + 3], "big"),
                    "status": records[index + 3],
                }
                for index in range(0, len(records), 4)
            ]
    return result
