"""Dash/DashBle source captures plus synthetic integration tests, not bike tests."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.honda_cbr600rr import HondaCB500FDashSession
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation

# Attributed source examples: atoid/Dash README, MIT. These both pass checksum.
TABLE11 = bytes.fromhex('02 19 71 11 06 a2 1c 00 b8 32 b7 33 72 4c ff ff 8b 00 04 35 98 5b 17 23 1e')
TABLED1 = bytes.fromhex('02 0b 71 d1 01 00 00 00 01 00 af')

class FakeConnection(Connection):
    def __init__(self, data=b''): self.data = bytearray(data); self.sent = []; self.closed = False
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): raise AssertionError('not a standard KWP frame')
    def read_bytes(self, size, timeout):
        result = self.data[:size]; del self.data[:size]; return bytes(result)
    def close(self): self.closed = True

class FakeTransport(Transport):
    name = 'kline'; is_physical = True; baud = 10400
    def __init__(self, data=b'', wake=bytes.fromhex('02 04 00 fa')):
        self.conn = FakeConnection(data); self.wake = wake; self.opened = False; self.args = None
    def open(self): self.opened = True; return self.conn
    def initialize(self, connection, **kwargs):
        self.args = kwargs
        return InitResult(True, 'honda-cb500f-dashble', baud=10400, protocol='honda-cbr600rr',
                          handshake_complete=True, response=self.wake)

def service(t):
    return DiagnosticsService(load_catalog().ecu('honda_cb500f_dashble'), t, SafetyGate(mode=Mode.READ_ONLY))

@pytest.fixture(autouse=True)
def disable_keepalive(monkeypatch):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)

def test_source_captures_with_correct_lengths_and_one_request_per_table():
    t = FakeTransport(TABLE11 + TABLED1); s = service(t); s.connect()
    assert t.args['method'] == 'honda-cb500f-dashble'
    samples = s.read_parameters(['rpm', 'tps_raw', 'coolant', 'airtemp', 'map', 'battery', 'speed', 'gear_status', 'engine_status'])
    assert [x.value for x in samples] == [1698, 0, 10, 11, 76, 13.9, 0, 1, 1]
    assert 'Neutral or clutch' in samples[-2].text
    assert samples[-1].text == ''  # engine status is a raw byte, not a binary inference
    assert t.conn.sent == [bytes.fromhex('72 05 71 11 07'), bytes.fromhex('72 05 71 d1 47')]
    assert s.gate.state.battery_v is None and not s.gate.state.engine_running
    s.disconnect(); assert t.conn.closed and len(t.conn.sent) == 2

@pytest.mark.parametrize('payload', [b'\x71\x10', b'\x71\x01', b'\x27', b'\x23', b'\x14'])
def test_unlisted_requests_blocked(payload):
    c = FakeConnection(); s = HondaCB500FDashSession(c)
    with pytest.raises(PermissionError): s.request(payload)
    assert not c.sent

def test_invalid_checksum_and_wrong_table_length_do_not_become_readings():
    t = FakeTransport(TABLE11[:-1] + b'\x00'); s = service(t); s.connect()
    assert s.read_parameters(['rpm'])[0].value is None
    t = FakeTransport(bytes.fromhex('02 0a 71 d1 00 00 00 00 00 b2')); s = service(t); s.connect()
    sample = s.read_parameters(['gear_status'])[0]
    assert sample.value is None and sample.error

def test_explicit_ecu_only_and_read_only(monkeypatch):
    ws = Workstation(record=False)
    ws.select(ecu='honda_cb500f_dashble', transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only'): ws.connect(mode='service')
    ws.select(ecu='honda_cb500f_dashble', transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
    t = FakeTransport(); s = service(t)
    with pytest.raises(TransportUnavailable): s.connect(init_method='fast')
    assert not t.opened
