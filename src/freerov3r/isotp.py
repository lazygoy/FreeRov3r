"""Passive ISO-TP reassembly for captured CAN traffic.

This module only interprets frames already present in a capture. It never
transmits Flow Control frames or interacts with a CAN adapter.
"""


def reassemble_isotp(frames, *, timeout=1.0, max_payload=1_048_576):
    """Reassemble ISO-TP Single and multi-frame messages.

    Args:
        frames: Iterable of dictionaries containing timestamp, arbitration_id,
            extended, data (hex string), and optional channel. Input order is
            capture order and is intentionally preserved.
        timeout: Maximum allowed gap, in seconds, between frames in a transfer.
        max_payload: Maximum accepted payload length in bytes.

    Returns:
        A list of message dictionaries. Single Frames and successfully
        reassembled First/Consecutive Frame transfers have status 'complete'.
        Transfers still pending at end-of-capture, or terminated by a sequence
        or timeout error, are returned as 'incomplete' with a diagnostic.
        Flow Control frames are transport metadata and are not returned as
        application messages.
    """
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    if max_payload < 1:
        raise ValueError("max_payload must be positive")

    pending = {}
    output = []

    def key_for(frame):
        return (
            int(frame["arbitration_id"]),
            bool(frame.get("extended", False)),
            frame.get("channel"),
        )

    def make_message(frame, payload, status, detail, frame_count, started_at=None, completed_at=None):
        stamp = float(frame.get("timestamp", 0.0) or 0.0)
        return {
            "arbitration_id": int(frame["arbitration_id"]),
            "extended": bool(frame.get("extended", False)),
            "channel": frame.get("channel"),
            "timestamp": stamp,
            "started_at": float(started_at if started_at is not None else stamp),
            "completed_at": float(completed_at if completed_at is not None else stamp),
            "payload": bytes(payload).hex(),
            "status": status,
            "detail": detail,
            "frame_count": frame_count,
        }

    for frame in frames:
        try:
            data = bytes.fromhex(str(frame.get("data", "")).replace(" ", ""))
            timestamp = float(frame.get("timestamp", 0.0) or 0.0)
            key = key_for(frame)
        except (TypeError, ValueError, KeyError):
            continue
        if not data:
            continue

        for expired_key, transfer in list(pending.items()):
            if timestamp - transfer["last_timestamp"] > timeout:
                output.append(make_message(
                    transfer["first_frame"], transfer["payload"], "incomplete",
                    "Timed out waiting for Consecutive Frame data",
                    transfer["frame_count"], transfer["started_at"], transfer["last_timestamp"],
                ))
                del pending[expired_key]

        pci_type = data[0] >> 4

        if pci_type == 0:
            if data[0] & 0x0F:
                length, offset = data[0] & 0x0F, 1
            elif len(data) >= 2:
                length, offset = data[1], 2
            else:
                output.append(make_message(
                    frame, b"", "incomplete", "Truncated Single Frame length", 1
                ))
                continue
            if length == 0 or offset + length > len(data):
                output.append(make_message(
                    frame, data[offset:], "incomplete",
                    "Single Frame payload is shorter than its declared length", 1
                ))
                continue
            if length > max_payload:
                output.append(make_message(
                    frame, data[offset:offset + length], "incomplete",
                    "Single Frame exceeds configured payload limit", 1
                ))
                continue
            output.append(make_message(
                frame, data[offset:offset + length], "complete", "Single Frame", 1
            ))

        elif pci_type == 1:
            if len(data) < 2:
                output.append(make_message(
                    frame, b"", "incomplete", "Truncated First Frame length", 1
                ))
                continue
            length = ((data[0] & 0x0F) << 8) | data[1]
            offset = 2
            if length == 0:
                if len(data) < 6:
                    output.append(make_message(
                        frame, b"", "incomplete",
                        "Truncated extended First Frame length", 1
                    ))
                    continue
                length = int.from_bytes(data[2:6], "big")
                offset = 6
            if length <= len(data) - offset:
                output.append(make_message(
                    frame, data[offset:offset + length], "incomplete",
                    "First Frame length does not require segmentation", 1
                ))
                continue
            if length > max_payload:
                output.append(make_message(
                    frame, data[offset:], "incomplete",
                    f"Declared payload length {length} exceeds limit {max_payload}", 1
                ))
                continue
            if key in pending:
                old = pending.pop(key)
                output.append(make_message(
                    old["first_frame"], old["payload"], "incomplete",
                    "Superseded by a new First Frame before transfer completed",
                    old["frame_count"], old["started_at"],
                ))
            pending[key] = {
                "first_frame": frame,
                "expected_length": length,
                "payload": bytearray(data[offset:]),
                "next_sequence": 1,
                "frame_count": 1,
                "started_at": timestamp,
                "last_timestamp": timestamp,
            }

        elif pci_type == 2:
            transfer = pending.get(key)
            if transfer is None:
                output.append(make_message(
                    frame, data[1:], "incomplete",
                    "Consecutive Frame received without a matching First Frame", 1
                ))
                continue
            sequence = data[0] & 0x0F
            if sequence != transfer["next_sequence"]:
                output.append(make_message(
                    transfer["first_frame"], transfer["payload"], "incomplete",
                    f"Sequence error: expected {transfer['next_sequence']:X}, got {sequence:X}",
                    transfer["frame_count"], transfer["started_at"], timestamp,
                ))
                del pending[key]
                continue
            transfer["payload"].extend(data[1:])
            transfer["frame_count"] += 1
            transfer["next_sequence"] = (sequence + 1) & 0x0F
            transfer["last_timestamp"] = timestamp
            if len(transfer["payload"]) >= transfer["expected_length"]:
                payload = transfer["payload"][:transfer["expected_length"]]
                output.append(make_message(
                    transfer["first_frame"], payload, "complete",
                    "Reassembled First Frame + Consecutive Frames",
                    transfer["frame_count"], transfer["started_at"], timestamp,
                ))
                del pending[key]

        elif pci_type == 3:
            # Flow Control is observed as transport metadata, never transmitted.
            continue

    for transfer in pending.values():
        output.append(make_message(
            transfer["first_frame"], transfer["payload"], "incomplete",
            "Capture ended before the declared payload was complete",
            transfer["frame_count"], transfer["started_at"], transfer["last_timestamp"],
        ))

    return sorted(output, key=lambda message: message["started_at"])



def pair_uds_transactions(messages, *, response_window=2.0):
    """Pair UDS requests with later responses using service semantics.

    Pairing is deliberately conservative: the response must use the matching
    positive-response SID (request SID + 0x40), or be a negative response
    (0x7F, original request SID), and must come from a different CAN ID on
    the same channel and CAN-ID format. This is a probable association, not
    proof of ECU identity or physical addressing.
    """
    if response_window < 0:
        raise ValueError("response_window must be non-negative")

    ordered = sorted(
        (dict(item) for item in messages if item.get("status") == "complete"),
        key=lambda item: item.get("started_at", item.get("timestamp", 0.0)),
    )
    pending = []
    results = []

    def payload_of(item):
        try:
            return bytes.fromhex(item.get("payload", ""))
        except (TypeError, ValueError):
            return b""

    for index, message in enumerate(ordered):
        payload = payload_of(message)
        if not payload:
            continue
        sid = payload[0]
        stamp = float(message.get("started_at", message.get("timestamp", 0.0)) or 0.0)

        # Expire old requests before considering this message.
        pending = [
            entry for entry in pending
            if stamp - entry["timestamp"] <= response_window
        ]

        if sid == 0x7F and len(payload) >= 3:
            request_sid = payload[1]
            response_kind = "negative"
        elif sid >= 0x40 and (sid - 0x40) in UDS_REQUEST_SERVICE_IDS:
            request_sid = sid - 0x40
            response_kind = "positive"
        else:
            request_sid = None
            response_kind = None

        match = None
        if request_sid is not None:
            candidates = [
                entry for entry in pending
                if entry["sid"] == request_sid
                and entry["can_id"] != message.get("arbitration_id")
                and entry["extended"] == bool(message.get("extended", False))
                and entry["channel"] == message.get("channel")
                and 0 <= stamp - entry["timestamp"] <= response_window
            ]
            if candidates:
                match = max(candidates, key=lambda entry: entry["timestamp"])

        if match is not None:
            pending.remove(match)
            request = match["message"]
            request_id = int(request["arbitration_id"])
            response_id = int(message["arbitration_id"])
            conventional_pair = (
                not bool(message.get("extended", False))
                and request_id <= 0x7FF and response_id <= 0x7FF
                and response_id == request_id + 8
            )
            results.append({
                "request": request,
                "response": message,
                "request_service": request_sid,
                "response_kind": response_kind,
                "latency_seconds": stamp - match["timestamp"],
                "addressing_hint": (
                    "Common 11-bit request/response ID offset (+0x8)"
                    if conventional_pair else
                    "Opposite CAN IDs; address relationship unverified"
                ),
                "confidence": "probable",
            })
        elif sid in range(0x10, 0x40) or sid in (0x3E, 0x85):
            pending.append({
                "sid": sid,
                "timestamp": stamp,
                "can_id": int(message.get("arbitration_id", -1)),
                "extended": bool(message.get("extended", False)),
                "channel": message.get("channel"),
                "message": message,
            })

    paired_response_ids = {id(pair["response"]) for pair in results}
    paired_request_ids = {id(pair["request"]) for pair in results}
    for message in ordered:
        if id(message) not in paired_response_ids and id(message) not in paired_request_ids:
            payload = payload_of(message)
            results.append({
                "request": message if payload and payload[0] in UDS_REQUEST_SERVICE_IDS else None,
                "response": message if payload and (
                    payload[0] == 0x7F or (
                        payload[0] >= 0x40
                        and payload[0] - 0x40 in UDS_REQUEST_SERVICE_IDS
                    )
                ) else None,
                "request_service": payload[0] if payload and payload[0] in UDS_REQUEST_SERVICE_IDS else None,
                "response_kind": None,
                "latency_seconds": None,
                "addressing_hint": "Unpaired; insufficient matching evidence",
                "confidence": "unmatched",
                "message": message,
            })
    return sorted(
        results,
        key=lambda item: min(
            (item.get("request") or item.get("message") or {}).get("started_at", 0.0),
            (item.get("response") or {}).get("started_at", float("inf")),
        ),
    )


UDS_REQUEST_SERVICE_IDS = {
    0x10, 0x11, 0x14, 0x19, 0x22, 0x23, 0x27, 0x28,
    0x2E, 0x2F, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3E, 0x85,
}
