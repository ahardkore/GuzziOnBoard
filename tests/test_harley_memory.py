"""Synthetic Delphi memory protocol tests; no physical ECU has been tested."""
from pathlib import Path
import pytest

from guzzionboard import harley_memory as hm
from guzzionboard.protocol.isotp import segment
from guzzionboard.server import Api
from guzzionboard.transports.base import TransportError
from guzzionboard.workstation import Workstation

AUTH = bytes(i % 251 for i in range(hm.AUTH_SIZE))
IDENTITY = {'F1EA': '414243', 'F1ED': '313233', 'F1F5': '0123'}
ORIGINAL = bytes((i * 7) % 256 for i in range(hm.TUNE_SIZE))
TARGET = bytes([ORIGINAL[0] ^ 1]) + ORIGINAL[1:]


def capture(p=AUTH):
    lines = []
    def msg(canid, payload):
        for frame in segment(payload):
            lines.append(f'1  0x{canid:X}  8  {frame.hex()}')
    msg(0x7e0, hm.AUTH_DOWNLOAD); msg(0x7e8, bytes.fromhex('74200802'))
    msg(0x7e0, b'\x36\x01' + p); msg(0x7e8, bytes.fromhex('760186'))
    return '\n'.join(lines)


def test_capture_extraction_and_reject_missing_ack_truncation_or_ambiguity(tmp_path):
    path = tmp_path / 'capture.txt'; path.write_text(capture())
    assert hm.auth_from_file(str(path)) == AUTH
    path.write_text(capture() + '\n' + capture()); assert hm.auth_from_file(str(path)) == AUTH
    path.write_text(capture().rsplit('\n',1)[0])
    with pytest.raises(ValueError, match='acknowledged'): hm.auth_from_file(str(path))
    path.write_text(capture() + '\n' + capture(bytes(reversed(AUTH))))
    with pytest.raises(ValueError, match='unique'): hm.auth_from_file(str(path))
    lines = capture().splitlines(); del lines[20]; path.write_text('\n'.join(lines))
    with pytest.raises(ValueError, match='ISO-TP'): hm.auth_from_file(str(path))
    path.write_bytes(AUTH); assert hm.auth_from_file(str(path)) == AUTH
    path.write_bytes(AUTH[:-1])
    with pytest.raises(ValueError): hm.auth_from_file(str(path))


class Fake:
    def __init__(self, tune=ORIGINAL, *, wrong_echo=False, fail_block=None, fail_download=False, bad_readback=False):
        self.tune = bytearray(tune); self.pending = b''; self.sent = []; self.closed = False
        self.wrong_echo = wrong_echo; self.fail_block = fail_block; self.fail_download = fail_download; self.bad_readback = bad_readback
        self.writes = 0; self.auths = 0; self.downloading = False
    def close(self): self.closed = True
    def write(self, p):
        p = bytes(p); self.sent.append(p)
        if p == b'\x10\x03': self.pending = b'\x50\x03\x00\x32\x01\xf4'
        elif p == b'\x3e\x00': self.pending = b'\x7e\x00'
        elif p == b'\x27\x01': self.pending = b'\x67\x01\x12\x34'
        elif p == b'\x27\x02\x88\xdc': self.pending = b'\x67\x02'
        elif p == hm.AUTH_DOWNLOAD: self.pending = bytes.fromhex('74200802'); self.downloading = False
        elif p == b'\x36\x01' + AUTH: self.auths += 1; self.pending = bytes.fromhex('760186')
        elif p == bytes.fromhex('3400440000400000004000'):
            self.downloading = True
            self.pending = bytes.fromhex('7f3422') if self.fail_download else bytes.fromhex('74200102')
        elif p[0] == 0x22:
            self.pending = b'\x62' + p[1:] + bytes.fromhex(IDENTITY[p[1:].hex().upper()])
        elif p[0] == 0x35:
            addr = int.from_bytes(p[3:], 'big'); off = addr - hm.TUNE_READ_ADDRESS
            data = bytes(self.tune[off:off+256]) if 0 <= off < hm.TUNE_SIZE else bytes([addr // 256 % 256]) * 256
            if self.bad_readback and self.writes: data = bytes([data[0] ^ 1]) + data[1:]
            self.pending = b'\x75' + (p[1:6] + bytes([p[6] ^ 1]) if self.wrong_echo else p[1:]) + data + b'\xaa\xbb'
        elif p[0] == 0x36 and self.downloading:
            seq = p[1]; self.writes += 1
            self.tune[(seq-1)*256:seq*256] = p[2:]
            self.pending = bytes((0x76, seq if seq != self.fail_block else 0, 0))
        else: raise AssertionError(p[:11].hex())
    def read_frame(self, timeout):
        p = self.pending; self.pending = b''; return p


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'home'))
    auth = tmp_path / 'auth.bin'; auth.write_bytes(AUTH)
    original = tmp_path / 'original.bin'; original.write_bytes(ORIGINAL)
    target = tmp_path / 'edited.bin'; target.write_bytes(TARGET)
    return auth, original, target


def plan(files):
    a, o, t = files
    return hm.prepare('socketcan', 'can0', str(a), IDENTITY, str(o), str(t))


def install(monkeypatch, fake):
    monkeypatch.setattr(hm, '_open', lambda interface, channel: (fake, fake))


def test_read_checks_echo_header_and_trailer_and_reauth(files, monkeypatch):
    fake = Fake(); install(monkeypatch, fake)
    got = hm.read('socketcan', 'can0', str(files[0]), 'tune', True)
    assert bytes.fromhex(got['data_hex']) == ORIGINAL
    assert got['identity'] == IDENTITY and got['repeated_match']
    assert fake.auths == 4 and fake.closed
    assert sum(p[:1] == b'\x35' for p in fake.sent) == 128
    assert not any(p[:3] == bytes.fromhex('340044') and p[3:7] == bytes.fromhex('00004000') for p in fake.sent)
    fake = Fake(wrong_echo=True); install(monkeypatch, fake)
    with pytest.raises(TransportError, match='address echo'): hm.read('socketcan','can0',str(files[0]),'tune')
    assert fake.closed


def test_full_write_backup_and_readback(files, monkeypatch):
    fake = Fake(); install(monkeypatch, fake)
    result = hm.execute(plan(files))
    assert Path(result['backup_path']).read_bytes() == ORIGINAL
    assert bytes(fake.tune) == TARGET and fake.writes == 64 and fake.closed
    assert [p[1] for p in fake.sent if len(p) == 258 and p[0] == 0x36] == list(range(1,65))
    assert not any(p[0] in (0x37,0x11) for p in fake.sent)


def test_write_failures_are_fail_closed_and_report_uncertainty(files, monkeypatch):
    for fake in (Fake(tune=b'\x00' * hm.TUNE_SIZE), Fake(wrong_echo=True)):
        install(monkeypatch, fake)
        with pytest.raises(TransportError, match='No tune download sent'): hm.execute(plan(files))
        assert fake.writes == 0 and fake.closed
    for fake in (Fake(fail_download=True), Fake(fail_block=3), Fake(bad_readback=True)):
        install(monkeypatch, fake)
        with pytest.raises(TransportError, match='ECU state is uncertain.*Backup:'): hm.execute(plan(files))
        assert fake.closed
        if fake.fail_block: assert fake.writes == 3
    fake = Fake(); install(monkeypatch, fake)
    monkeypatch.setattr(hm, '_backup', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(TransportError, match='No tune download sent.*disk full'): hm.execute(plan(files))
    assert fake.writes == 0


def test_review_plan_api_single_use(files, monkeypatch):
    a,o,t = files; api = Api(Workstation(record=False)); calls = []
    monkeypatch.setattr(hm, 'execute', lambda p: calls.append(p) or {'ok': True})
    body = {'action':'prepare-write','confirm':True, 'confirm_write':True, 'interface':'socketcan','channel':'can0',
            'capture_path':str(a),'identity':IDENTITY,'original_path':str(o),'edited_path':str(t)}
    status, desc = api.post_tools_harley_memory(body)
    assert status == 200 and desc['changed_bytes'] == 1 and not calls
    status, _ = api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':desc['token']})
    assert status == 200 and len(calls) == 1
    assert api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':desc['token']})[0] == 400


def test_one_read_automatically_supplies_immutable_original_and_write(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    a, _, target = files
    status, result = api.post_tools_harley_memory({'action':'read', 'confirm':True, 'interface':'socketcan',
        'channel':'can0', 'capture_path':str(a), 'region':'tune'})
    assert status == 200 and result['read_token'] and result['original_tune_verified'] is False
    assert Path(result['original_tune_path']).read_bytes() == ORIGINAL
    assert sum(p[:1] == b'\x35' for p in fake.sent) == 64
    # The server takes identity, interface, auth and original from the read,
    # never from client-supplied fields or a changed capture file.
    a.write_bytes(bytes(reversed(AUTH)))
    status, desc = api.post_tools_harley_memory({'action':'prepare-from-read', 'confirm':True,
        'read_token':result['read_token'], 'edited_path':str(target), 'identity':{'fake':'00'},
        'interface':'invalid', 'capture_path':'/missing'})
    assert status == 200 and desc['single_read'] and desc['identity'] == IDENTITY
    assert desc['original_sha256'] == result['original_tune_sha256']
    assert api.post_tools_harley_memory({'action':'write','confirm':True,'token':desc['token']})[0] == 400
    # A rejected attempt consumes the plan, but not the read evidence.
    _, desc = api.post_tools_harley_memory({'action':'prepare-from-read', 'confirm':True,
        'read_token':result['read_token'], 'edited_path':str(target)})
    target.write_bytes(b'\x99' * hm.TUNE_SIZE)  # Reviewed plan must hold its own immutable bytes.
    status, output = api.post_tools_harley_memory({'action':'write','confirm':True,
        'confirm_write':True,'token':desc['token']})
    assert status == 200 and output['single_read'] and Path(output['backup_path']).read_bytes() == ORIGINAL
    assert fake.writes == 64 and bytes(fake.tune) == TARGET
    # One original read plus post-write readback; no fresh pre-write tune read.
    assert sum(p[:1] == b'\x35' for p in fake.sent) == 128
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})[0] == 400
    assert api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':desc['token']})[0] == 400


def test_calibration_read_automatically_extracts_tune_for_review(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    a, _, target = files
    status, result = api.post_tools_harley_memory({'action':'read','confirm':True,'interface':'socketcan',
        'channel':'can0','capture_path':str(a),'region':'calibration'})
    assert status == 200 and result['length'] == 0x28000 and result['read_token']
    assert Path(result['original_tune_path']).read_bytes() == ORIGINAL
    status, desc = api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})
    assert status == 200 and desc['single_read'] and desc['original_region'] == 'calibration'
    assert sum(p[:1] == b'\x35' for p in fake.sent) == 0x28000 // 256


def test_single_read_snapshot_invalidated_and_backup_tampering_fails_closed(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    a, _, target = files
    body = {'action':'read','confirm':True,'interface':'socketcan','channel':'can0','capture_path':str(a),'region':'tune'}
    _, result = api.post_tools_harley_memory(body)
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,'read_token':'bad','edited_path':str(target)})[0] == 400
    _, desc = api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})
    Path(result['original_tune_path']).write_bytes(b'\x00' * hm.TUNE_SIZE)
    monkeypatch.setattr(hm, '_open', lambda *_: pytest.fail('Changed backup must fail before opening bus'))
    with pytest.raises(TransportError, match='no connection'):
        api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':desc['token']})
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})[0] == 400


def test_single_read_identity_mismatch_refuses_write_and_keeps_saved_original(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    a, _, target = files
    _, result = api.post_tools_harley_memory({'action':'read','confirm':True,'interface':'socketcan',
        'channel':'can0','capture_path':str(a),'region':'tune'})
    _, desc = api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})
    other = Fake(); original_write = other.write
    def wrong_identity(payload):
        original_write(payload)
        if bytes(payload) == bytes.fromhex('22f1ed'):
            other.pending = bytes.fromhex('62f1eddeadbeef')
    other.write = wrong_identity; install(monkeypatch, other)
    with pytest.raises(TransportError, match='identity differs'):
        api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':desc['token']})
    assert other.writes == 0 and Path(result['original_tune_path']).read_bytes() == ORIGINAL
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})[0] == 400


def test_non_tune_read_and_failed_reread_invalidate_prior_evidence(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    a, _, target = files
    body = {'action':'read','confirm':True,'interface':'socketcan','channel':'can0','capture_path':str(a),'region':'tune'}
    _, result = api.post_tools_harley_memory(body)
    _, config = api.post_tools_harley_memory({**body, 'region':'config_low'})
    assert 'read_token' not in config
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})[0] == 400
    _, result = api.post_tools_harley_memory(body)
    install(monkeypatch, Fake(wrong_echo=True))
    with pytest.raises(TransportError): api.post_tools_harley_memory(body)
    assert api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':result['read_token'],'edited_path':str(target)})[0] == 400


def test_failed_automatic_save_keeps_read_but_cannot_prepare(files, monkeypatch):
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    monkeypatch.setattr(hm, '_backup', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    status, result = api.post_tools_harley_memory({'action':'read','confirm':True,'interface':'socketcan',
        'channel':'can0','capture_path':str(files[0]),'region':'tune'})
    assert status == 200 and bytes.fromhex(result['data_hex']) == ORIGINAL
    assert 'disk full' in result['write_review_unavailable'] and 'read_token' not in result


def test_file_identity_and_adapter_validation(files):
    a,o,t = files
    for identity in ({}, {'F1EA':'00', 'F1ED':'00', 'F1F5':'z'}, {'F1EA':'00', 'F1ED':'00', 'F1F5':'00', 'EXTRA':'00'}):
        with pytest.raises(ValueError): hm.prepare('socketcan','can0',str(a),identity,str(o),str(t))
    with pytest.raises(ValueError): hm.prepare('socketcan','bad name',str(a),IDENTITY,str(o),str(t))
    assert hm._channel('pcan', 'PCAN_USBBUS1') == 'PCAN_USBBUS1'
    with pytest.raises(ValueError): hm._channel('pcan', 'PCAN_USBBUS17')
    t.write_bytes(TARGET[:-1])
    with pytest.raises(ValueError, match='16384'): plan(files)


def test_protocol_rejects_malformed_download_and_mismatched_block(files):
    class BadDownload(Fake):
        def write(self, p):
            super().write(p)
            if bytes(p) == hm.AUTH_DOWNLOAD: self.pending = bytes.fromhex('742007D6')
    fake = BadDownload(); s = hm.Session(fake, fake, AUTH)
    with pytest.raises(TransportError, match='too small'): s.authenticate()
    assert not fake.auths
    fake = Fake(fail_block=1); s = hm.Session(fake, fake, AUTH)
    with pytest.raises(TransportError, match='block 1'): s.write_tune(TARGET)
    assert fake.writes == 1


def test_identity_change_blocks_tune_download(files, monkeypatch):
    fake = Fake(); install(monkeypatch, fake)
    wrong = dict(IDENTITY); wrong['F1ED'] = 'DEADBEEF'
    a,o,t = files
    p = hm.prepare('socketcan','can0',str(a),wrong,str(o),str(t))
    with pytest.raises(TransportError, match='identity differs'): hm.execute(p)
    assert fake.writes == 0
    assert not any(q == bytes.fromhex('3400440000400000004000') for q in fake.sent)


def test_api_invalid_confirmation_does_not_touch_ecu(files, monkeypatch):
    api = Api(Workstation(record=False)); touched = []
    monkeypatch.setattr(hm,'read',lambda *a: touched.append(a))
    assert api.post_tools_harley_memory({'action':'read'})[0] == 400
    assert api.post_tools_harley_memory({'action':'write','confirm':True,'confirm_write':True,'token':'fake'})[0] == 400
    assert not touched


def test_bad_capture_does_not_open_bus(files, monkeypatch):
    files[0].write_bytes(b'bad')
    monkeypatch.setattr(hm, '_open', lambda *_: pytest.fail('Must not open bus'))
    with pytest.raises(ValueError): hm.read('socketcan','can0',str(files[0]),'tune')


def test_synthetic_single_read_map_export_review_write_full_stack(files, monkeypatch, tmp_path):
    """Synthetic tune read, user XDF edit/export, plan, download and readback."""
    import hashlib
    api = Api(Workstation(record=False)); fake = Fake(); install(monkeypatch, fake)
    status, read = api.post_tools_harley_memory({'action':'read','confirm':True,'interface':'socketcan',
        'channel':'can0','capture_path':str(files[0]),'region':'tune','compare_repeat':False})
    assert status == 200 and read['read_token']
    xdf = tmp_path / 'user-harley.xdf'
    xdf.write_text('''<XDFFORMAT><XDFHEADER><deftitle>Synthetic Harley</deftitle><DEFAULTS signed="0" lsbfirst="0"/></XDFHEADER>
<XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
<XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>''')
    body = {'path':read['original_tune_path'], 'xdf':str(xdf), 'address_base':0,
            'expected_source_sha256':read['original_tune_sha256'], 'expected_xdf_sha256':hashlib.sha256(xdf.read_bytes()).hexdigest(),
            'changes':[{'kind':'table','id':'fuel','row':0,'col':1,'expected_raw':ORIGINAL[33],'value':42}]}
    status, preview = api.post_maps_research_preview(body); assert status == 200
    status, saved = api.post_maps_harley_research_export({**body,'accept_research_only':True,
        'expected_candidate_sha256':preview['candidate_sha256']})
    assert status == 201 and Path(saved['path']).read_bytes()[33] == 42
    status, reviewed = api.post_tools_harley_memory({'action':'prepare-from-read','confirm':True,
        'read_token':read['read_token'],'edited_path':saved['path']})
    assert status == 200 and not fake.writes
    status, result = api.post_tools_harley_memory({'action':'write','confirm':True,
        'confirm_write':True,'token':reviewed['token']})
    assert status == 200 and result['single_read'] and fake.tune[33] == 42 and fake.writes == 64
    assert Path(read['original_tune_path']).read_bytes() == ORIGINAL
