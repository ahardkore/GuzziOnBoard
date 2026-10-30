"""Synthetic wire tests only; no physical ECU was tested."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.aster_kline import Versys2012Session, Gsxr6002011Session
from guzzionboard.protocol.kwp2000 import ProtocolError, checksum, encode_request
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


def reply(source, *payload):
    body = bytes([0x80, 0xf1, source, len(payload), *payload])
    return body + bytes([checksum(body)])


class FakeConnection(Connection):
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeTransport(Transport):
    name = 'kline'
    is_physical = True
    baud = 10400
    def __init__(self, target, replies, wake=None):
        self.conn = FakeConnection(replies)
        self.wake = wake if wake is not None else reply(target, 0xc1, 0xea, 0x8f)
        self.args = None
        self.opened = False
    def open(self):
        self.opened = True
        return self.conn
    def initialize(self, connection, **kwargs):
        self.args = kwargs
        return InitResult(True, 'fast', baud=10400, protocol='iso14230',
                          handshake_complete=True, response=self.wake)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.aster_kline.time.sleep', lambda _: None)
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)


def service(name, transport):
    return DiagnosticsService(load_catalog().ecu(name), transport, SafetyGate(mode=Mode.READ_ONLY))


def test_versys_session_and_scaling():
    t = FakeTransport(0x11, [reply(0x11, 0x50, 0x80), reply(0x11, 0x61, 9, 30, 128),
                             reply(0x11, 0x61, 6, 144), reply(0x11, 0x61, 0x0c, 45, 1)])
    s = service('kawasaki_versys650_2012', t); s.connect()
    assert t.args['method'] == 'aster-versys-2012'
    samples = s.read_parameters(['rpm', 'coolant', 'speed'])
    assert [x.value for x in samples] == [3050, 60.0, 45]
    assert t.conn.sent == [bytes.fromhex('80 11 f1 02 10 80 14'),
                           bytes.fromhex('80 11 f1 02 21 09 ae'),
                           bytes.fromhex('80 11 f1 02 21 06 ab'),
                           bytes.fromhex('80 11 f1 02 21 0c b1')]
    assert not s.gate.state.engine_running
    s.disconnect()
    assert len(t.conn.sent) == 4 and t.conn.closed


def test_gsxr_single_snapshot_per_poll():
    data = bytearray(50); data[11:13] = bytes([120, 50]); data[15] = 144
    data[18] = 150; data[20] = 3
    t = FakeTransport(0x12, [reply(0x12, 0x61, 0x08, *data)])
    s = service('suzuki_gsxr600_2011', t); s.connect()
    assert t.args['method'] == 'aster-gsxr600-2011'
    samples = s.read_parameters(['rpm', 'coolant', 'gear', 'battery_raw'])
    assert [x.value for x in samples] == [1205.0, 60.0, 3, 150.0]
    assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    assert not s.gate.state.engine_running and s.gate.state.battery_v is None
    s.disconnect()
    assert len(t.conn.sent) == 1 and t.conn.closed


@pytest.mark.parametrize('cls', [Versys2012Session, Gsxr6002011Session])
@pytest.mark.parametrize('payload', [b'\x14\xff', b'\x27\x01', b'\x23\x00', b'\x34', b'\x21\xff'])
def test_request_allowlist(cls, payload):
    c = FakeConnection([]); s = cls(c)
    with pytest.raises(PermissionError): s.request(payload)
    assert c.sent == []


@pytest.mark.parametrize('bad', [reply(0x12, 0x61, 8, *([0] * 49)),
    reply(0x11, 0x61, 8, *([0] * 50)), reply(0x12, 0x61, 9, *([0] * 50)),
    encode_request([0x61, 8] + [0]*50, target=0xf1, source=0x12),
    reply(0x12, 0x61, 8, *([0] * 50))[:-1] + b'\x00'])
def test_bad_snapshot_is_not_measurement(bad):
    t = FakeTransport(0x12, [bad]); s = service('suzuki_gsxr600_2011', t); s.connect()
    samples = s.read_parameters(['rpm', 'gear'])
    assert all(item.value is None and item.error for item in samples)
    assert len(t.conn.sent) == 1


@pytest.mark.parametrize('profile,target', [('kawasaki_versys650_2012', 0x11), ('suzuki_gsxr600_2011', 0x12)])
def test_bad_wake_and_override_fail_closed(profile, target):
    t = FakeTransport(target, [], wake=reply(target, 0xc1, 0xea, 0x8e)); s = service(profile, t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and t.conn.sent == []
    t = FakeTransport(target, []); s = service(profile, t)
    with pytest.raises(TransportUnavailable): s.connect(init_method='auto')
    assert not t.opened


@pytest.mark.parametrize('make,model,year,profile', [('Kawasaki', 'Versys 650', 2012, 'kawasaki_versys650_2012'),
                                                      ('Suzuki', 'GSX-R600', 2011, 'suzuki_gsxr600_2011')])
def test_workstation_exact_vehicle_and_mode(make, model, year, profile):
    ws = Workstation(record=False)
    ws.select(ecu=profile, transport='kline')
    with pytest.raises(TransportUnavailable, match='exact tested'): ws.connect(mode='read_only')
    ws.select(make=make, model=model, year=year, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only'): ws.connect(mode='service')
    ws.select(make=make, model=model, year=year, transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
