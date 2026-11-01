"""Synthetic DDFI SET integration tests; no physical ECM or adapter tested."""
import hashlib
import sys
from functools import reduce
from operator import xor
from types import SimpleNamespace

import pytest

from guzzionboard import buell_burn, buell_ddfi
from guzzionboard.server import Api
from guzzionboard.transports.base import TransportError
from guzzionboard.workstation import Workstation

VERSION = 'BUEIB310 12-11-03'


def reply(data=b'', *, status=6, ecm=0x42):
    body = bytes((ecm, 0, len(data) + 2, 0xff, 2, status)) + data + b'\x03'
    return b'\x01' + body + bytes((reduce(xor, body, 0),))


class EcmSerial:
    def __init__(self, image, *, version=VERSION, rpm=0, fail_set=False, bad_readback=False, rpm_sequence=None, ecm=0x42, fail_at=None, runtime_length=98):
        self.pending = bytearray(); self.sent = []; self.closed = False
        self.ecm = ecm; self.fail_at = fail_at; self.runtime_length = runtime_length; self.version = version; self.rpm = rpm; self.rpm_sequence = list(rpm_sequence or []); self.fail_set = fail_set; self.bad_readback = bad_readback
        self.writes = 0; self.pages = {}; cursor = 0
        for number, length in buell_ddfi.IMAGE_LAYOUTS['BUEIB']:
            if number == 0: continue
            self.pages[number] = bytearray(image[cursor:cursor+length]); cursor += length
        self.pages[0] = bytearray(image[cursor:])

    def reset_input_buffer(self): pass
    def close(self): self.closed = True
    def read(self, n):
        n = min(n, 3, len(self.pending)); data = bytes(self.pending[:n]); del self.pending[:n]; return data
    def write(self, wire):
        self.sent.append(wire); p = wire[6:-2]
        if p == b'V':
            result = reply(self.version.encode(), ecm=self.ecm)
        elif p == b'C':
            data = bytearray(self.runtime_length); rpm = self.rpm_sequence.pop(0) if self.rpm_sequence else self.rpm; data[4:6] = rpm.to_bytes(2, 'little'); result = reply(data, ecm=self.ecm)
        elif p[0] == 0x52:
            _, offset, page, length = p
            start = offset - (256 - len(self.pages[0])) if page == 0 else offset
            data = bytes(self.pages[page][start:start + length])
            if self.bad_readback and self.writes and page == 4 and offset == 208:
                data = bytes([data[0] ^ 1]) + data[1:]
            result = reply(data, ecm=self.ecm)
        elif p[0] == 0x57:
            _, offset, page, *data = p
            assert page > 0 and page < 32
            self.pages[page][offset:offset + len(data)] = data
            self.writes += 1
            result = reply(status=0x15 if self.fail_set or self.fail_at == self.writes else 6, ecm=self.ecm)
        else: raise AssertionError(p.hex())
        self.pending.extend(result); return len(wire)


def install(monkeypatch, conn):
    monkeypatch.setattr(buell_ddfi.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=lambda **kw: conn, SerialException=OSError))


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'appdata'))
    data = bytes(i & 255 for i in range(1210))
    original = tmp_path / 'BUEIB-original.xpr'; original.write_bytes(data)
    edited = tmp_path / 'edited.bin'; new = bytearray(data); new[884] = 42; new[886] = 43; edited.write_bytes(new)
    return original, edited, data, bytes(new)


def make_plan(files):
    original, edited, _, _ = files
    return buell_burn.prepare('/dev/ttyUSB0', 'stock', VERSION, str(original), str(edited))


def test_map_write_backup_readback_and_preservation(files, monkeypatch):
    _, _, original, target = files
    plan = make_plan(files); conn = EcmSerial(original); install(monkeypatch, conn)
    result = buell_burn.execute(plan)
    backup = __import__('pathlib').Path(result['backup_path'])
    assert backup.read_bytes() == original
    assert result['backup_sha256'] == hashlib.sha256(original).hexdigest()
    assert result['edited_bytes'] == 2 and result['chunks_written'] == 1
    assert conn.closed and conn.writes == 1
    sent = [wire[6:-2] for wire in conn.sent if wire[6] == 0x57]
    assert len(sent) == 1 and sent[0][:3] == bytes((0x57, 208, 4))
    assert conn.pages[4][208:224] == target[878:894]
    assert all(p[2] != 32 for p in (wire[6:-2] for wire in conn.sent) if p[0] in (0x52, 0x57))


def test_no_set_on_running_version_mismatch_or_edited_cell_conflict(files, monkeypatch):
    _, _, original, _ = files; plan = make_plan(files)
    for conn in (EcmSerial(original, rpm=1250), EcmSerial(original, version='BUEIB999'),
                 EcmSerial(original, rpm_sequence=[0, 1250]),
                 EcmSerial(original, runtime_length=97),
                 EcmSerial(original[:884] + b'\x00' + original[885:])):
        install(monkeypatch, conn)
        with pytest.raises(TransportError, match='before SET'):
            buell_burn.execute(plan)
        assert conn.writes == 0 and conn.closed


def test_set_error_and_readback_mismatch_are_uncertain_and_never_retried(files, monkeypatch):
    _, _, original, _ = files; plan = make_plan(files)
    for conn in (EcmSerial(original, fail_set=True), EcmSerial(original, bad_readback=True)):
        install(monkeypatch, conn)
        with pytest.raises(TransportError, match='uncertain.*Backup:'):
            buell_burn.execute(plan)
        assert conn.writes == 1 and conn.closed


def test_prepare_rejects_non_map_changes_wrong_id_and_size(files):
    original, edited, data, _ = files
    for at in (0, len(data)-1, 883):  # ordinary metadata, page zero, padding byte
        modified = bytearray(data); modified[at] ^= 1; edited.write_bytes(modified)
        with pytest.raises(ValueError, match='Only this ECM'):
            make_plan(files)
    edited.write_bytes(data[:-1])
    with pytest.raises(ValueError, match='exactly'):
        make_plan(files)
    edited.write_bytes(data[:884] + b'\x2a' + data[885:])
    bad_name = original.with_name('unknown.xpr'); bad_name.write_bytes(data)
    with pytest.raises(ValueError, match='filename must begin'):
        buell_burn.prepare('/dev/ttyUSB0', 'stock', VERSION, str(bad_name), str(edited))
    for page in (0, 32):
        with pytest.raises(ValueError): buell_burn._set_request(0x42, page, 0, b'x')
    with pytest.raises(ValueError): buell_burn._set_request(0x42, 1, 1, b'x')


def test_api_write_plan_is_explicit_and_single_use(files, monkeypatch):
    original, edited, _, _ = files
    api = Api(Workstation(record=False)); calls = []
    monkeypatch.setattr(buell_burn, 'execute', lambda p: calls.append(p) or {'written': True})
    body = {'action': 'prepare-write', 'confirm': True, 'port': '/dev/ttyUSB0', 'mode': 'stock',
            'version': VERSION, 'original_path': str(original), 'edited_path': str(edited)}
    status, reviewed = api.post_tools_buell_ddfi(body)
    assert status == 200 and len(reviewed['changes']) == 2 and not calls
    body = {'action': 'write', 'confirm': True, 'token': reviewed['token']}
    assert api.post_tools_buell_ddfi(body)[0] == 400 and not calls
    assert api.post_tools_buell_ddfi({**body, 'confirm_write': True})[0] == 200 and len(calls) == 1
    assert api.post_tools_buell_ddfi({**body, 'confirm_write': True})[0] == 400


def test_backup_failure_blocks_all_writes(files, monkeypatch):
    _, _, original, _ = files; conn = EcmSerial(original); install(monkeypatch, conn)
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr(buell_burn, '_backup', fail)
    with pytest.raises(TransportError, match='before SET.*disk full'):
        buell_burn.execute(make_plan(files))
    assert conn.writes == 0 and conn.closed


def test_all_ids_have_matching_writer_definitions_and_runtime_lengths():
    assert set(buell_burn.MAP_DEFINITIONS) == set(buell_ddfi.IMAGE_LAYOUTS) == set(buell_burn.RUNTIME_LENGTHS)
    for key in buell_burn.MAP_DEFINITIONS:
        name, allowed = buell_burn._allowed(key)
        size = sum(n for p, n in buell_ddfi.IMAGE_LAYOUTS[key] if p != 0)
        assert name.endswith('_source_research.xdf') and allowed
        assert min(allowed) >= 0 and max(allowed) < size


def test_expired_or_invalid_token_does_not_write(files, monkeypatch):
    original, edited, _, _ = files; calls = []
    api = Api(Workstation(record=False))
    monkeypatch.setattr(buell_burn, 'execute', lambda p: calls.append(p))
    request = {'action': 'prepare-write', 'confirm': True, 'port': '/dev/ttyUSB0', 'mode': 'stock',
               'version': VERSION, 'original_path': str(original), 'edited_path': str(edited)}
    _, reviewed = api.post_tools_buell_ddfi(request)
    now = __import__('time').monotonic()
    token, _, plan = api._buell_write_plan
    api._buell_write_plan = (token, now - 1, plan)
    write = {'action': 'write', 'confirm': True, 'confirm_write': True, 'token': reviewed['token']}
    assert api.post_tools_buell_ddfi(write)[0] == 400 and not calls
    _, reviewed = api.post_tools_buell_ddfi(request)
    assert api.post_tools_buell_ddfi({**write, 'token': 'wrong'})[0] == 400
    assert api.post_tools_buell_ddfi({**write, 'token': reviewed['token']})[0] == 400 and not calls


def test_buell_write_is_visible_to_desktop_close_guard(files, monkeypatch):
    from guzzionboard.desktop import DesktopApp
    app = DesktopApp(no_window=True, record=False)
    try:
        app.start(); api = app.handler.api
        api._buell_writing.set()
        assert app.busy()['name'] == 'Buell EEPROM write'
        assert app._on_window_closing() is False
        assert app.bridge.quit()['ok'] is False
        api._buell_writing.clear()
        assert app.busy()['running'] is False
    finally:
        app.shutdown()


def test_complete_api_path_uses_reviewed_bytes_and_exposes_busy(files, monkeypatch):
    original, edited, data, target = files
    conn = EcmSerial(data); install(monkeypatch, conn)
    api = Api(Workstation(record=False))
    backup = buell_burn._backup
    def assert_busy(*args):
        assert api._buell_writing.is_set()
        return backup(*args)
    monkeypatch.setattr(buell_burn, '_backup', assert_busy)
    status, review = api.post_tools_buell_ddfi({'action': 'prepare-write', 'confirm': True,
        'port': '/dev/ttyUSB0', 'mode': 'stock', 'version': VERSION,
        'original_path': str(original), 'edited_path': str(edited)})
    assert status == 200 and conn.sent == []
    # A later disk change cannot silently alter the plan the operator reviewed.
    edited.write_bytes(data)
    status, result = api.post_tools_buell_ddfi({'action': 'write', 'confirm': True,
        'confirm_write': True, 'token': review['token']})
    assert status == 200 and result['target_sha256'] == hashlib.sha256(target).hexdigest()
    assert conn.pages[4][214] == target[884] and conn.writes == 1
    assert not api._buell_writing.is_set()


def test_factory_race_source_layout_writes_the_selected_map(tmp_path, monkeypatch):
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'data'))
    data = bytes(i & 255 for i in range(1210))
    original = tmp_path / 'B2RIB-original.xpr'; original.write_bytes(data)
    edited = tmp_path / 'edit.bin'; new = bytearray(data); new[670] = 42; edited.write_bytes(new)
    plan = buell_burn.prepare('/dev/ttyUSB0', 'factory_race', 'B2RIB123 TEST', str(original), str(edited))
    conn = EcmSerial(data, version=plan.version, ecm=0x55); install(monkeypatch, conn)
    result = buell_burn.execute(plan)
    assert result['chunks_written'] == 1 and conn.pages[4][0] == 42
    assert all(frame[2] == 0x55 for frame in conn.sent)


def test_second_chunk_failure_reports_partial_and_retains_backup(files, monkeypatch):
    original, edited, data, _ = files
    new = bytearray(data); new[670] = 42; new[884] = 43; edited.write_bytes(new)
    plan = make_plan(files); conn = EcmSerial(data, fail_at=2); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='uncertain after 2 SET attempt') as exc:
        buell_burn.execute(plan)
    assert conn.writes == 2 and conn.closed
    backup = str(exc.value).split('Backup: ')[1].split('. ')[0]
    assert __import__('pathlib').Path(backup).read_bytes() == data


def single_read(api):
    status, result = api.post_tools_buell_ddfi({'action': 'image', 'confirm': True,
        'port': '/dev/ttyUSB0', 'mode': 'stock', 'version': VERSION})
    assert status == 200, result
    assert result['original_verified'] is False and result['read_token']
    return result


def test_one_read_api_to_review_and_write(files, monkeypatch):
    from pathlib import Path
    _, edited, data, target = files
    connections = []
    def open_serial(**kwargs):
        conn = EcmSerial(data); connections.append(conn); return conn
    monkeypatch.setattr(buell_ddfi.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=open_serial, SerialException=OSError))
    api = Api(Workstation(record=False))
    read = single_read(api)
    assert Path(read['original_path']).read_bytes() == data
    assert read['map_xdf'] == 'BUEIB_source_research.xdf'
    assert len(connections) == 1 and connections[0].writes == 0
    status, review = api.post_tools_buell_ddfi({'action': 'prepare-from-read', 'confirm': True,
        'read_token': read['read_token'], 'edited_path': str(edited)})
    assert status == 200 and review['single_read'] and len(connections) == 1
    assert review['base_sha256'] == hashlib.sha256(data).hexdigest()
    edited.write_bytes(data)  # the immutable reviewed target, not this later file, is written
    request = {'action': 'write', 'confirm': True, 'confirm_write': True, 'token': review['token']}
    status, result = api.post_tools_buell_ddfi(request)
    assert status == 200, result
    assert result['single_read'] and result['backup_path'] == read['original_path']
    assert result['target_sha256'] == hashlib.sha256(target).hexdigest()
    conn = connections[1]
    reads = [frame[6:-2] for frame in conn.sent if frame[6] == 0x52]
    assert reads == [bytes((0x52, 208, 4, 16))] * 3  # precheck, immediate check, readback
    assert conn.writes == 1 and conn.pages[4][214] == target[884]
    assert api.post_tools_buell_ddfi(request)[0] == 400
    assert api.post_tools_buell_ddfi({'action':'prepare-from-read', 'confirm':True,
        'read_token':read['read_token'], 'edited_path':str(edited)})[0] == 400


def test_one_read_original_tampering_is_rejected_before_review_and_write(files, monkeypatch):
    from pathlib import Path
    _, edited, data, _ = files
    install(monkeypatch, EcmSerial(data))
    api = Api(Workstation(record=False)); read = single_read(api)
    original = Path(read['original_path'])
    original.write_bytes(bytes(len(data)))
    prepare = {'action': 'prepare-from-read', 'confirm': True,
               'read_token': read['read_token'], 'edited_path': str(edited)}
    with pytest.raises(ValueError, match='original changed'):
        api.post_tools_buell_ddfi(prepare)
    original.write_bytes(data)
    status, review = api.post_tools_buell_ddfi(prepare); assert status == 200
    original.write_bytes(bytes(len(data)))
    with pytest.raises(TransportError, match='original changed'):
        api.post_tools_buell_ddfi({'action':'write', 'confirm':True,
            'confirm_write':True, 'token':review['token']})


def test_one_read_prechecks_all_chunks_before_first_set(files, monkeypatch):
    _, edited, data, _ = files
    new = bytearray(data); new[670] = 42; new[884] = 43; edited.write_bytes(new)
    evidence = buell_burn.capture_original('/dev/ttyUSB0', 'stock', {
        'version':VERSION, 'kind':'eeprom-image', 'layout':'BUEIB', 'length':len(data),
        'data_hex':data.hex(), 'sha256':hashlib.sha256(data).hexdigest()})
    plan = buell_burn.prepare_from_read(evidence, str(edited))
    changed = bytearray(data); changed[885] ^= 1  # unchanged neighbor in later chunk
    conn = EcmSerial(bytes(changed)); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='no write sent'):
        buell_burn.execute(plan)
    assert conn.writes == 0


def test_one_read_later_mismatch_can_be_partial(files, monkeypatch):
    _, edited, data, _ = files
    new = bytearray(data); new[670] = 42; new[884] = 43; edited.write_bytes(new)
    evidence = buell_burn.capture_original('/dev/ttyUSB0', 'stock', {
        'version':VERSION, 'kind':'eeprom-image', 'layout':'BUEIB', 'length':len(data),
        'data_hex':data.hex(), 'sha256':hashlib.sha256(data).hexdigest()})
    conn = EcmSerial(data)
    write = conn.write
    def change_after_first_set(wire):
        result = write(wire)
        if wire[6] == 0x57 and conn.writes == 1:
            conn.pages[4][215] ^= 1
        return result
    conn.write = change_after_first_set; install(monkeypatch, conn)
    with pytest.raises(TransportError, match='uncertain after 1 SET attempt'):
        buell_burn.execute(buell_burn.prepare_from_read(evidence, str(edited)))
    assert conn.writes == 1


def test_new_buell_read_invalidates_old_evidence_and_plan(files, monkeypatch):
    _, edited, data, _ = files
    monkeypatch.setattr(buell_ddfi.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=lambda **kw:EcmSerial(data), SerialException=OSError))
    api = Api(Workstation(record=False)); read = single_read(api)
    prep = {'action':'prepare-from-read', 'confirm':True, 'read_token':read['read_token'], 'edited_path':str(edited)}
    status, review = api.post_tools_buell_ddfi(prep); assert status == 200
    assert api.post_tools_buell_ddfi({'action':'identify', 'confirm':True, 'port':'/dev/ttyUSB0', 'mode':'stock'})[0] == 200
    assert api.post_tools_buell_ddfi(prep)[0] == 400
    assert api.post_tools_buell_ddfi({'action':'write', 'confirm':True, 'confirm_write':True, 'token':review['token']})[0] == 400


def test_failed_automatic_save_still_returns_image_without_evidence(files, monkeypatch):
    _, _, data, _ = files; install(monkeypatch, EcmSerial(data))
    monkeypatch.setattr(buell_burn, '_backup', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    api = Api(Workstation(record=False))
    status, result = api.post_tools_buell_ddfi({'action':'image', 'confirm':True,
        'port':'/dev/ttyUSB0', 'mode':'stock', 'version':VERSION})
    assert status == 200 and result['data_hex'] == data.hex().upper()
    assert 'disk full' in result['write_review_unavailable'] and 'read_token' not in result


def test_one_read_rejects_running_engine_and_wrong_version(files, monkeypatch):
    _, edited, data, _ = files
    evidence = buell_burn.capture_original('/dev/ttyUSB0', 'stock', {
        'version':VERSION, 'kind':'eeprom-image', 'layout':'BUEIB', 'length':len(data),
        'data_hex':data.hex(), 'sha256':hashlib.sha256(data).hexdigest()})
    plan = buell_burn.prepare_from_read(evidence, str(edited))
    for conn in (EcmSerial(data, rpm=1500), EcmSerial(data, version='BUEIB999')):
        install(monkeypatch, conn)
        with pytest.raises(TransportError, match='before SET'):
            buell_burn.execute(plan)
        assert conn.writes == 0 and conn.closed


def test_bad_image_cannot_create_single_read_evidence(files):
    _, _, data, _ = files
    result = {'version':VERSION, 'kind':'eeprom-image', 'layout':'BUEIB', 'length':len(data),
              'data_hex':data.hex(), 'sha256':hashlib.sha256(data).hexdigest()}
    for override in ({'sha256':'wrong'}, {'length':len(data)-1}, {'data_hex':'xx'},
                     {'layout':'BUEIA'}, {'kind':'range'}):
        with pytest.raises(ValueError):
            buell_burn.capture_original('/dev/ttyUSB0', 'stock', {**result, **override})


def test_all_single_read_handoff_definitions_are_packaged():
    from guzzionboard.maps import BUNDLED_XDF_DIR, XdfFile
    for ecm_id, geometry in buell_burn.MAP_DEFINITIONS.items():
        path = BUNDLED_XDF_DIR / 'buell' / f'{geometry}_source_research.xdf'
        xdf = XdfFile.from_file(path)
        assert xdf.tables, ecm_id
        assert ecm_id in buell_ddfi.IMAGE_LAYOUTS


def test_synthetic_one_read_map_export_review_write_full_stack(files, monkeypatch):
    """Single synthetic read -> source map export -> review -> serial SET/readback."""
    from pathlib import Path
    from guzzionboard.maps import BUNDLED_XDF_DIR
    _, _, data, _ = files
    connections = []
    def open_serial(**_):
        conn = EcmSerial(data); connections.append(conn); return conn
    monkeypatch.setattr(buell_ddfi.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=open_serial, SerialException=OSError))
    api = Api(Workstation(record=False)); read = single_read(api)
    xdf = BUNDLED_XDF_DIR / 'buell' / read['map_xdf']
    body = {'path':read['original_path'], 'xdf':str(xdf), 'address_base':0,
            'expected_source_sha256':read['sha256'], 'expected_xdf_sha256':hashlib.sha256(xdf.read_bytes()).hexdigest(),
            'changes':[{'kind':'table','title':'Tab_Fuel_Front','row':1,'col':0,'expected_raw':data[884],'value':42}]}
    status, preview = api.post_maps_research_preview(body)
    assert status == 200 and len(connections) == 1
    status, saved = api.post_maps_research_export({**body,'region_start':0,'region_end':len(data),
        'accept_research_only':True,'expected_candidate_sha256':preview['candidate_sha256']})
    assert status == 201 and Path(saved['path']).read_bytes()[884] == 42
    status, plan = api.post_tools_buell_ddfi({'action':'prepare-from-read','confirm':True,
        'read_token':read['read_token'],'edited_path':saved['path']})
    assert status == 200 and plan['single_read'] and len(connections) == 1
    assert connections[0].writes == 0
    status, result = api.post_tools_buell_ddfi({'action':'write','confirm':True,
        'confirm_write':True,'token':plan['token']})
    assert status == 200 and result['single_read'] and len(connections) == 2
    assert connections[1].writes == 1 and connections[1].pages[4][214] == 42
    assert Path(read['original_path']).read_bytes() == data
