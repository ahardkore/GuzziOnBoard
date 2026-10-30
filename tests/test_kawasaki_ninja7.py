"""Synthetic source vectors only: no physical ECU or bike validation."""
from types import SimpleNamespace

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kawasaki_ninja7 import KawasakiNinja7Session
from guzzionboard.protocol.kwp2000 import NegativeResponse, ProtocolError
from guzzionboard.protocol.isotp import segment
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.transports.can import CanConnection
from guzzionboard.workstation import Workstation


class FakeConnection(Connection):
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.sent = []
        self.closed = False
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeCAN(Transport):
    name = 'can'
    is_physical = True
    bitrate, tx_id, rx_id, padding = 500000, 0x764, 0x746, 0
    def __init__(self, replies=()):
        self.conn = FakeConnection(replies)
        self.opened = False
    def open(self):
        self.opened = True
        return self.conn
    def initialize(self, connection, **kwargs):
        return InitResult(True, 'can', protocol='isotp', handshake_complete=True)


def make_service(transport, mode=Mode.READ_ONLY):
    return DiagnosticsService(load_catalog().ecu('kawasaki_ninja7_hybrid'), transport, SafetyGate(mode=mode))


def test_source_scoped_live_identity_and_dtc(monkeypatch):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeCAN([b'\x50\x80', b'\x5aML5CXGA11RDA04358', b'\x61\x09\x3e\x80',
                 b'\x61\x06\x54', b'\x61\x76\x64', b'\x58\x00'])
    s = make_service(t); s.connect()
    assert s.identify().raw == b'ML5CXGA11RDA04358'
    samples = s.read_parameters(['rpm', 'coolant', 'battery'])
    assert [x.value for x in samples] == [4000, 44, 12.5]
    assert s.read_dtcs()['dtcs'] == []
    assert t.conn.sent == [b'\x10\x80', b'\x1a\x80', b'\x21\x09', b'\x21\x06', b'\x21\x76', b'\x18\x01']
    s.disconnect()
    assert t.conn.closed and t.conn.sent[-1] == b'\x18\x01'


def test_source_candidate_dtc_layout_and_bounds():
    s = KawasakiNinja7Session(FakeConnection([b'\x58\x00\x01\x01\x23\x20']))
    codes = s.read_stored_codes()
    assert codes[0]['code'] == 'P0123' and codes[0]['status_byte'] == 0x20
    assert codes[0]['warning_indicator'] is None
    for raw in (b'\x58', b'\x58\x00\x02\x01\x23\x20', b'\x58\x00\x01\x01'):
        with pytest.raises(ProtocolError):
            KawasakiNinja7Session(FakeConnection([raw])).read_stored_codes()


@pytest.mark.parametrize('reply', [b'', b'\x61\x09\x10', b'\x61\x06\x01\x02',
                                   b'\x61\x09\x12\x34', b'\x7f\x27\x33', b'\x7f\x21'])
def test_bad_sensor_reply_fails_closed(reply):
    with pytest.raises(ProtocolError):
        KawasakiNinja7Session(FakeConnection([reply])).read_data_by_local_id(6)


def test_unavailable_sensor_and_negative_response():
    with pytest.raises(ProtocolError, match='unavailable'):
        KawasakiNinja7Session(FakeConnection([b'\x61\x06\xff'])).read_data_by_local_id(6)
    with pytest.raises(NegativeResponse):
        KawasakiNinja7Session(FakeConnection([b'\x7f\x21\x31'])).read_data_by_local_id(6)


def test_read_only_requests_are_closed_even_if_guard_changes():
    conn = FakeConnection(); s = KawasakiNinja7Session(conn, write_guard=lambda _: True)
    for request in (b'\x10\x81', b'\x27\x07', b'\x14\xff\x00', b'\x21\xff', b'\x34', b'\x13\x01'):
        with pytest.raises(PermissionError): s.request(request)
    assert not conn.sent


def test_wrong_settings_do_not_open_transport():
    for attr, value in [('tx_id', 0x7e0), ('rx_id', 0x7e8), ('bitrate', 250000), ('padding', 0xaa)]:
        t = FakeCAN(); setattr(t, attr, value)
        with pytest.raises(TransportUnavailable): make_service(t).connect()
        assert not t.opened
    t = FakeCAN()
    with pytest.raises(TransportUnavailable): make_service(t, Mode.SERVICE).connect()
    assert not t.opened
    with pytest.raises(TransportUnavailable): make_service(t).connect(init_method='fast')
    assert not t.opened


def test_bad_handshake_closes_connection(monkeypatch):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    t = FakeCAN([b'\x50\x81'])
    with pytest.raises(ProtocolError): make_service(t).connect()
    assert t.conn.closed and t.conn.sent == [b'\x10\x80']


def test_workstation_requires_model_can_and_fixed_address():
    w = Workstation(record=False)
    w.select(ecu='kawasaki_ninja7_hybrid', transport='can')
    with pytest.raises(TransportUnavailable, match='vehicle selection'): w.connect(mode='read_only')
    w.select(make='Kawasaki', model='Ninja 7 Hybrid', year=2024, transport='can', can_tx_id='0x7e0')
    with pytest.raises(TransportUnavailable, match='source-scoped'): w.connect(mode='read_only')
    w.select(make='Kawasaki', model='Ninja 7 Hybrid', year=2024, transport='simulator')
    with pytest.raises(TransportUnavailable, match='read-only'): w.connect(mode='simulator')
    w.select(make='Kawasaki', model='Ninja 7 Hybrid', year=2024, transport='can')
    t = w._build_transport()
    assert (t.tx_id, t.rx_id, t.bitrate, t.padding) == (0x764, 0x746, 500000, 0)


def test_can_transport_uses_source_zero_padding_and_flow_control(monkeypatch):
    import guzzionboard.transports.can as mod
    monkeypatch.setattr(mod, '_require_can', lambda: SimpleNamespace(Message=lambda **k: SimpleNamespace(**k)))
    class Bus:
        def __init__(self): self.sent, self.messages = [], []
        def send(self, msg): self.sent.append(msg)
        def recv(self, timeout): return self.messages.pop(0) if self.messages else None
    bus = Bus(); conn = CanConnection(bus, tx_id=0x764, rx_id=0x746, padding=0, st_min=0)
    conn.write(b'\x10\x80')
    assert bus.sent[0].data == bytes.fromhex('02 10 80 00 00 00 00 00')
    raw = b'\x5a' + b'ABCDEFGHIJKLMNOP'
    bus.messages = [SimpleNamespace(arbitration_id=0x746, data=x) for x in segment(raw, padding=0)]
    assert conn.read_frame(1) == raw
    assert bus.sent[1].data == bytes.fromhex('30 00 00 00 00 00 00 00')


@pytest.mark.parametrize(('model', 'profile'), [
    ('Ninja ZX-6R (636)', 'kawasaki_zx6r_636_2024_2026'),
    ('Ninja 650 / EX650', 'kawasaki_ninja650_2023_2026'),
    ('Z650', 'kawasaki_z650_2023_2026'),
])
def test_2026_kawasaki_research_models_cannot_open_sessions(model, profile):
    w = Workstation(record=False)
    result = w.select(make='Kawasaki', model=model, year=2026, transport='can')
    assert result['ecu']['id'] == profile
    assert result['ecu']['effective_capabilities'] == []
    with pytest.raises(TransportUnavailable, match='no transport was constructed'):
        w.connect(mode='read_only')
    w.select(make='Kawasaki', model=model, year=2026, transport='simulator')
    with pytest.raises(TransportUnavailable, match='no matching simulator'):
        w.connect(mode='simulator')
