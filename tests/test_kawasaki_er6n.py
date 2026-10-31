"""Synthetic tests for the author-reported iKawa wire sequence; not bike tests."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kawasaki_er6n import KawasakiER6nSession, decode_kawasaki_value
from guzzionboard.protocol.kwp2000 import ProtocolError, encode_request
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


def response(*payload, source=0x11, target=0xf1):
    return encode_request(payload, target=target, source=source)


class FakeConnection(Connection):
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False
    def write(self, data):
        self.sent.append(bytes(data))
    def read_frame(self, timeout):
        return self.replies.pop(0) if self.replies else b''
    def close(self):
        self.closed = True


class FakeKLine(Transport):
    is_physical = True
    name = 'kline'
    def __init__(self, replies, wake=None):
        self.conn = FakeConnection(replies)
        self.wake = wake or response(0xc1, 0xea, 0x8f)
        self.opened = False
        self.args = None
    def open(self):
        self.opened = True
        return self.conn
    def initialize(self, connection, **kwargs):
        self.args = kwargs
        return InitResult(True, 'fast', baud=10250, protocol='iso14230',
                          handshake_complete=True, response=self.wake)


def service(transport):
    return DiagnosticsService(load_catalog().ecu('kawasaki_er6n_2006'), transport,
                              SafetyGate(mode=Mode.READ_ONLY))


def test_exact_source_requests_and_values(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.kawasaki_er6n.time.sleep', lambda _: None)
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeKLine([response(0x50, 0x80), response(0x61, 9, 40, 2),
                   response(0x61, 6, 0x90), response(0x61, 10, 153)])
    s = service(t)
    s.connect()
    assert t.args['method'] == 'kawasaki-er6n'
    assert t.conn.sent[0] == bytes.fromhex('80 11 f1 02 10 80 14')
    samples = s.read_parameters(['rpm', 'coolant', 'battery'])
    assert [(x.key, x.value, x.raw) for x in samples] == [
        ('rpm', 4002, b'\x28\x02'), ('coolant', 60.0, b'\x90'), ('battery', 12.0, b'\x99')]
    assert t.conn.sent[1] == bytes.fromhex('80 11 f1 02 21 09 ae')
    before = list(t.conn.sent)
    with pytest.raises(PermissionError): s.session.request([0x14, 0xff, 0])
    with pytest.raises(PermissionError): s.session.request([0x21, 0x45])
    s.disconnect()
    assert t.conn.sent == before  # no unverified stop/clear/actuation commands
    assert t.conn.closed


@pytest.mark.parametrize('bad', [response(0x50, 0x81), response(0x50, 0x80, source=0x10), b'\x00'])
def test_failed_session_start_closes_port(monkeypatch, bad):
    monkeypatch.setattr('guzzionboard.protocol.kawasaki_er6n.time.sleep', lambda _: None)
    t = FakeKLine([bad]); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and not s.connected


def test_incorrect_wake_and_init_override_fail_closed(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.kawasaki_er6n.time.sleep', lambda _: None)
    t = FakeKLine([], wake=response(0xc1, 0xea, 0x8e)); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and t.conn.sent == []
    t = FakeKLine([]); s = service(t)
    with pytest.raises(TransportUnavailable): s.connect(init_method='auto')
    assert not t.opened


@pytest.mark.parametrize('reply', [response(0x61, 8, 40, 2), response(0x61, 9, 40),
                                  response(0x61, 9, 40, 2, source=0x10),
                                  response(0x61, 9, 40, 2)[:-1] + b'\x00'])
def test_bad_data_cannot_become_measurement(monkeypatch, reply):
    monkeypatch.setattr('guzzionboard.protocol.kawasaki_er6n.time.sleep', lambda _: None)
    session = KawasakiER6nSession(FakeConnection([reply]))
    with pytest.raises(ProtocolError): session.read_data_by_local_id(9)


def test_conversion_and_scoped_connection_gate():
    assert decode_kawasaki_value(12, bytes([1, 50])) == 75
    assert decode_kawasaki_value(5, bytes([1, 20])) == 60
    assert decode_kawasaki_value(8, b'\x05') == 2
    with pytest.raises(ProtocolError): decode_kawasaki_value(9, b'\x01')
    ws = Workstation(record=False)
    ws.select(ecu='kawasaki_er6n_2006', transport='kline')
    with pytest.raises(TransportUnavailable, match='exact Kawasaki'): ws.connect(mode='read_only')
    ws.select(make='Kawasaki', model='ER-6n', year=2006, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only mode'): ws.connect(mode='service')
    ws.select(make='Kawasaki', model='ER-6n', year=2006, transport='simulator')
    with pytest.raises(TransportUnavailable, match='no simulator'): ws.connect()


def test_transport_exception_closes_connection():
    class FailedInit(FakeKLine):
        def initialize(self, connection, **kwargs):
            raise RuntimeError('adapter disconnected')
    t = FailedInit([])
    with pytest.raises(RuntimeError, match='adapter disconnected'):
        service(t).connect()
    assert t.conn.closed


def test_new_ikawa_candidates_synthetic(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.kawasaki_er6n.time.sleep', lambda _: None)
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeKLine([response(0x50, 0x80), response(0x61, 4, 0x03, 0x5c),
                   response(0x61, 2, 2), response(0x61, 0x44, 0, 0, 0x0e, 0x74)])
    s = service(t); s.connect()
    samples = s.read_parameters(['throttle_candidate', 'starter_switch_candidate', 'elapsed_counter_candidate'])
    assert [x.value for x in samples] == [101, 1, 1.02]
    assert t.conn.sent[1:] == [bytes.fromhex('80 11 f1 02 21 04 a9'),
                               bytes.fromhex('80 11 f1 02 21 02 a7'),
                               bytes.fromhex('80 11 f1 02 21 44 e9')]
    assert decode_kawasaki_value(4, b'\x00\x00') == -33
    assert decode_kawasaki_value(0x44, b'\xff\xff\xff\xff') == (0xffffffff // 60) / 60
    with pytest.raises(ProtocolError): decode_kawasaki_value(0x44, b'\x00')
    s.disconnect()
