"""Synthetic ELM fixtures; these tests do not validate a motorcycle."""
from __future__ import annotations

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService, NotConnected
from guzzionboard.protocol.harley_j1850 import HarleyJ1850Session, _crc
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportError, TransportUnavailable
from guzzionboard.transports.elm_j1850 import ElmJ1850Connection, ElmJ1850Transport
from guzzionboard.workstation import Workstation


def frame(*payload):
    body = bytes(payload)
    return (body + bytes([_crc(body)])).hex().upper()


class FakeConnection(Connection):
    def __init__(self):
        self.commands = []
        self.replies = {}
        self.closed = False
        self.broadcast = ''
    @property
    def is_open(self): return not self.closed
    def command(self, command, timeout):
        self.commands.append(command)
        return self.replies.get(command, 'OK\r' if command.startswith('ATSH') else 'NO DATA\r')
    def monitor(self, timeout): self.commands.append('ATMA'); return self.broadcast
    def write(self, data): raise AssertionError('no raw writes')
    def read_frame(self, timeout): raise AssertionError('no raw reads')
    def close(self): self.closed = True


class FakeTransport(Transport):
    name, is_physical = 'elm_j1850', True
    def __init__(self, conn=None): self.conn = conn or FakeConnection(); self.opened = False
    def open(self): self.opened = True; return self.conn
    def initialize(self, conn, **kwargs):
        assert kwargs['method'] == 'harley-j1850-harleydroid'
        return InitResult(True, kwargs['method'], protocol='j1850-vpw', handshake_complete=True)


def service(transport):
    return DiagnosticsService(load_catalog().ecu('harley_j1850_harleydroid'), transport, SafetyGate(mode=Mode.READ_ONLY))


def test_live_snapshot_only_decodes_complete_crc_valid_frames():
    t = FakeTransport(); s = service(t); s.connect()
    t.conn.broadcast = '\r'.join(['ATMA', '28 1B 10 02 0F A0 D7', frame(0x48, 0x29, 0x10, 0x02, 0x32, 0x00),
                                  frame(0xa8, 0x49, 0x10, 0x10, 120), '281B1002000000'])
    samples = s.read_parameters()
    assert [(x.key, x.value) for x in samples] == [('rpm', 1000), ('speed', 100.0), ('engine_temp', 80)]
    assert t.conn.commands == ['ATMA']
    assert s.read_parameter(s.profile.parameter('rpm')).value == 1000
    t.conn.broadcast = '28 1B 10 02 0F A0 00\r'
    samples = s.read_parameters(['rpm', 'speed'])
    assert all(x.value is None and 'No matching' in x.error for x in samples)
    assert s.last_samples['rpm'].value is None  # no stale RPM reuse
    s.disconnect(); assert t.conn.closed


def test_identification_assembles_only_complete_matching_blocks():
    t = FakeTransport(); s = service(t); s.connect()
    for block, value in [(1,b'123456'), (2,b'789012'), (3,b'ABCDEF'), (4,b'GHIJKL'),
                         (11, b'\x07'), (15,b'1HD123'), (16,b'456789'), (17,b'01234')]:
        t.conn.replies[f'3C{block:02X}'] = frame(0x0c,0xf1,0x10,0x7c,block,*value)
    identity = s.identify()
    assert identity.fields == {'ECM part number':'123456789012', 'ECM calibration ID':'ABCDEFGHIJKL',
                               'VIN':'1HD12345678901234', 'ECM software level':'7'}
    assert t.conn.commands == ['ATSH0C10F1','3C01','3C02','3C03','3C04','3C0B','3C0F','3C10','3C11']
    assert s.gate.state.ecu_hardware == ''  # no asserted flashing fitment
    s.disconnect()


def test_identity_never_treats_missing_or_bad_crc_as_complete():
    t = FakeTransport(); s = service(t); s.connect()
    t.conn.replies['3C01'] = frame(0x0c,0xf1,0x10,0x7c,1,*b'123456')
    with pytest.raises(ProtocolError, match='No complete'): s.identify()
    assert not s.gate.state.identified
    t.conn.replies['3C02'] = frame(0x0c,0xf1,0x10,0x7c,2,*b'789012')[:-2] + '00'
    with pytest.raises(ProtocolError, match='invalid length or CRC'): s.identify()
    assert not s.gate.state.identified
    s.disconnect()


def test_dtc_response_status_and_missing_modules_are_not_invented():
    t = FakeTransport(); s = service(t); s.connect()
    responses = iter([frame(0x6c,0xf1,0x10,0x59,1,0x34),
                      frame(0x6c,0xf1,0x40,0x59,0,0), 'NO DATA\r'])
    old = t.conn.command
    t.conn.command = lambda c, timeout: next(responses) if c == '1952FF00' else old(c,timeout)
    result = s.read_dtcs()
    assert result['modules'] == {'ECM':{'responded':True}, 'ABS':{'responded':True}, 'TSM':{'responded':False}}
    assert result['dtcs'][0]['code'] == 'P0134'
    assert result['dtcs'][0]['description'] == 'HarleyDroid reference (fitment unverified): Front Oxygen Sensor Open'
    assert result['dtcs'][0]['status_byte'] is None and result['dtcs'][0]['status'] == 'unknown'
    assert 'missing responses do not mean no faults' in result['note']
    assert not s.check_clear_dtcs().allowed
    with pytest.raises(ProtocolError): s.clear_dtcs('invalid')
    s.disconnect()


def test_dtc_bad_matching_crc_fails_instead_of_clean_result():
    conn = FakeConnection(); conn.replies['1952FF00'] = frame(0x6c,0xf1,0x10,0x59,1,0x34)[:-2] + '00'
    with pytest.raises(ProtocolError, match='CRC'): HarleyJ1850Session(conn).read_dtcs()


def test_harley_profile_boundaries_before_open():
    ws = Workstation(record=False)
    ws.select(ecu='harley_j1850_harleydroid', transport='elm_j1850', device='')
    with pytest.raises(TransportUnavailable, match='explicit ELM327 serial'): ws.connect(mode='read_only')
    ws.select(ecu='harley_j1850_harleydroid', transport='elm_j1850', device='COM3')
    with pytest.raises(TransportUnavailable, match='read-only mode'): ws.connect(mode='service')
    ws.select(ecu='harley_j1850_harleydroid', transport='kline', device='COM3')
    with pytest.raises(TransportUnavailable, match='read-only mode'): ws.connect(mode='read_only')
    ws.select(ecu='5am', transport='elm_j1850', device='COM3')
    with pytest.raises(TransportUnavailable, match='restricted'): ws.connect(mode='read_only')
    for bad in ['ATSH6C10F1\r14', '14', '2701', '340044', '11', 'ATMA']:
        conn = ElmJ1850Connection(SerialStub({}))
        with pytest.raises(PermissionError): conn.command(bad)
        assert conn.serial.sent == []


class SerialStub:
    def __init__(self, answers): self.answers, self.buffer, self.sent, self.is_open = answers, bytearray(), [], True
    def write(self, data):
        self.sent.append(bytes(data))
        self.buffer.extend(self.answers.get(bytes(data), b''))
        return len(data)
    def read(self, n):
        if not self.buffer: return b''
        data = self.buffer[:n]; del self.buffer[:n]; return bytes(data)
    def flush(self): pass
    def close(self): self.is_open = False


def test_elm_setup_and_restricted_monitor(monkeypatch):
    responses = {b'ATWS\r': b'ATWS\rELM327 v1.5\r>',
                 **{(c+'\r').encode(): (c+'\rOK\r>').encode() for c in ['ATE1','ATH1','ATAL','ATS0','ATSP2']},
                 b'ATMA\r': b'ATMA\r28 1B 10 02 0F A0 D7\r', b'\r': b'STOPPED\r>'}
    serial = SerialStub(responses); conn = ElmJ1850Connection(serial)
    result = ElmJ1850Transport('COM3').initialize(conn, method='harley-j1850-harleydroid')
    assert result.ok and result.protocol == 'j1850-vpw'
    # Advance a deterministic clock to bound monitor even without a real bus.
    clock = iter([0.0] + [0.01 * n for n in range(1,1000)])
    monkeypatch.setattr('guzzionboard.transports.elm_j1850.time.monotonic', lambda: next(clock))
    data = conn.monitor(0.5)
    assert '28 1B 10 02 0F A0 D7' in data
    assert serial.sent[-2:] == [b'ATMA\r', b'\r']
    conn.close()


def test_connection_drops_after_elms_prompt_timeout(monkeypatch):
    serial = SerialStub({}); conn = ElmJ1850Connection(serial)
    clock = iter([0.0, 0.1, 10.0])
    monkeypatch.setattr('guzzionboard.transports.elm_j1850.time.monotonic', lambda: next(clock))
    with pytest.raises(TransportError, match='prompt timed out'): conn.command('ATWS', 1)
    assert not conn.is_open
    monkeypatch.undo()
    t = FakeTransport(); s = service(t); s.connect(); t.conn.close()
    assert not s.connected
    with pytest.raises(NotConnected): s.read_parameters(['rpm'])


def test_workstation_api_flow_is_live_read_only(monkeypatch):
    from guzzionboard.server import Api
    from guzzionboard.programming import ProgrammingError
    t = FakeTransport()
    monkeypatch.setattr(Workstation, '_build_transport', lambda self: t)
    ws = Workstation(record=False)
    selected = ws.select(ecu='harley_j1850_harleydroid', transport='elm_j1850', device='COM3')
    assert selected['ecu']['effective_capabilities'] == ['identify', 'live', 'dtc_read']
    ws.connect(mode='read_only')
    assert ws.status()['connected'] and t.opened
    t.conn.broadcast = '28 1B 10 02 0F A0 D7\r'
    api = Api(ws)
    code, live = api.get_live({'keys': ['rpm,speed']})
    assert code == 200 and live['samples'][0]['value'] == 1000
    assert live['samples'][1]['value'] is None
    code, dtcs = api.get_dtcs({})
    assert code == 200 and not dtcs['clear']['allowed']
    assert not any(item['responded'] for item in dtcs['modules'].values())
    with pytest.raises(ProgrammingError, match='reading is not supported'):
        api._programming().read_region()
    with pytest.raises(ProtocolError, match='KWP2000'):
        ws.require_service().clear_dtcs('invalid')
    ws.disconnect()
    assert t.conn.closed


def test_service_rejects_wrong_mode_before_port_opens():
    t = FakeTransport()
    svc = DiagnosticsService(load_catalog().ecu('harley_j1850_harleydroid'), t, SafetyGate(mode=Mode.SERVICE))
    with pytest.raises(TransportUnavailable, match='read-only mode'): svc.connect()
    assert not t.opened


def test_short_serial_write_closes_link():
    class Partial(SerialStub):
        def write(self, data): self.sent.append(bytes(data)); return len(data) - 1
    port = Partial({}); conn = ElmJ1850Connection(port)
    with pytest.raises(TransportError, match='not fully written'): conn.command('ATWS')
    assert not conn.is_open


def test_adapter_rejection_and_timeout_clean_up():
    class RejectingTransport(FakeTransport):
        def initialize(self, conn, **kwargs):
            raise TransportError('ELM did not acknowledge ATH1')
    t = RejectingTransport(); s = service(t)
    with pytest.raises(TransportError, match='acknowledge'): s.connect()
    assert t.conn.closed and not s.connected


def test_monitor_without_stop_prompt_closes_serial(monkeypatch):
    serial = SerialStub({b'ATMA\r': b'ATMA\r28 1B 10 02 0F A0 D7\r'})
    conn = ElmJ1850Connection(serial)
    ticks = iter(n / 100 for n in range(1000))
    monkeypatch.setattr('guzzionboard.transports.elm_j1850.time.monotonic', lambda: next(ticks))
    with pytest.raises(TransportError, match='prompt timed out'): conn.monitor(0.5)
    assert serial.sent == [b'ATMA\r', b'\r'] and not conn.is_open


def test_service_checks_initialize_method_before_open():
    t = FakeTransport(); s = service(t)
    with pytest.raises(TransportUnavailable, match='requires its profile-default initialization'): s.connect(init_method='fast')
    assert not t.opened


def test_harleydroid_reference_descriptions_are_scoped_and_unknown_remains_unknown():
    from guzzionboard.harley_dtc_descriptions import DESCRIPTIONS
    assert len(DESCRIPTIONS) == 167
    assert DESCRIPTIONS['C1151'] == 'Front Wheel ABS Release Too Long'
    assert 'PFFFF' not in DESCRIPTIONS
    conn = FakeConnection()
    conn.replies['1952FF00'] = frame(0x6c, 0xf1, 0x10, 0x59, 0x3f, 0xff)
    result = HarleyJ1850Session(conn).read_dtcs()
    assert result['dtcs'][0]['code'] == 'P3FFF'
    assert result['dtcs'][0]['description'] == ''
