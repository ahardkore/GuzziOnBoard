"""Synthetic frames and transport only; no real Honda has been tested."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.honda_cbr600rr import HondaCBR600RRSession
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


def frame(*body):
    return bytes([*body, (-sum(body)) & 255])


class FakeConnection(Connection):
    def __init__(self, data=b''):
        self.data = bytearray(data); self.sent = []; self.closed = False
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): raise AssertionError('Honda is not generic KWP')
    def read_bytes(self, size, timeout):
        result = self.data[:size]; del self.data[:size]; return bytes(result)
    def close(self): self.closed = True


class FakeHonda(Transport):
    name = 'kline'; is_physical = True; baud = 10400
    def __init__(self, data=b'', wake=bytes.fromhex('02 04 00 fa')):
        self.conn = FakeConnection(data); self.wake = wake; self.opened = False; self.args = None
    def open(self): self.opened = True; return self.conn
    def initialize(self, connection, **kw):
        self.args = kw
        return InitResult(True, 'honda-cbr600rr-2005', baud=10400, protocol='honda-cbr600rr',
                          handshake_complete=True, response=self.wake)


def service(t):
    return DiagnosticsService(load_catalog().ecu('honda_cbr600rr_2005'), t,
                              SafetyGate(mode=Mode.READ_ONLY))


@pytest.fixture(autouse=True)
def disable_keepalive(monkeypatch):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)


def test_single_table_poll_and_measurements():
    # Full 22-byte synthetic frame: table data positions use source offsets.
    data = [0] * 17
    data[0:2] = [0x27, 0x10]; data[3] = 80; data[5] = 100
    data[7] = 60; data[9] = 98; data[12] = 125; data[13] = 42
    t = FakeHonda(frame(2, 22, 0x71, 0x10, *data)); s = service(t); s.connect()
    assert t.args['method'] == 'honda-cbr600rr-2005'
    samples = s.read_parameters(['rpm', 'tps', 'coolant', 'airtemp', 'map', 'battery', 'speed'])
    assert [x.value for x in samples] == [10000, 50.0, 60.0, 20.0, 98.0, 12.5, 42]
    assert {x.local_id for x in samples} == {0x10}
    assert t.conn.sent == [bytes.fromhex('72 05 71 10 08')]
    assert s.gate.state.battery_v is None and not s.gate.state.engine_running
    s.disconnect(); assert t.conn.closed and len(t.conn.sent) == 1


@pytest.mark.parametrize('payload', [b'', b'\x71\x11', b'\x71\x01', b'\x27\x01', b'\x23\x00', b'\x14', b'\x72\x05\x71\x10\x08'])
def test_allowlist(payload):
    c = FakeConnection(); s = HondaCBR600RRSession(c)
    with pytest.raises(PermissionError): s.request(payload)
    assert c.sent == []


@pytest.mark.parametrize('data', [b'', b'\x02', b'\x02\x03\x00', b'\x02\xff',
    frame(2, 5, 0x71, 0x10), frame(2, 22, 0x71, 0x11, *([0]*17)),
    frame(3, 22, 0x71, 0x10, *([0]*17)),
    frame(2, 22, 0x71, 0x10, *([0]*17))[:-1] + b'\x00'])
def test_bad_frames_produce_no_samples(data):
    t = FakeHonda(data); s = service(t); s.connect()
    samples = s.read_parameters(['rpm', 'speed'])
    assert all(item.value is None and item.error for item in samples)
    assert len(t.conn.sent) == 1


def test_bad_handshake_and_override_fail_closed():
    t = FakeHonda(wake=b'bad!'); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and not t.conn.sent
    t = FakeHonda(); s = service(t)
    with pytest.raises(TransportUnavailable): s.connect(init_method='fast')
    assert not t.opened


def test_exact_vehicle_and_mode():
    ws = Workstation(record=False)
    ws.select(ecu='honda_cbr600rr_2005', transport='kline')
    with pytest.raises(TransportUnavailable, match='exact Honda'): ws.connect(mode='read_only')
    ws.select(make='Honda', model='CBR600RR', year=2005, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only'): ws.connect(mode='service')
    assert ws.selection.profile.memory['read_supported'] is False


def test_status_table_and_snapshot_isolation():
    table10 = frame(2, 22, 0x71, 0x10, *([0] * 17))
    d1 = frame(2, 10, 0x71, 0xd1, 1, 0, 0, 0, 1)
    t = FakeHonda(table10 + d1); s = service(t); s.connect()
    samples = s.read_parameters(['rpm', 'gear_status', 'engine_status'])
    assert [x.value for x in samples] == [0, 1, 1]
    assert 'Neutral or clutch' in samples[1].text
    assert 'candidate' in samples[2].text
    assert t.conn.sent == [bytes.fromhex('72 05 71 10 08'), bytes.fromhex('72 05 71 d1 47')]
    assert not s.gate.state.engine_running


def test_status_failure_does_not_erase_valid_sensor_table():
    table10 = frame(2, 22, 0x71, 0x10, *([0] * 17))
    invalid_status = bytes.fromhex('02 0a 71 d1 00 00 00 00 01 22')  # upstream example checksum fails
    t = FakeHonda(table10 + invalid_status); s = service(t); s.connect()
    samples = s.read_parameters(['rpm', 'gear_status'])
    assert samples[0].value == 0 and not samples[0].error
    assert samples[1].value is None and 'checksum' in samples[1].error


def test_status_only_does_not_request_sensor_table():
    d1 = frame(2, 10, 0x71, 0xd1, 3, 0, 0, 0, 0)
    t = FakeHonda(d1); s = service(t); s.connect()
    assert 'Kickstand' in s.read_parameters(['gear_status'])[0].text
    assert t.conn.sent == [bytes.fromhex('72 05 71 d1 47')]


def test_raw_ecm_id_candidate_never_unlocks_safety_gate():
    # Synthetic 71 00; layout candidate drawn from HondaECU's do_get_ecmid.
    result = frame(2, 10, 0x71, 0, 1, 2, 3, 4, 5)
    t = FakeHonda(result); s = service(t); s.connect()
    identity = s.identify()
    assert identity.raw == bytes([1, 2, 3, 4, 5])
    assert identity.fields == {'Honda ECM ID (raw candidate)': '01 02 03 04 05'}
    assert identity.ecu_id == '' and not s.gate.state.identified
    assert t.conn.sent == [bytes.fromhex('72 05 71 00 18')]


def test_bad_ecm_id_does_not_preserve_old_evidence():
    t = FakeHonda(frame(2, 9, 0x71, 0, 1, 2, 3, 4)); s = service(t); s.connect()
    s.gate.state.identified = True; s.gate.state.ecu_hardware = 'old'
    with pytest.raises(ProtocolError): s.identify()
    assert not s.gate.state.identified and not s.gate.state.ecu_hardware
