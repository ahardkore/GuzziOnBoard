"""Synthetic generic KWP2000 (ISO 14230) K-Line tests; no claim of motorcycle compatibility."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.generic_kwp import GenericKwp2000Session
from guzzionboard.protocol.kwp2000 import (
    KWP2000Session, NegativeResponse, ProtocolError, encode_request,
)
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


def _response(payload):
    """Build an ECU->tester KWP2000 frame."""
    return encode_request(payload, target=0xF1, source=0x10)


class FakeConnection(Connection):
    def __init__(self, replies):
        self.replies, self.sent, self.closed = list(replies), [], False
    @property
    def is_open(self): return not self.closed
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeTransport(Transport):
    name, is_physical = 'kline', True
    baud = 10400
    def __init__(self, replies, protocol='iso14230', handshake=True):
        self.conn, self.protocol, self.handshake, self.opened = FakeConnection(replies), protocol, handshake, False
    def open(self): self.opened = True; return self.conn
    def initialize(self, connection, **kwargs):
        return InitResult(True, 'fast', protocol=self.protocol, handshake_complete=self.handshake)


def service(transport, mode=Mode.READ_ONLY):
    svc = DiagnosticsService(load_catalog().ecu('generic_kwp2000_kline'), transport, SafetyGate(mode=mode))
    # Keep the tester-present keep-alive thread out of these assertions.
    svc.profile.session["tester_present_interval"] = 3600.0
    return svc


def test_identify_and_stored_faults_with_only_readonly_services():
    t = FakeTransport([_response([0x5A, 0x80, 0x41, 0x42, 0x43]),            # 1A 80 identification
                       _response([0x58, 0x01, 0x01, 0x22, 0x41])])          # 18 00 FF 00, one DTC
    s = service(t); s.connect()
    assert isinstance(s.session, GenericKwp2000Session)
    ident = s.identify()
    assert ident.raw == b'ABC'
    assert [d['code'] for d in s.read_dtcs()['dtcs']] == ['P0122']
    sent_payloads = [bytes(f[3:-1]) for f in t.conn.sent]
    assert sent_payloads == [b'\x1a\x80', b'\x18\x00\xff\x00']
    s.disconnect()
    assert t.conn.closed


def test_every_mutating_service_is_refused_before_transmission():
    t = FakeTransport([_response([0x7E])])                                   # tester-present positive
    s = service(t); s.connect()
    before = t.conn.sent[:]
    for payload in ([0x11, 0x01], [0x14, 0xFF, 0x00], [0x23, 0, 0, 0, 1], [0x27, 0x01],
                    [0x30, 0x01, 0x07], [0x31, 0x01], [0x3B, 0x01, 0x00], [0x3D, 0, 0, 0, 1],
                    [0x34, 0], [0x36, 0x01], [0x99]):
        with pytest.raises(PermissionError): s.session.request(payload)
    # read-only services stay allowed
    s.session.request([0x3E])
    assert t.conn.sent[:len(before)] == before
    s.disconnect()


def test_negative_response_raises_with_the_decoded_reason():
    conn = FakeConnection([_response([0x7F, 0x21, 0x12])])
    with pytest.raises(NegativeResponse):
        KWP2000Session(connection=conn, write_guard=lambda _: False).request([0x21, 0x30])


def test_local_id_echo_is_verified():
    conn = FakeConnection([_response([0x61, 0x31, 0x04])])
    with pytest.raises(ProtocolError):
        KWP2000Session(connection=conn, write_guard=lambda _: False).read_data_by_local_id(0x30)


@pytest.mark.parametrize('change', [dict(baud=9600), dict(is_physical=False)])
def test_invalid_transport_refused_before_open(change):
    t = FakeTransport([])
    for key, value in change.items(): setattr(t, key, value)
    with pytest.raises(TransportUnavailable): service(t).connect()
    assert not t.opened


@pytest.mark.parametrize('init_method', ['legacy', 'honda-cbr600rr-2005', 'generic-obd-iso9141-kline'])
def test_non_kwp_init_methods_refused(init_method):
    t = FakeTransport([])
    with pytest.raises(TransportUnavailable): service(t).connect(init_method=init_method)
    assert not t.opened


def test_non_iso14230_handshake_refused():
    t = FakeTransport([], protocol='iso9141-2')
    with pytest.raises(ProtocolError): service(t).connect()
    assert t.conn.closed and not service(t).connected


def test_profile_only_mode_and_selection_boundaries():
    t = FakeTransport([])
    with pytest.raises(TransportUnavailable): service(t, Mode.SERVICE).connect()
    assert not t.opened
    ws = Workstation(record=False)
    ws.select(ecu='generic_kwp2000_kline', transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
    ws.select(ecu='generic_kwp2000_kline', transport='kline')
    with pytest.raises(TransportUnavailable): ws.connect(mode='read_only')
