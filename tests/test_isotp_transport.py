import queue
import threading

import pytest

from freerov3r.isotp_transport import (
    IsoTpProtocolError,
    IsoTpTimeout,
    IsoTpTransport,
)
from freerov3r.models import CanFrame


def endpoint(tx_queue, rx_queue, *, tx_id, rx_id, sent=None, **kwargs):
    def send(frame):
        tx_queue.put(frame)
        if sent is not None:
            sent.append(frame)

    def receive(timeout):
        try:
            return rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    return IsoTpTransport(
        send,
        receive,
        lambda frame: True,
        tx_id=tx_id,
        rx_id=rx_id,
        timeout=0.3,
        **kwargs,
    )


def test_single_frame_round_trip():
    a_to_b, b_to_a = queue.Queue(), queue.Queue()
    sent = []
    sender = endpoint(a_to_b, b_to_a, tx_id=0x7E0, rx_id=0x7E8, sent=sent)
    receiver = endpoint(b_to_a, a_to_b, tx_id=0x7E8, rx_id=0x7E0)
    payload = bytes.fromhex("22 F1 90")

    sender.send_payload(payload)
    assert receiver.receive_payload() == payload
    assert sent[0].data == bytes.fromhex("03 22 F1 90")


def test_multi_frame_round_trip_with_flow_control():
    a_to_b, b_to_a = queue.Queue(), queue.Queue()
    sender = endpoint(a_to_b, b_to_a, tx_id=0x7E0, rx_id=0x7E8)
    receiver = endpoint(b_to_a, a_to_b, tx_id=0x7E8, rx_id=0x7E0)
    payload = bytes(range(1, 25))
    received = {}

    def receive():
        try:
            received["payload"] = receiver.receive_payload()
        except Exception as exc:
            received["error"] = exc

    worker = threading.Thread(target=receive)
    worker.start()
    stats = sender.send_payload(payload)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert "error" not in received
    assert received["payload"] == payload
    assert stats == {"payload_bytes": len(payload), "frames_sent": 4}


def test_multi_frame_obeys_receiver_block_size():
    a_to_b, b_to_a = queue.Queue(), queue.Queue()
    sender = endpoint(a_to_b, b_to_a, tx_id=0x7E0, rx_id=0x7E8)
    flow_controls_sent = []
    receiver = endpoint(
        b_to_a, a_to_b, tx_id=0x7E8, rx_id=0x7E0, block_size=1,
        sent=flow_controls_sent,
    )
    payload = bytes(range(1, 22))
    received = {}
    worker = threading.Thread(target=lambda: received.setdefault("payload", receiver.receive_payload()))
    worker.start()
    sender.send_payload(payload)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert received["payload"] == payload
    flow_controls = [
        frame for frame in flow_controls_sent
        if frame.data and frame.data[0] >> 4 == 3
    ]
    assert len(flow_controls) >= 2


def test_transmission_requires_explicit_authorization_for_every_frame():
    sent = []
    transport = IsoTpTransport(
        sent.append,
        lambda timeout: None,
        lambda frame: False,
        tx_id=0x7E0,
        rx_id=0x7E8,
    )
    with pytest.raises(PermissionError, match="denied"):
        transport.send_payload(b"\x22\xf1\x90")
    assert sent == []


def test_authorization_callback_is_mandatory():
    with pytest.raises(TypeError, match="authorization"):
        IsoTpTransport(
            lambda frame: None,
            lambda timeout: None,
            None,
            tx_id=0x7E0,
            rx_id=0x7E8,
        )


@pytest.mark.parametrize("st_min", [0x80, 0xF0, 0xFA, 0xFF])
def test_reserved_st_min_values_are_rejected(st_min):
    with pytest.raises(ValueError, match="STmin"):
        IsoTpTransport(
            lambda frame: None,
            lambda timeout: None,
            lambda frame: True,
            tx_id=0x7E0,
            rx_id=0x7E8,
            st_min=st_min,
        )


def test_invalid_flow_control_status_is_rejected():
    incoming = queue.Queue()
    incoming.put(CanFrame(0x7E8, bytes.fromhex("32 00 00")))
    transport = IsoTpTransport(
        lambda frame: None,
        lambda timeout: incoming.get_nowait() if not incoming.empty() else None,
        lambda frame: True,
        tx_id=0x7E0,
        rx_id=0x7E8,
        timeout=0.02,
    )
    with pytest.raises(IsoTpProtocolError, match="OVERFLOW"):
        transport._wait_flow_control()


def test_consecutive_frame_without_matching_first_frame_is_not_accepted():
    incoming = queue.Queue()
    incoming.put(CanFrame(0x7E8, bytes.fromhex("21 01 02 03")))
    transport = IsoTpTransport(
        lambda frame: None,
        lambda timeout: incoming.get_nowait() if not incoming.empty() else None,
        lambda frame: True,
        tx_id=0x7E0,
        rx_id=0x7E8,
        timeout=0.02,
    )
    with pytest.raises(IsoTpProtocolError, match="Single Frame or First Frame"):
        transport.receive_payload()


def test_segmented_receive_uses_one_overall_timeout_deadline():
    incoming = [
        CanFrame(0x7E8, bytes.fromhex("10 0A 01 02 03 04 05 06")),
    ]
    requested_timeouts = []

    def receive(timeout):
        requested_timeouts.append(timeout)
        if incoming:
            return incoming.pop(0)
        return None

    transport = IsoTpTransport(
        lambda frame: None,
        receive,
        lambda frame: True,
        tx_id=0x7E0,
        rx_id=0x7E8,
        timeout=0.5,
    )

    with pytest.raises(IsoTpTimeout):
        transport.receive_payload(timeout=0.02)

    assert len(requested_timeouts) == 2
    assert 0 < requested_timeouts[1] <= requested_timeouts[0] <= 0.02


def test_flow_control_wait_frames_share_one_deadline():
    incoming = [
        CanFrame(0x7E8, bytes.fromhex("31 00 00")),
        CanFrame(0x7E8, bytes.fromhex("30 00 00")),
    ]
    requested_timeouts = []

    def receive(timeout):
        requested_timeouts.append(timeout)
        return incoming.pop(0)

    transport = IsoTpTransport(
        lambda frame: None,
        receive,
        lambda frame: True,
        tx_id=0x7E0,
        rx_id=0x7E8,
        timeout=0.5,
    )

    assert transport._wait_flow_control(timeout=0.25) == (0, 0.0)
    assert len(requested_timeouts) == 2
    assert 0 < requested_timeouts[1] <= requested_timeouts[0] <= 0.25


def test_segmented_send_does_not_violate_stmin_when_deadline_is_short():
    incoming = [CanFrame(0x7E8, bytes.fromhex("30 00 01"))]
    sent = []

    transport = IsoTpTransport(
        sent.append,
        lambda timeout: incoming.pop(0) if incoming else None,
        lambda frame: True,
        tx_id=0x7E0,
        rx_id=0x7E8,
        timeout=0.5,
    )

    with pytest.raises(IsoTpTimeout, match="STmin delay"):
        transport.send_payload(bytes(range(1, 11)), timeout=0.0005)

    assert len(sent) == 1
    assert sent[0].data[0] >> 4 == 1
