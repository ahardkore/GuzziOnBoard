"""PGM-FI read-only research: synthetic frames, not motorcycle tests."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.honda_pgmfi import HondaPgmfiSession
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


def response(table, data):
    body = bytes([2, len(data) + 5, 0x71, table]) + data
    return body + bytes([(-sum(body)) & 0xff])


class FakeConnection(Connection):
    def __init__(self, data=b''): self.data, self.sent, self.closed = bytearray(data), [], False
    def write(self, data): self.sent.append(bytes(data))
    def read_bytes(self, size, timeout):
        b = bytes(self.data[:size]); del self.data[:size]; return b
    def read_frame(self, timeout): raise AssertionError('not a KWP frame')
    def close(self): self.closed = True


class FakeKLine(Transport):
    name, is_physical, baud = 'kline', True, 10400
    def __init__(self, data=b'', response=bytes.fromhex('02 04 00 fa')):
        self.connection, self.opened, self.response = FakeConnection(data), False, response
    def open(self): self.opened = True; return self.connection
    def initialize(self, conn, **kwargs):
        return InitResult(True, kwargs['method'], baud=self.baud, protocol='honda-cbr600rr',
                          handshake_complete=True, response=self.response)


def service(t, mode=Mode.READ_ONLY):
    return DiagnosticsService(load_catalog().ecu('honda_pgmfi_research'), t, SafetyGate(mode=mode))


@pytest.fixture(autouse=True)
def no_background(monkeypatch): monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)


def test_raw_and_candidate_values_share_one_table_request_and_do_not_set_safety_state():
    data = bytes.fromhex('12 34 01 02 03 50 06 07')
    t = FakeKLine(response(0x17, data)); s = service(t); s.connect()
    samples = s.read_parameters(['table_17_raw', 'table_17_rpm', 'table_17_coolant'])
    assert [x.value for x in samples] == [None, 0x1234, 40]
    assert samples[0].raw == data and samples[0].text == 'Raw table (meaning varies)'
    assert samples[1].raw == bytes.fromhex('12 34') and samples[2].raw == b'\x50'
    assert t.connection.sent == [bytes.fromhex('72 05 71 17 01')]
    assert not s.gate.state.identified and s.gate.state.battery_v is None and not s.gate.state.engine_running
    s.disconnect(); assert t.connection.closed and len(t.connection.sent) == 1


def test_one_failed_table_does_not_return_stale_values_or_erase_another():
    wrong = response(0x11, b'\x01')
    good = response(0x17, bytes.fromhex('12 34 01 02 03 50'))
    t = FakeKLine(wrong + good); s = service(t); s.connect()
    a, b = s.read_parameters(['table_10_raw', 'table_17_rpm'])
    assert a.value is None and a.raw == b'' and 'mismatch' in a.error
    assert b.value == 0x1234 and not b.error
    s.disconnect()


def test_identity_is_candidate_only_and_tester_present_uses_table_00():
    r = response(0x00, b'\x01\x02\x03\x04\x05'); t = FakeKLine(r+r); s = service(t); s.connect()
    identity = s.identify()
    assert identity.raw == b'\x01\x02\x03\x04\x05' and identity.ecu_id == ''
    assert not s.gate.state.identified and not s.gate.state.ecu_hardware
    s.session.tester_present()
    assert t.connection.sent == [bytes.fromhex('72 05 71 00 18')]*2
    s.disconnect()


@pytest.mark.parametrize('payload', [b'\x71\x02', b'\x71\x13', b'\x72\x10', b'\x27\x01', b'\x14', b'\x34', b'\x71', b'\x71\x10\x00'])
def test_arbitrary_or_write_services_never_sent(payload):
    c = FakeConnection(); s = HondaPgmfiSession(c)
    with pytest.raises(PermissionError): s.request(payload)
    assert not c.sent


@pytest.mark.parametrize('bad', [b'', b'\x02', b'\x02\x02', b'\x02\x41',
                                 bytes.fromhex('02 06 71 10 01 00'), response(0x11,b'\x01'), response(0x10,b'')])
def test_bad_frames_fail_closed(bad):
    s = HondaPgmfiSession(FakeConnection(bad))
    with pytest.raises(ProtocolError): s.read_table(0x10)


def test_short_data_cannot_be_decoded_as_sensor_but_raw_is_available():
    t = FakeKLine(response(0x10,b'\x20')); s = service(t); s.connect()
    raw, rpm, temp = s.read_parameters(['table_10_raw','table_10_rpm','table_10_coolant'])
    assert raw.raw == b'\x20' and not raw.error
    assert rpm.value is None and temp.value is None and rpm.error and temp.error
    s.disconnect()


def test_only_physical_read_only_expected_profile_default_init():
    for changes, mode, init in [({'baud':9600}, Mode.READ_ONLY, None), ({'is_physical':False}, Mode.READ_ONLY, None),
                                 ({}, Mode.SERVICE, None), ({}, Mode.READ_ONLY, 'fast')]:
        t=FakeKLine()
        for k,v in changes.items(): setattr(t,k,v)
        with pytest.raises(TransportUnavailable): service(t,mode).connect(init_method=init)
        assert not t.opened
    t=FakeKLine(response=b'\x02\x04\x00\x00'); s=service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.connection.closed


def test_source_list_adds_more_than_25_distinct_models_as_attempts_only():
    c=load_catalog(); entries=[e for e in c.vehicles if e.ecu=='honda_pgmfi_research']
    assert len({e.model for e in entries}) >= 25
    for v in entries:
        assert v.make == 'Honda' and v.confidence == 'unknown'
        assert 'not confirmation' in v.notes
        entry, profile = c.resolve(v.model, v.year_from, 'Honda')
        assert entry.ecu == 'honda_pgmfi_research' and profile.id == entry.ecu
    assert not c.find('CRF250L',2016,'Honda')
    p=c.ecu('honda_pgmfi_research')
    assert p.capabilities == ('identify','live') and not p.memory['read_supported'] and not p.memory['write_supported']
    w=Workstation(record=False); w.select(make='Honda',model='Wave 110',year=2012,transport='kline')
    assert w.selection.profile.id == p.id
    with pytest.raises(TransportUnavailable): w.connect(mode='service')


def test_existing_honda_models_gain_source_listed_additional_years_without_replacing_original_profile():
    c=load_catalog()
    assert c.resolve('CBR600RR',2005,'Honda')[1].id == 'honda_cbr600rr_2005'
    for model,year in [('CBR600RR',2003),('CBR600RR',2019),('CB500F',2018),('CBR500R',2019),('CBR1000RR',2019)]:
        assert c.resolve(model,year,'Honda')[1].id == 'honda_pgmfi_research'


def test_existing_attributed_dashble_table11_capture_in_generic_session():
    # atoid/Dash MIT example, already attributed in tests/test_honda_cb500f_dash.py.
    captured=bytes.fromhex('02 19 71 11 06 a2 1c 00 b8 32 b7 33 72 4c ff ff 8b 00 04 35 98 5b 17 23 1e')
    t=FakeKLine(captured); s=service(t); s.connect()
    raw,rpm,temp=s.read_parameters(['table_11_raw','table_11_rpm','table_11_coolant'])
    assert raw.raw == captured[4:-1] and rpm.value == 1698 and temp.value == 10
    assert t.connection.sent == [bytes.fromhex('72 05 71 11 07')]
    s.disconnect()


@pytest.mark.parametrize('model,years', [
 ('CBR1000RR HRC',[2008,2012,2019]), ('CBR600RR HRC',[2005,2018]),
 ('CRF300L',[2021,2022]), ('CRF450RL',[2021,2026]), ('CRF 450 RX Enduro',[2022]),
 ('RS 150',[2016,2020]), ('Sonic 150',[2016,2020]), ('Supra GTR 150',[2016,2020]),
 ('Winner 150',[2016,2020]), ('Goldwing 1800',[2005,2008]), ('NC700X',[2012,2013]),
 ('NC700XD',[2012,2013]), ('Shadow Aero 750',[2007,2012]), ('VFR1200FD',[2010,2012,2013]),
 ('CBR125R',[2007,2009,2011]), ('CRF250L',[2013]), ('CRF450R',[2009,2013,2025]),
 ('CB600F',[2007]), ('CBR650R',[2023]), ('CB650R',[2023]), ('CBR600RR',[2022]),
 ('CBR1000RR',[2026]), ('X-ADV 750',[2025])])
def test_new_honda_models_resolve_to_disclaimed_read_only_profile(model,years):
    w=Workstation(record=False)
    for year in years:
        selected=w.select(make='Honda',model=model,year=year,transport='kline')
        assert selected['ecu']['id']=='honda_pgmfi_research'
        assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
        assert not selected['ecu']['memory']['read_supported']
        with pytest.raises(TransportUnavailable,match='read-only'): w.connect(mode='service')


def test_honda_pgmfi_requires_cataloged_vehicle():
    w=Workstation(record=False); w.select(ecu='honda_pgmfi_research',transport='kline')
    with pytest.raises(TransportUnavailable,match='source-listed'): w.connect(mode='read_only')


@pytest.mark.parametrize('model,years', [
    ('Z125M',[2019]),('CRF110F',range(2019,2025)),('MSX125',[2014,2017]),
    ('CBR250R',[2012]),('CBR250R HRC',[2014]),('CBR250RR HRC',[2017]),
    ('CRF250R',[2011,2013,2014,2015]),('VTR250',[2015]),('CBR300R HRC',[2014]),
    ('CB300',range(2008,2013)),('SH300',[2009]),('XRE 300',range(2009,2013)),
    ('Transalp700',[2013]),('Shadow 750',[2009]),('GL1800',[2015]),('CB600F/R',[2010,2011])])
def test_hondaecu_source_models_attempt_raw_table_with_fake_ecu(monkeypatch,model,years):
    for year in years:
        w=Workstation(record=False)
        selected=w.select(make='Honda',model=model,year=year,transport='kline')
        assert selected['ecu']['id']=='honda_pgmfi_research'
        assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
        assert not selected['ecu']['memory']['read_supported']
        t=FakeKLine(response(0x10,b'\x01\x02'))
        monkeypatch.setattr(w,'_build_transport',lambda:t)
        w.connect(mode='read_only')
        sample=w.require_service().read_parameters(['table_10_raw'])[0]
        assert sample.raw==b'\x01\x02' and sample.value is None and not sample.error
        assert t.connection.sent==[bytes.fromhex('72 05 71 10 08')]
        w.disconnect(); assert t.connection.closed


def test_honda_source_does_not_fill_missing_years():
    c=load_catalog()
    assert not c.find('MSX125',2015,'Honda')
    assert c.resolve('CRF250R',2012,'Honda')[1].id == 'honda_pgmfi_research'
    assert not c.find('CRF250R',2009,'Honda')
    assert not c.find('CRF110F',2018,'Honda')


@pytest.mark.parametrize('model,years', [
    ('Vario 125 Techno FI', range(2012, 2016)),
    ('CB150R StreetFire', range(2012, 2022)),
    ('CBR150R FI', range(2014, 2021)),
    ('Supra X 125 Helm-In', range(2014, 2021)),
])
def test_wrt_listed_keihin_models_attempt_raw_read_with_synthetic_ecu(monkeypatch, model, years):
    """28 model/year combinations, not 28 distinct models or hardware tests."""
    for year in years:
        w = Workstation(record=False)
        selected = w.select(make='Honda', model=model, year=year, transport='kline')
        assert selected['ecu']['id'] == 'honda_pgmfi_research'
        assert 'synthetic' in selected['ecu']['session']['physical_evidence_note'].lower()
        assert not selected['ecu']['memory']['read_supported']
        t = FakeKLine(response(0x10, b'\x01\x02'))
        monkeypatch.setattr(w, '_build_transport', lambda: t)
        w.connect(mode='read_only')
        sample = w.require_service().read_parameters(['table_10_raw'])[0]
        assert sample.raw == b'\x01\x02' and sample.value is None and not sample.error
        assert t.connection.sent == [bytes.fromhex('72 05 71 10 08')]
        w.disconnect()


def test_wrt_listed_models_do_not_claim_outside_years():
    c = load_catalog()
    for model, year in [('Vario 125 Techno FI', 2016), ('CB150R StreetFire', 2022),
                        ('CBR150R FI', 2013), ('Supra X 125 Helm-In', 2021)]:
        assert not c.find(model, year, 'Honda')


@pytest.mark.parametrize('model,years', [
    ('CRF250R', [2010, 2012, *range(2016, 2023)]),
    ('CRF250RX', range(2019, 2023)),
])
def test_hrc_crf_model_years_attempt_read_with_fake_ecu(monkeypatch, model, years):
    """The HRC tool's tuning capabilities are not implemented here."""
    for year in years:
        w = Workstation(record=False)
        selected = w.select(make='Honda', model=model, year=year, transport='kline')
        assert selected['ecu']['id'] == 'honda_pgmfi_research'
        assert not selected['ecu']['memory']['read_supported']
        assert not selected['ecu']['memory']['write_supported']
        t = FakeKLine(response(0x10, b'\x01\x02'))
        monkeypatch.setattr(w, '_build_transport', lambda: t)
        w.connect(mode='read_only')
        sample = w.require_service().read_parameters(['table_10_raw'])[0]
        assert sample.raw == b'\x01\x02' and sample.value is None and not sample.error
        assert t.connection.sent == [bytes.fromhex('72 05 71 10 08')]
        w.disconnect()


def test_hrc_crf_model_years_are_bounded():
    c = load_catalog()
    assert not c.find('CRF250R', 2009, 'Honda')
    assert not c.find('CRF250R', 2023, 'Honda')
    assert not c.find('CRF250RX', 2018, 'Honda')
    assert not c.find('CRF250RX', 2023, 'Honda')
