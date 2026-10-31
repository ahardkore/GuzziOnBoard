"""Synthetic ISO-TP flow-control and malformed-input tests, not motorcycle tests."""
from types import SimpleNamespace
import pytest

import guzzionboard.transports.can as transport
from guzzionboard.protocol.isotp import IsoTpError, Reassembler, segment
from guzzionboard.transports.base import TransportError


class Bus:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.events = []
    def send(self, msg):
        self.sent.append(bytes(msg.data)); self.events.append('send')
    def recv(self, timeout):
        self.events.append('recv')
        return self.replies.pop(0) if self.replies else None


def frame(*data, ident=0x7e8, **kwargs):
    return SimpleNamespace(arbitration_id=ident, data=bytes(data), **kwargs)


@pytest.fixture(autouse=True)
def fake_can(monkeypatch):
    monkeypatch.setattr(transport, '_require_can', lambda: SimpleNamespace(Message=lambda **kwargs: SimpleNamespace(**kwargs)))


def connection(bus):
    return transport.CanConnection(bus, tx_id=0x7e0, rx_id=0x7e8, st_min=0, padding=0)


def test_sender_obeys_each_block_size_and_updated_timing(monkeypatch):
    bus = Bus([frame(0x31,0,0),frame(0x30,2,0xf3),frame(0x30,1,0x05),frame(0x30,0,0)])
    delays = []
    monkeypatch.setattr(transport.time, 'sleep', lambda value: delays.append(value))
    c = connection(bus)
    c.write(bytes(range(40)))  # FF, five CF; then block size 2, 1, unrestricted
    assert [packet[0] for packet in bus.sent] == [0x10,0x21,0x22,0x23,0x24,0x25]
    assert bus.events == ['send','recv','recv','send','send','recv','send','recv','send','send']
    assert delays == [0.0003,0.0003,0.005]


@pytest.mark.parametrize('st, expected', [(0x00,0),(0x7f,0.127),(0xf1,0.0001),(0xf9,0.0009),
                                          (0x80,0.127),(0xf0,0.127),(0xfa,0.127),(0xff,0.127)])
def test_separation_time_decoding(st, expected):
    assert connection(Bus([frame(0x30,3,st)]))._await_flow_control() == (3, expected)


@pytest.mark.parametrize('data, message', [(b'\x30', 'malformed'),(b'\x30\x00','malformed'),
                                            (b'\x33\x00\x00','invalid'),(b'\x32\x00\x00','overflow')])
def test_bad_flow_control_fails_before_any_consecutive_frames(data, message):
    bus = Bus([frame(*data)])
    with pytest.raises(TransportError, match=message): connection(bus).write(bytes(range(25)))
    assert len(bus.sent) == 1 and bus.sent[0][0] == 0x10


def test_wait_flood_and_timeout_are_bounded():
    bus = Bus([frame(0x31,0,0)] * 9)
    with pytest.raises(TransportError, match='too many'): connection(bus).write(bytes(range(20)))
    assert len(bus.sent) == 1
    with pytest.raises(TransportError, match='timed out'):
        connection(Bus([]))._await_flow_control(timeout=0.001)


def test_irrelevant_wrong_format_and_fd_flow_controls_are_ignored():
    bus = Bus([frame(0x30,0,0,ident=0x123), frame(0x30,0,0,is_extended_id=True),
               frame(0x30,0,0,is_fd=True), frame(0x30,0,0,is_rx=False), frame(0x30,0,0,is_remote_frame=True),
               frame(0x30,0,0,is_error_frame=True), frame(0x30,0,0)])
    assert connection(bus)._await_flow_control() == (0,0)
    assert bus.events == ['recv'] * 7


@pytest.mark.parametrize('bad', [b'\x10',b'\x10\x08',b'\x10\x07'+bytes(6),
                                 b'\x10\x00'+bytes(6), b'\x10\x09'+bytes(7)])
def test_bad_first_frames_never_generate_flow_control(bad):
    rx = Reassembler()
    with pytest.raises(IsoTpError): rx.feed(bad)
    assert not rx.active


def test_truncated_or_interleaved_transfers_reset_state():
    first = segment(bytes(range(25)))[0]
    for bad in (b'\x21', b'\x21\x00', b'\x01\x7e', first):
        rx = Reassembler(); rx.feed(first)
        with pytest.raises(IsoTpError): rx.feed(bad)
        assert not rx.active


def test_short_last_frame_is_valid_when_complete():
    rx = Reassembler(); payload=bytes(range(9)); parts=segment(payload)
    rx.feed(parts[0]); result, reply = rx.feed(parts[1][:4])
    assert result == payload and reply is None


def test_invalid_response_raises_transport_error_and_sends_no_flow_control():
    bus=Bus([frame(0x10,0x07,0,0,0,0,0,0)])
    with pytest.raises(TransportError, match='invalid ISO-TP response'):
        connection(bus).read_frame(0.1)
    assert bus.sent == []


def test_empty_payload_refused_before_send():
    bus = Bus([])
    with pytest.raises(TransportError, match='empty payload'): connection(bus).write(b'')
    assert bus.sent == []
