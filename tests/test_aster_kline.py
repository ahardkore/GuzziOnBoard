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


def test_gsxr1000_2004_raw_snapshot_no_sensor_assumptions():
    from guzzionboard.protocol.aster_kline import Gsxr10002004Session
    raw = bytes(range(40))
    t = FakeTransport(0x12, [reply(0x12, 0x61, 0x08, *raw)])
    s = service('suzuki_gsxr1000_2004', t); s.connect()
    assert isinstance(s.session, Gsxr10002004Session)
    assert t.args['method'] == 'suzuki-gsxr1000-2004'
    sample = s.read_parameters(['raw_snapshot'])[0]
    assert sample.raw == raw and sample.value is None and sample.text.startswith('Raw snapshot')
    assert not s.gate.state.identified and s.gate.state.battery_v is None and not s.gate.state.engine_running
    assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    assert s.read_parameters([]) == []
    s.disconnect(); assert t.conn.closed and len(t.conn.sent) == 1


def test_gsxr1000_blocks_other_services_and_invalid_snapshots():
    from guzzionboard.protocol.aster_kline import Gsxr10002004Session
    c = FakeConnection([]); session = Gsxr10002004Session(c)
    for p in (b'\x3e\x01', b'\x23\x00', b'\x27\x01', b'\x14', b'\x34', b'\x21\x09'):
        with pytest.raises(PermissionError): session.request(p)
    assert not c.sent
    for bad in (reply(0x12,0x61,8), reply(0x11,0x61,8,1), reply(0x12,0x61,9,1), reply(0x12,0x61,8,*([1]*61))):
        t=FakeTransport(0x12,[bad]); s=service('suzuki_gsxr1000_2004',t); s.connect()
        result=s.read_parameters(['raw_snapshot'])[0]
        assert result.error and result.value is None and result.raw == b''
        s.disconnect()


def test_gsxr1000_exact_vehicle_selection_and_read_only():
    w=Workstation(record=False)
    w.select(ecu='suzuki_gsxr1000_2004', transport='kline')
    with pytest.raises(TransportUnavailable, match='exact tested model'): w.connect(mode='read_only')
    w.select(make='Suzuki', model='GSX-R1000', year=2004, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only'): w.connect(mode='service')


def test_gsxr1000_accepts_source_described_c1_two_keyword_response():
    t=FakeTransport(0x12, [], wake=reply(0x12, 0xc1, 0x12, 0x34))
    s=service('suzuki_gsxr1000_2004',t); s.connect(); s.disconnect()
    t=FakeTransport(0x12, [], wake=reply(0x12, 0xc1, 0x12))
    with pytest.raises(ProtocolError): service('suzuki_gsxr1000_2004',t).connect()
    assert t.conn.closed


def test_sv650ak7_live_snapshot_uses_source_conversions_and_preserves_raw():
    from guzzionboard.protocol.aster_kline import Sv650Ak7Session
    data=bytearray(50)
    data[11],data[13],data[15],data[16],data[18],data[20]=120,100,125,70,143,3
    t=FakeTransport(0x12,[reply(0x12,0x61,0x08,*data)])
    s=service('suzuki_sv650ak7_2007',t); s.connect()
    assert isinstance(s.session,Sv650Ak7Session)
    samples=s.read_parameters(['rpm','tps','coolant','airtemp','battery','gear_status'])
    assert [v.value for v in samples] == [8280,25,85,30,12.6,3]
    assert [v.raw for v in samples] == [b'\x78',b'\x64',b'\x7d',b'\x46',b'\x8f',b'\x03']
    assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    assert not s.gate.state.identified and s.gate.state.battery_v is None and not s.gate.state.engine_running
    s.disconnect(); assert t.conn.closed and len(t.conn.sent)==1


@pytest.mark.parametrize('bad', [reply(0x12,0x61,8,*([0]*49)), reply(0x11,0x61,8,*([0]*50)),
                                 reply(0x12,0x61,9,*([0]*50)),
                                 reply(0x12,0x61,8,*([0]*50))[:-1]+b'\x00'])
def test_sv650ak7_invalid_snapshot_never_becomes_data(bad):
    t=FakeTransport(0x12,[bad]); s=service('suzuki_sv650ak7_2007',t); s.connect()
    assert all(v.value is None and v.error for v in s.read_parameters(['rpm','gear_status']))
    s.disconnect()


def test_sv650ak7_allowlist_keepalive_and_frame_delay(monkeypatch):
    from guzzionboard.protocol.aster_kline import Sv650Ak7Session
    delays=[]; monkeypatch.setattr('guzzionboard.protocol.aster_kline.time.sleep',delays.append)
    c=FakeConnection([reply(0x12,0x61,8,*([0]*50))]); s=Sv650Ak7Session(c,target=0x12)
    for payload in (b'\x3e\x01',b'\x23\x00',b'\x27\x01',b'\x14',b'\x34',b'\x21\x09'):
        with pytest.raises(PermissionError): s.request(payload)
    assert c.sent==[]
    s.tester_present()
    assert c.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    assert delays[-2:] == [0.2,0.055]


def test_sv650ak7_exact_vehicle_and_read_only():
    w=Workstation(record=False)
    w.select(ecu='suzuki_sv650ak7_2007',transport='kline')
    with pytest.raises(TransportUnavailable,match='exact tested model'): w.connect(mode='read_only')
    w.select(make='Suzuki',model='SV650AK7',year=2007,transport='kline')
    with pytest.raises(TransportUnavailable,match='read-only'): w.connect(mode='service')


def test_sv650_2003_source_capture_is_raw_and_not_ak7_decoded():
    # synfinatic/sv650sds, data/sds_tool_output.txt (GPL-3.0).
    capture=bytes.fromhex('80 f1 12 34 61 08 00 00 00 00 00 00 00 ff ff ff ff 00 ff 43 cc 41 3d ff a7 ff 00 ff ff ff ff 00 00 00 00 ff ff ff ff ff ff 47 47 ff ff ff 7f ff ff ff ff 00 04 ff ff ff 4a')
    t=FakeTransport(0x12,[capture]); s=service('suzuki_sv650_2003',t); s.connect()
    sample=s.read_parameters()[0]
    assert sample.raw==capture[6:-1] and sample.value is None and not sample.error
    assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    s.disconnect()


@pytest.mark.parametrize('year',[2003,2004,2005])
def test_sv650_2003_scope_all_source_years(year):
    w=Workstation(record=False)
    w.select(make='Suzuki',model='SV650',year=year,transport='kline')
    assert w.selection.profile.id == 'suzuki_sv650_2003'
    with pytest.raises(TransportUnavailable,match='read-only'): w.connect(mode='service')


def test_sv650_2003_rejects_short_snapshot():
    t=FakeTransport(0x12,[reply(0x12,0x61,8,*([0]*49))]); s=service('suzuki_sv650_2003',t); s.connect()
    sample=s.read_parameters()[0]
    assert sample.error and not sample.raw


def test_suzuki_gsxr_research_raw_snapshot_and_read_only_allowlist():
    from guzzionboard.protocol.aster_kline import SuzukiGsxrResearchSession
    data=bytes(range(50))
    t=FakeTransport(0x12,[reply(0x12,0x61,8,*data)])
    s=service('suzuki_sds_gsxr_research',t); s.connect()
    assert isinstance(s.session,SuzukiGsxrResearchSession)
    sample=s.read_parameters()[0]
    assert sample.raw==data and sample.value is None and not sample.error
    assert t.conn.sent==[bytes.fromhex('80 12 f1 02 21 08 ae')]
    with pytest.raises(PermissionError): s.session.request(b'\x23\x00')
    s.disconnect(); assert len(t.conn.sent)==1


@pytest.mark.parametrize('data', [reply(0x12,0x61,8,*([0]*49)), reply(0x11,0x61,8,*([0]*50)),
                                  reply(0x12,0x61,9,*([0]*50))])
def test_suzuki_gsxr_research_invalid_snapshots_fail(data):
    t=FakeTransport(0x12,[data]); s=service('suzuki_sds_gsxr_research',t); s.connect()
    sample=s.read_parameters()[0]
    assert sample.error and not sample.raw and sample.value is None
    s.disconnect()


@pytest.mark.parametrize('model,start,end', [('GSX-R600',2006,2010),('GSX-R600',2012,2016),
 ('GSX-R750',2006,2016),('GSX-R1000',2005,2016),('GSX-R1300 Hayabusa',2008,2016)])
def test_suzuki_gsxr_source_list_ranges_and_transport_gates(model,start,end):
    w=Workstation(record=False)
    for year in range(start,end+1):
        selected=w.select(make='Suzuki',model=model,year=year,transport='kline')
        assert selected['ecu']['id']=='suzuki_sds_gsxr_research'
        assert selected['ecu']['capabilities']==['live']
        assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
        with pytest.raises(TransportUnavailable, match='read-only'): w.connect(mode='service')
    w.select(ecu='suzuki_sds_gsxr_research',transport='kline')
    with pytest.raises(TransportUnavailable,match='source-listed'): w.connect(mode='read_only')


def test_suzuki_gsxr_research_does_not_replace_prior_specific_models():
    c=load_catalog()
    assert c.resolve('GSX-R600',2011,'Suzuki')[1].id=='suzuki_gsxr600_2011'
    assert c.resolve('GSX-R1000',2004,'Suzuki')[1].id=='suzuki_gsxr1000_2004'
    assert c.resolve('GSX-R750',2017,'Suzuki')[1].id == 'suzuki_sds_gsxr_research'
    assert not c.find('GSX-R750',2018,'Suzuki')


def test_kds_research_raw_read_does_not_promote_sensor_or_safety_state():
    from guzzionboard.protocol.aster_kline import KawasakiKdsResearchSession
    t=FakeTransport(0x11,[reply(0x11,0x50,0x80),reply(0x11,0x61,9,30,128),reply(0x11,0x61,6,144)])
    s=service('kawasaki_kds_research',t); s.connect()
    assert isinstance(s.session,KawasakiKdsResearchSession)
    samples=s.read_parameters(['raw_09','raw_06'])
    assert [x.raw for x in samples] == [b'\x1e\x80',b'\x90']
    assert all(x.value is None and not x.error and 'unverified' in x.text for x in samples)
    assert t.conn.sent == [bytes.fromhex(x) for x in ('80 11 f1 02 10 80 14','80 11 f1 02 21 09 ae','80 11 f1 02 21 06 ab')]
    assert not s.gate.state.identified and not s.gate.state.engine_running and s.gate.state.battery_v is None
    with pytest.raises(PermissionError): s.session.request(b'\x23\x00')
    s.disconnect()


@pytest.mark.parametrize('bad', [reply(0x11,0x61,9,1),reply(0x12,0x61,9,1,2),
                                  reply(0x11,0x61,8,1,2),reply(0x11,0x61,9,1,2)[:-1]+b'\x00'])
def test_kds_research_bad_reply_stays_error(bad):
    t=FakeTransport(0x11,[reply(0x11,0x50,0x80),bad]); s=service('kawasaki_kds_research',t);s.connect()
    sample=s.read_parameters(['raw_09'])[0]
    assert sample.error and not sample.raw and sample.value is None
    s.disconnect()


def test_kds_all_vendor_models_select_synthetic_read_only(monkeypatch):
    models=[v for v in load_catalog().vehicles if v.ecu=='kawasaki_kds_research']
    assert len({v.model for v in models})==39
    for bike in models:
        for year in range(bike.year_from,bike.year_to + 1):
            w=Workstation(record=False)
            selected=w.select(make=bike.make,model=bike.model,year=year,transport='kline')
            assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
            assert not selected['ecu']['memory']['read_supported']
            with pytest.raises(TransportUnavailable,match='read-only'): w.connect(mode='service')
            t=FakeTransport(0x11,[reply(0x11,0x50,0x80),reply(0x11,0x61,9,1,2)])
            monkeypatch.setattr(w,'_build_transport',lambda:t)
            w.connect(mode='read_only')
            assert w.require_service().read_parameters()[0].raw==b'\x01\x02'
            w.disconnect()
    w=Workstation(record=False); w.select(ecu='kawasaki_kds_research',transport='kline')
    with pytest.raises(TransportUnavailable,match='source-listed'): w.connect(mode='read_only')
    c=load_catalog()
    assert c.resolve('ER-6n',2006,'Kawasaki')[1].id=='kawasaki_er6n_2006'
    assert c.resolve('Versys 650',2012,'Kawasaki')[1].id=='kawasaki_versys650_2012'


@pytest.mark.parametrize('model,years', [
    ('GSX-R600', list(range(2004, 2006)) + list(range(2017, 2024))),
    ('GSX-R750', [2004, 2005, 2017]),
])
def test_new_aim_suzuki_ranges_execute_raw_snapshot_with_fake_ecu(monkeypatch, model, years):
    """Synthetic exchanges, not a hardware test or a memory read."""
    for year in years:
        w = Workstation(record=False)
        selected = w.select(make='Suzuki', model=model, year=year, transport='kline')
        assert selected['ecu']['id'] == 'suzuki_sds_gsxr_research'
        assert not selected['ecu']['memory']['read_supported']
        t = FakeTransport(0x12, [reply(0x12, 0x61, 8, *range(50))])
        monkeypatch.setattr(w, '_build_transport', lambda: t)
        w.connect(mode='read_only')
        sample = w.require_service().read_parameters()[0]
        assert sample.raw == bytes(range(50)) and sample.value is None and not sample.error
        assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
        w.disconnect()


def test_extended_suzuki_ranges_are_bounded_and_do_not_override_special_profiles():
    c = load_catalog()
    assert not c.find('GSX-R600', 2003, 'Suzuki')
    assert not c.find('GSX-R600', 2024, 'Suzuki')
    assert not c.find('GSX-R750', 2018, 'Suzuki')
    assert c.resolve('GSX-R600', 2011, 'Suzuki')[1].id == 'suzuki_gsxr600_2011'
    assert c.resolve('GSX-R1000', 2004, 'Suzuki')[1].id == 'suzuki_gsxr1000_2004'


@pytest.mark.parametrize('profile,target,payload,expected', [
    ('kawasaki_kds_generic_research', 0x11,
     [reply(0x11, 0x50, 0x80), reply(0x11, 0x61, 9, 1, 2)], b'\x01\x02'),
    ('suzuki_sds_generic_research', 0x12,
     [reply(0x12, 0x61, 8, *range(40))], bytes(range(40))),
])
def test_generic_ecu_only_kline_research_is_read_only_and_returns_raw(monkeypatch, profile, target, payload, expected):
    w = Workstation(record=False)
    selected = w.select(ecu=profile, transport='kline')
    assert selected['ecu']['session']['simulator_supported'] is False
    assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
    assert selected['ecu']['capabilities'] == ['live']
    assert not selected['ecu']['memory']['read_supported']
    assert not selected['ecu']['memory']['write_supported']
    with pytest.raises(TransportUnavailable, match='read-only'):
        w.connect(mode='service')
    t = FakeTransport(target, payload)
    monkeypatch.setattr(w, '_build_transport', lambda: t)
    w.connect(mode='read_only')
    svc = w.require_service()
    sample = svc.read_parameters()[0]
    assert sample.raw == expected and sample.value is None and not sample.error
    assert not svc.gate.state.identified and svc.gate.state.battery_v is None
    for command in (b'\x23\x00', b'\x27\x01', b'\x14', b'\x34', b'\x31\x01'):
        with pytest.raises(PermissionError):
            svc.session.request(command)
    w.disconnect()
    assert t.conn.closed


@pytest.mark.parametrize('profile,target', [('kawasaki_kds_generic_research', 0x11),
                                            ('suzuki_sds_generic_research', 0x12)])
def test_generic_kline_attempt_never_treats_an_uncatalogued_model_as_evidence(profile, target):
    w = Workstation(record=False)
    with pytest.raises(ValueError, match='not cataloged'):
        w.select(make='Suzuki', model='GSX-R600', year=2011, ecu=profile, transport='kline')
    w.select(ecu=profile, transport='simulator')
    with pytest.raises(TransportUnavailable):
        w.connect()
    t = FakeTransport(target, [], wake=reply(target, 0xc1, 0xea))
    with pytest.raises(ProtocolError):
        service(profile, t).connect()
    assert t.conn.closed and not t.conn.sent
    t = FakeTransport(target, [])
    t.baud = 9600
    with pytest.raises(TransportUnavailable, match='10400'):
        service(profile, t).connect()
    assert not t.opened


def test_generic_suzuki_accepts_bounded_raw_lengths_but_not_empty_or_oversized():
    for size in (1, 40, 50, 60):
        t = FakeTransport(0x12, [reply(0x12, 0x61, 8, *([1] * size))])
        s = service('suzuki_sds_generic_research', t); s.connect()
        sample = s.read_parameters()[0]
        assert len(sample.raw) == size and sample.value is None and not sample.error
        s.disconnect()
    for size in (0, 61):
        t = FakeTransport(0x12, [reply(0x12, 0x61, 8, *([1] * size))])
        s = service('suzuki_sds_generic_research', t); s.connect()
        sample = s.read_parameters()[0]
        assert sample.raw == b'' and sample.value is None and sample.error
        s.disconnect()


def test_dl650_gateway_candidate_is_scoped_raw_and_read_only(monkeypatch):
    """The upstream project explicitly says its 2017 bike hasn't been tested."""
    w = Workstation(record=False)
    selected = w.select(make='Suzuki', model='V-Strom DL650XAL7', year=2017, transport='kline')
    assert selected['ecu']['id'] == 'suzuki_dl650_2017_research'
    assert 'not verified' in selected['ecu']['session']['physical_evidence_note'].lower()
    assert not selected['ecu']['memory']['read_supported'] and not selected['ecu']['memory']['write_supported']
    with pytest.raises(TransportUnavailable, match='read-only'):
        w.connect(mode='service')
    payload = bytes(range(52))
    t = FakeTransport(0x12, [reply(0x12, 0x61, 8, *payload)])
    monkeypatch.setattr(w, '_build_transport', lambda: t)
    w.connect(mode='read_only')
    sample = w.require_service().read_parameters()[0]
    assert sample.raw == payload and sample.value is None and not sample.error
    assert t.conn.sent == [bytes.fromhex('80 12 f1 02 21 08 ae')]
    with pytest.raises(PermissionError): w.require_service().session.request(b'\x14\xff\x00')
    w.disconnect()
    c = load_catalog()
    assert not c.find('V-Strom DL650XAL7', 2016, 'Suzuki')
    assert not c.find('V-Strom DL650XAL7', 2018, 'Suzuki')
    w.select(ecu='suzuki_dl650_2017_research', transport='kline')
    with pytest.raises(TransportUnavailable, match='exact 2017'):
        w.connect(mode='read_only')


def test_dl650_candidate_rejects_unexpected_wake_keywords():
    t = FakeTransport(0x12, [], wake=reply(0x12, 0xc1, 0x00, 0x00))
    s = service('suzuki_dl650_2017_research', t)
    with pytest.raises(ProtocolError, match='source-specific key bytes'):
        s.connect()
    assert t.conn.closed and not t.conn.sent
