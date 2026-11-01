"""Synthetic MGZ read exchanges. No physical ECU was tested."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.programming import ProgrammingService, ProgrammingError
from guzzionboard.protocol.honda_cbr600rr import (
    MGZ_A03_ECM_ID, MGZ_A03_ECM_ID_OFFSET, MGZ_A03_IMAGE_SIZE, MGZ_ECM_IDS,
    HONDA_RESEARCH_LAYOUTS, HONDA_EXAMPLE_INFERRED_IDS, HONDA_RESEARCH_IMAGE_SIZES,
    HONDA_RESEARCH_STARTS, HONDA_RESEARCH_MAX_END, HONDA_RESEARCH_EXAMPLE_PARTS,
    HONDA_RESEARCH_COMMENTED_IDS, HONDA_TABLE_ONLY_IDS, HONDA_EXAMPLE_ONLY_IDS, HONDA_FAMILY_INFERRED_IDS, HONDA_SOURCE_CONFLICTS, HONDA_VFR_RESEARCH_IDS, HondaCB500FDashSession, _honda_read_block,
    read_honda_research_image, read_mgz_research_image,
)
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport


def frame(body): return bytes(body) + bytes([(-sum(body)) & 255])


class EmulatedConnection(Connection):
    def __init__(self, *, ecm=MGZ_A03_ECM_ID, fault='', image=None):
        self.ecm, self.fault = ecm, fault
        self.image = bytearray(HONDA_RESEARCH_IMAGE_SIZES.get(ecm, MGZ_A03_IMAGE_SIZE)) if image is None else bytearray(image)
        id_offset = HONDA_RESEARCH_LAYOUTS.get(ecm, ('', MGZ_A03_ECM_ID_OFFSET))[1]
        self.image[id_offset:id_offset+5] = ecm
        self.image[-1] = (-sum(self.image)) & 255
        self.rx = bytearray(); self.sent = []; self.closed = False; self.nblocks = 0
    def write(self, request):
        self.sent.append(bytes(request))
        assert sum(request) & 255 == 0
        if request == bytes.fromhex('72 05 71 00 18'):
            self.rx.extend(frame([2, 10, 0x71, 0, *self.ecm]))
        elif request[0] == 0x27:
            self.rx.extend(frame([0x07 if self.fault != 'security' else 0x7f, 3]))
        elif request[:4] == bytes.fromhex('82 82 00 09'):
            self.nblocks += 1
            address = (request[4] << 16) | request[5] | (request[6] << 8)
            start = HONDA_RESEARCH_STARTS.get(self.ecm, 0)
            assert start <= address and address + request[7] <= start + len(self.image)
            n = request[7]; data = self.image[address-start:address-start+n]
            reply = frame([0x92, 0x92, 0, n+5, *data])
            if self.fault == 'block': reply = reply[:-1] + bytes([reply[-1] ^ 1])
            self.rx.extend(reply)
        else: raise AssertionError(f'unexpected outgoing request: {request.hex()}')
    def read_frame(self, timeout): raise AssertionError('not conventional KWP')
    def read_bytes(self, n, timeout):
        b = bytes(self.rx[:n]); del self.rx[:n]; return b
    def close(self): self.closed = True


class EmulatedTransport(Transport):
    name='kline'; is_physical=True; baud=10400
    def __init__(self, **kw): self.conn = EmulatedConnection(**kw)
    def open(self): return self.conn
    def initialize(self, connection, **kw):
        return InitResult(True, 'honda-cb500f-dashble', baud=10400,
                          protocol='honda-cbr600rr', handshake_complete=True,
                          response=bytes.fromhex('02 04 00 fa'))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    def create(profile='honda_cb500f_dashble', **kw):
        t = EmulatedTransport(**kw)
        d = DiagnosticsService(load_catalog().ecu(profile), t, SafetyGate(mode=Mode.READ_ONLY))
        d.connect()
        return t, d, ProgrammingService(d, image_dir=tmp_path)
    return create


@pytest.mark.parametrize('ecm, part', list(MGZ_ECM_IDS.items()))
def test_confirmed_full_synthetic_read_does_not_create_verified_backup(setup, ecm, part):
    t, d, prog = setup(ecm=ecm)
    img = prog.read_region(experimental_confirmation=True)
    assert len(img.data) == 262144 and img.data == t.conn.image
    assert img.meta['verified_backup'] is False and img.source == 'research-read'
    assert img.identity['ECM ID candidate'] == ecm.hex(' ').upper()
    assert img.identity['Source part candidate'] == part
    assert not d.gate.state.verified_backup and not d.gate.state.identified
    assert t.conn.sent[0] == bytes.fromhex('72 05 71 00 18')
    assert t.conn.sent[1][0] == 0x27 and t.conn.sent[2][0] == 0x27
    assert t.conn.nblocks == 32768
    assert t.conn.sent[3][:4] == bytes.fromhex('82 82 00 09')
    assert t.conn.sent[-1][4:8] == bytes.fromhex('03 f8 ff 08')
    assert all(req[0] in (0x72, 0x27, 0x82) for req in t.conn.sent)


def test_honda_source_layout_allowlist_is_explicit_and_bounded():
    assert len(HONDA_RESEARCH_LAYOUTS) == 60
    assert len(HONDA_EXAMPLE_INFERRED_IDS) == 34
    assert HONDA_RESEARCH_COMMENTED_IDS == {bytes.fromhex('01 00 5e 05 03')}
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 5e 05 03')] == ('38770-MFL-773', 0x2880A)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 02 49 01 01')] == ('38770-MKF-D43', 0x7C745)
    assert HONDA_RESEARCH_IMAGE_SIZES[bytes.fromhex('01 02 49 01 01')] == 0x100000
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 02 ca 05 01')] == ('38770-K0F-A01', 0x3233)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 02 de 05 01')] == ('38770-KYK-D12', 0x3319)
    assert HONDA_RESEARCH_EXAMPLE_PARTS[bytes.fromhex('01 00 6a 01 01')] == '38770-MFN-D01'
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 b8 05 02')] == ('38770-KYJ-922', 0xC3EE)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 fa 10 01')] == ('38770-KPP-N02', 0xC3CC)
    assert HONDA_RESEARCH_IMAGE_SIZES[bytes.fromhex('01 00 c5 0d 02')] == 0xE000
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 5e 03 01')] == ('38770-MFL-622', 0x2880A)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 f3 04 01')] == ('38770-MGP-A01', 0x29089)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 01 83 04 01')] == ('38770-MGP-A92', 0x26215)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 02 f2 05 11')] == ('38770-MJW-AQ1', 0x18BB7)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 00 2b 01 01')] == ('38770-MEL-D21', 0x23381)
    assert HONDA_RESEARCH_LAYOUTS[bytes.fromhex('01 01 9c 12 01')] == ('38770-MJE-G52', 0x15F72)
    assert len({part for part, _ in HONDA_RESEARCH_LAYOUTS.values()}) == 59
    assert set(HONDA_RESEARCH_IMAGE_SIZES) == set(HONDA_RESEARCH_STARTS) == set(HONDA_RESEARCH_LAYOUTS)
    assert all(0 <= offset <= HONDA_RESEARCH_IMAGE_SIZES[ecm] - 5
               and HONDA_RESEARCH_STARTS[ecm] + HONDA_RESEARCH_IMAGE_SIZES[ecm] <= HONDA_RESEARCH_MAX_END
               for ecm, (_, offset) in HONDA_RESEARCH_LAYOUTS.items())
    assert HONDA_RESEARCH_STARTS[bytes.fromhex('01 01 35 05 01')] == 0x4000
    assert HONDA_RESEARCH_STARTS[bytes.fromhex('01 02 13 05 01')] == 0x8000


@pytest.mark.parametrize('ecm, layout', list(HONDA_RESEARCH_LAYOUTS.items()))
def test_explicit_honda_source_id_reader_for_each_synthetic_layout(setup, ecm, layout):
    part, offset = layout
    t, d, prog = setup(profile='honda_pgmfi_flash_research', ecm=ecm)
    img = prog.read_region(experimental_confirmation=True)
    assert img.data == t.conn.image and img.identity['Source part candidate'] == part
    assert img.identity.get('Conflicting source example label') == HONDA_RESEARCH_EXAMPLE_PARTS.get(ecm)
    assert img.identity['ECM ID candidate'] == ecm.hex(' ').upper()
    assert img.meta['source_id_offset'] == offset and img.meta['verified_backup'] is False
    assert img.meta['source_id_table_status'] == ('example-only ID/part candidate; table may conflict' if ecm in HONDA_EXAMPLE_ONLY_IDS else 'active table ID; named example has a different ID' if ecm in HONDA_FAMILY_INFERRED_IDS else 'commented out upstream; matching example' if ecm in HONDA_RESEARCH_COMMENTED_IDS else 'active upstream entry')
    assert img.identity.get('Source ID conflict') == HONDA_SOURCE_CONFLICTS.get(ecm)
    assert img.meta['id_offset_basis'] == ('source ID table; no example independently checked' if ecm in HONDA_TABLE_ONLY_IDS else 'inferred from another family example; named example ID conflicts' if ecm in HONDA_FAMILY_INFERRED_IDS else 'inferred from source-named example image' if ecm in HONDA_EXAMPLE_INFERRED_IDS else 'source ID table, confirmed in example image')
    expected_size = HONDA_RESEARCH_IMAGE_SIZES[ecm]
    assert len(img.data) == expected_size and img.meta['read_size'] == expected_size
    assert img.meta['sample_size'] == (None if ecm in HONDA_TABLE_ONLY_IDS | HONDA_FAMILY_INFERRED_IDS else expected_size)
    if ecm in HONDA_TABLE_ONLY_IDS:
        assert img.meta['candidate_source'] == 'aeaphichart/HondaECU-1 b59ae98b'
        assert img.meta['read_size_basis'] == 'source model/family ROM size; no example independently checked'
    start = HONDA_RESEARCH_STARTS[ecm]
    assert img.meta['read_start'] == start
    assert img.meta['address_basis'] == ('source table offset used as assumed read start; example file origin not established' if start else 'zero start assumed; example file origin not established')
    block = 128 if ecm in HONDA_VFR_RESEARCH_IDS else 8
    assert t.conn.nblocks == expected_size // block
    def encoded(addr): return bytes([addr >> 16, addr & 255, (addr >> 8) & 255, block])
    assert t.conn.sent[3][4:8] == encoded(start)
    assert t.conn.sent[-1][4:8] == encoded(start + expected_size - block)
    assert all(req[0] in (0x72, 0x27, 0x82) for req in t.conn.sent)
    assert not d.gate.state.identified and not d.gate.state.verified_backup


def test_generic_reader_unknown_and_wrong_session_fail_before_security(setup):
    t, _, prog = setup(profile='honda_pgmfi_flash_research', ecm=b'\x01\x02\x03\x04\x05')
    with pytest.raises(ProtocolError, match='ECM ID'): prog.read_region(experimental_confirmation=True)
    assert len(t.conn.sent) == 1 and t.conn.nblocks == 0
    other_id = bytes.fromhex('01 02 f2 05 11')
    t, _, prog = setup(ecm=other_id)  # narrower DashBle profile
    with pytest.raises(ProtocolError, match='ECM ID'): prog.read_region(experimental_confirmation=True)
    assert len(t.conn.sent) == 1 and t.conn.nblocks == 0
    with pytest.raises(PermissionError): read_honda_research_image(object())


def test_generic_research_profile_is_ecu_only_and_does_not_offer_live_or_writes(setup):
    from guzzionboard.transports.base import TransportUnavailable
    from guzzionboard.workstation import Workstation
    profile = load_catalog(overlays=False).ecu('honda_pgmfi_flash_research')
    assert profile.capabilities == ('identify',) and profile.memory['research_read_only']
    assert profile.memory['read_supported'] and not profile.memory['write_supported']
    ws = Workstation(record=False)
    ws.select(ecu=profile.id, transport='kline')
    with pytest.raises(TransportUnavailable): ws.connect(mode='service')
    t, d, prog = setup(profile=profile.id)
    with pytest.raises(PermissionError): d.session.request(b'\x71\x11')
    with pytest.raises(ProgrammingError, match='explicit confirmation'): prog.read_region()
    with pytest.raises(ProgrammingError, match='verified backup'): prog.backup()
    assert t.conn.sent == []


def test_no_confirmation_no_bytes_and_no_backup(setup):
    t, d, prog = setup()
    with pytest.raises(ProgrammingError, match='explicit confirmation'): prog.read_region()
    with pytest.raises(ProgrammingError, match='verified backup'): prog.backup()
    with pytest.raises(ProgrammingError, match='verified base maps'): prog.save_base_map("missing.bin")
    from guzzionboard.firmware import FirmwareImage
    with pytest.raises(ProgrammingError, match='never writes'): prog.write_region(FirmwareImage(b"\x00"), "fake")
    assert t.conn.sent == []


def test_wrong_identity_and_failed_security_stop_without_retries(setup):
    t, _, prog = setup(ecm=b'\x01\x02\x03\x04\x05')
    with pytest.raises(ProtocolError, match='ECM ID'): prog.read_region(experimental_confirmation=True)
    assert len(t.conn.sent) == 1 and t.conn.nblocks == 0
    t, _, prog = setup(fault='security')
    with pytest.raises(ProtocolError, match='security'): prog.read_region(experimental_confirmation=True)
    assert len(t.conn.sent) == 2 and t.conn.nblocks == 0


def test_bad_block_stops_and_yields_no_image(setup):
    t, _, prog = setup(fault='block')
    with pytest.raises(ProtocolError, match='checksum'): prog.read_region(experimental_confirmation=True)
    assert t.conn.nblocks == 1


def test_bounds_and_wrong_session_refused_before_write():
    c = EmulatedConnection()
    with pytest.raises(PermissionError): _honda_read_block(c, HONDA_RESEARCH_MAX_END - 1, 2, lambda *_: None)
    with pytest.raises(PermissionError): _honda_read_block(c, -1, 1, lambda *_: None)
    with pytest.raises(PermissionError): _honda_read_block(c, 0, 9, lambda *_: None)
    with pytest.raises(PermissionError): read_mgz_research_image(object())
    assert c.sent == []


def test_image_id_or_checksum_mismatch_never_returns_file(setup):
    t, _, prog = setup()
    # Even another allowed source ID in the image must match this live ECU.
    t.conn.image[MGZ_A03_ECM_ID_OFFSET:MGZ_A03_ECM_ID_OFFSET+5] = bytes.fromhex('01 01 25 0b 01')
    with pytest.raises(ProtocolError, match='image ECM ID'): prog.read_region(experimental_confirmation=True)
    t, _, prog = setup()
    t.conn.image[20] ^= 1
    with pytest.raises(ProtocolError, match='whole-image checksum'): prog.read_region(experimental_confirmation=True)


@pytest.mark.parametrize('ecm', [bytes.fromhex('01 00 b8 05 02'), bytes.fromhex('01 00 f3 04 01'), bytes.fromhex('01 02 13 05 01')])
def test_new_research_layouts_reject_bad_id_or_sum(setup, ecm):
    t, _, prog = setup(profile='honda_pgmfi_flash_research', ecm=ecm)
    offset = HONDA_RESEARCH_LAYOUTS[ecm][1]
    t.conn.image[offset] ^= 1
    with pytest.raises(ProtocolError, match='image ECM ID'):
        prog.read_region(experimental_confirmation=True)
    t, _, prog = setup(profile='honda_pgmfi_flash_research', ecm=ecm)
    t.conn.image[20] ^= 1
    with pytest.raises(ProtocolError, match='whole-image checksum'):
        prog.read_region(experimental_confirmation=True)


def test_generic_research_api_exports_only_after_confirmed_matching_read(setup, tmp_path):
    from guzzionboard.server import Api
    ecm = bytes.fromhex('01 02 f2 05 11')
    t, _, prog = setup(profile='honda_pgmfi_flash_research', ecm=ecm)
    api = Api(WorkstationStub())
    api._programming = lambda: prog
    class Immediate:
        def start(self, name, fn): return fn(lambda _: None)
    api.jobs = Immediate()
    with pytest.raises(ProgrammingError, match='explicit confirmation'):
        api.post_memory_read({'region': 'flash'})
    assert not t.conn.sent and not list(tmp_path.iterdir())
    status, result = api.post_memory_read({'region': 'flash', 'confirm_research_read': True})
    assert status == 202 and result['research_only'] is True
    assert result['describe']['identity']['Source part candidate'] == '38770-MJW-AQ1'
    assert result['describe']['meta']['verified_backup'] is False
    assert result['describe']['meta']['source_id_offset'] == 0x18BB7
    from pathlib import Path
    assert Path(result['path']).read_bytes() == t.conn.image


def test_api_confirmation_and_research_file_metadata(setup):
    from guzzionboard.server import Api
    t, d, prog = setup()
    api = Api(WorkstationStub())
    api._programming = lambda: prog
    class Immediate:
        def start(self, name, fn): return fn(lambda _: None)
    api.jobs = Immediate()
    with pytest.raises(ProgrammingError, match='explicit confirmation'):
        api.post_memory_read({'region': 'flash'})
    assert not t.conn.sent
    status, result = api.post_memory_read({'region': 'flash', 'confirm_research_read': True})
    assert status == 202 and result['research_only'] is True
    assert result['describe']['meta']['verified_backup'] is False
    assert 'research-read-' in result['path']
    from pathlib import Path
    assert Path(result['path']).read_bytes() == t.conn.image
    assert Path(result['path'] + '.json').exists()


class WorkstationStub:
    pass


def test_vfr_128_byte_request_is_source_scoped():
    connection = EmulatedConnection()
    assert len(_honda_read_block(connection, 0x36b00, 128, lambda *args: None, max_size=128)) == 128
    assert connection.sent[-1][4:8] == bytes([0x03, 0x00, 0x6b, 0x80])
    with pytest.raises(PermissionError):
        _honda_read_block(connection, 0, 128, lambda *args: None)
    with pytest.raises(PermissionError):
        _honda_read_block(connection, 0, 129, lambda *args: None, max_size=128)
