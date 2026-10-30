"""Synthetic MGZ-A03 read exchanges. No physical ECU was tested."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.programming import ProgrammingService, ProgrammingError
from guzzionboard.protocol.honda_cbr600rr import (
    MGZ_A03_ECM_ID, MGZ_A03_ECM_ID_OFFSET, MGZ_A03_IMAGE_SIZE, HondaCB500FDashSession,
    _honda_read_block, read_mgz_a03_research_image,
)
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport


def frame(body): return bytes(body) + bytes([(-sum(body)) & 255])


class EmulatedConnection(Connection):
    def __init__(self, *, ecm=MGZ_A03_ECM_ID, fault='', image=None):
        self.ecm, self.fault = ecm, fault
        self.image = bytearray(MGZ_A03_IMAGE_SIZE) if image is None else bytearray(image)
        self.image[MGZ_A03_ECM_ID_OFFSET:MGZ_A03_ECM_ID_OFFSET+5] = MGZ_A03_ECM_ID
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
            n = request[7]; data = self.image[address:address+n]
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
    def create(**kw):
        t = EmulatedTransport(**kw)
        d = DiagnosticsService(load_catalog().ecu('honda_cb500f_dashble'), t, SafetyGate(mode=Mode.READ_ONLY))
        d.connect()
        return t, d, ProgrammingService(d, image_dir=tmp_path)
    return create


def test_confirmed_full_synthetic_read_does_not_create_verified_backup(setup):
    t, d, prog = setup()
    img = prog.read_region(experimental_confirmation=True)
    assert len(img.data) == 262144 and img.data == t.conn.image
    assert img.meta['verified_backup'] is False and img.source == 'research-read'
    assert not d.gate.state.verified_backup and not d.gate.state.identified
    assert t.conn.sent[0] == bytes.fromhex('72 05 71 00 18')
    assert t.conn.sent[1][0] == 0x27 and t.conn.sent[2][0] == 0x27
    assert t.conn.nblocks == 21846
    assert t.conn.sent[3][:4] == bytes.fromhex('82 82 00 09')
    assert t.conn.sent[-1][4:8] == bytes.fromhex('03 fc ff 04')
    assert all(req[0] in (0x72, 0x27, 0x82) for req in t.conn.sent)


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
    with pytest.raises(PermissionError): _honda_read_block(c, 0x3ffff, 2, lambda *_: None)
    with pytest.raises(PermissionError): _honda_read_block(c, -1, 1, lambda *_: None)
    with pytest.raises(PermissionError): _honda_read_block(c, 0, 13, lambda *_: None)
    with pytest.raises(PermissionError): read_mgz_a03_research_image(object())
    assert c.sent == []


def test_image_id_or_checksum_mismatch_never_returns_file(setup):
    t, _, prog = setup()
    t.conn.image[MGZ_A03_ECM_ID_OFFSET] ^= 1
    with pytest.raises(ProtocolError, match='image ECM ID'): prog.read_region(experimental_confirmation=True)
    t, _, prog = setup()
    t.conn.image[20] ^= 1
    with pytest.raises(ProtocolError, match='whole-image checksum'): prog.read_region(experimental_confirmation=True)


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
