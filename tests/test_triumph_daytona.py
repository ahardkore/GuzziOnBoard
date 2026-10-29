"""Synthetic protocol regression tests; these do not validate real hardware."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.protocol.triumph_daytona import TriumphDaytonaSession, parse_iso_burst
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.transports.kline import KLineTransport
from guzzionboard.workstation import Workstation


def iso(*payload):
    body = bytes([0x48, 0x6b, 0xd1, *payload])
    return body + bytes([sum(body) & 255])


class FakeConnection(Connection):
    def __init__(self, replies): self.replies, self.sent, self.closed = list(replies), [], False
    def write(self, raw): self.sent.append(bytes(raw))
    def read_frame(self, timeout): raise AssertionError('ISO frames have no KWP length byte')
    def read_iso9141_burst(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeTransport(Transport):
    name, is_physical = 'kline', True
    def __init__(self, replies, keys=(8, 8)):
        self.conn, self.keys, self.opened = FakeConnection(replies), keys, False
    def open(self): self.opened = True; return self.conn
    def initialize(self, connection, **kw):
        assert kw['method'] == 'triumph-daytona-2012'
        return InitResult(True, 'slow', protocol='iso9141-2', key_bytes=self.keys, handshake_complete=True)


def service(t):
    return DiagnosticsService(load_catalog().ecu('triumph_daytona_675_2012'), t, SafetyGate(mode=Mode.READ_ONLY))


def test_obd_live_and_multiframe_stored_faults(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.triumph_daytona.time.sleep', lambda _: None)
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeTransport([iso(0x41, 0, 0xff, 0xff, 0xff, 0xff),
                       iso(0x41, 12, 0x3e, 0x80), iso(0x41, 5, 90),
                       iso(0x43, 0x01, 0x22, 0, 0, 0, 0) + iso(0x43, 0x41, 0x11, 0, 0, 0, 0)])
    s = service(t); s.connect()
    assert t.conn.sent[0] == bytes.fromhex('68 6A F1 01 00 C4')
    samples = s.read_parameters(['rpm', 'coolant'])
    assert [(x.key, x.value, x.raw) for x in samples] == [('rpm', 4000, b'\x3e\x80'), ('coolant', 50, b'\x5a')]
    result = s.read_dtcs()
    assert [d['code'] for d in result['dtcs']] == ['P0122', 'C0111']
    assert result['dtcs'][0]['status_byte'] is None
    assert 'pending' in result['note']
    assert t.conn.sent[-1] == bytes.fromhex('68 6a f1 03 c6')
    before = t.conn.sent[:]
    for request in ([4], [0x21, 0], [0x27, 1], [1, 0x42]):
        with pytest.raises(PermissionError): s.session.request(request)
    s.disconnect()
    assert t.conn.sent == before and t.conn.closed


def test_bitmap_refusal_sends_nothing(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.triumph_daytona.time.sleep', lambda _: None)
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeTransport([iso(0x41, 0, 0, 0, 0, 0)]); s = service(t); s.connect()
    sample = s.read_parameters(['rpm'])[0]
    assert sample.value is None and 'support bitmap' in sample.error
    assert len(t.conn.sent) == 1
    s.disconnect()


@pytest.mark.parametrize('bad', [iso(0x41, 0, 0, 0, 0, 0)[:-1] + b'\x00',
                                 iso(0x41, 1, 0, 0, 0, 0), b'\x48\x6b'])
def test_bad_bitmap_closes_port(monkeypatch, bad):
    monkeypatch.setattr('guzzionboard.protocol.triumph_daytona.time.sleep', lambda _: None)
    t = FakeTransport([bad]); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and not s.connected


def test_burst_rejects_partial_codes_and_mismatched_headers(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.triumph_daytona.time.sleep', lambda _: None)
    with pytest.raises(ProtocolError): parse_iso_burst(iso(0x43, 1, 2) + b'\x48\x6b')
    with pytest.raises(ProtocolError): parse_iso_burst(b'\x00' + iso(0x43, 1, 2))
    session = TriumphDaytonaSession(FakeConnection([iso(0x43, 1)]))
    with pytest.raises(ProtocolError, match='partial code'): session.read_stored_codes()


def test_profile_and_transport_guards():
    ws = Workstation(record=False)
    ws.select(ecu='triumph_daytona_675_2012', transport='kline')
    with pytest.raises(TransportUnavailable, match='exact Triumph'): ws.connect(mode='read_only')
    ws.select(make='Triumph', model='Daytona 675', year=2012, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only mode'): ws.connect(mode='service')
    ws.select(make='Triumph', model='Daytona 675', year=2012, transport='simulator')
    with pytest.raises(TransportUnavailable, match='no simulator'): ws.connect()


def test_slow_init_retries_only_exact_protocol(monkeypatch):
    attempts = []
    def slow(self, conn, addr, **kw):
        attempts.append((addr, kw))
        return InitResult(len(attempts) == 2, 'slow', protocol='iso9141-2', key_bytes=(8, 8), handshake_complete=True, detail='synthetic')
    monkeypatch.setattr(KLineTransport, '_slow_init', slow)
    result = KLineTransport().initialize(FakeConnection([]), method='triumph-daytona-2012')
    assert result.ok and len(result.attempts) == 2
    assert [x[1]['idle'] for x in attempts] == [3.0, 6.0]
    assert all(x[0] == 0x33 and x[1]['bit_time'] == .196 and x[1]['allow_iso9141'] for x in attempts)
