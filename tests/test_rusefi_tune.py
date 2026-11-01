"""Synthetic-only rusEFI calibration tests; no physical ECU exercised."""
import hashlib
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

from guzzionboard import rusefi_tune as mod
from guzzionboard.server import Api
from guzzionboard.transports.base import TransportError
from guzzionboard.workstation import Workstation

SIG = 'rusEFI test.synthetic.123'
INI = '''[TunerStudio]
signature = "rusEFI test.synthetic.123"
[Constants]
nPages = 2
pageSize = 300, 256
pageIdentifier = "\\x00\\x00", "\\x00\\x01"
pageReadCommand = "R%2i%2o%2c", "R%2i%2o%2c"
pageChunkWrite = "C%2i%2o%2c%v", "C%2i%2o%2c%v"
burnCommand = "B%2i", ""
crc32CheckCommand = "k%2i%2o%2c", "k%2i%2o%2c"
'''


def frame(data):
    return len(data).to_bytes(2, 'big') + data + zlib.crc32(data).to_bytes(4, 'big')


class Device:
    def __init__(self, data):
        self.data = bytearray(data); self.sent = []; self.pending = bytearray(); self.closed = False
        self.version = SIG; self.burns = 0; self.writes = 0; self.bad_readback = False; self.fail_write = False
    def reset_input_buffer(self): pass
    def close(self): self.closed = True
    def read(self, count):
        n = min(count, 3, len(self.pending)); result = bytes(self.pending[:n]); del self.pending[:n]; return result
    def write(self, wire):
        length = int.from_bytes(wire[:2], 'big'); payload = wire[2:2+length]
        assert len(wire) == length+6 and zlib.crc32(payload) == int.from_bytes(wire[-4:], 'big')
        self.sent.append(payload); op = payload[:1]
        if op == b'S': result = b'\x00' + self.version.encode() + b'\x00'
        elif op in (b'R', b'k', b'C'):
            page, offset, count = struct.unpack('<HHH', payload[1:7]); assert page == 0
            if op == b'R':
                out = bytes(self.data[offset:offset+count])
                if self.bad_readback and self.writes: out = bytes([out[0]^1]) + out[1:]
                result = b'\x00' + out
            elif op == b'k': result = b'\x00' + zlib.crc32(self.data[offset:offset+count]).to_bytes(4, 'big')
            else:
                assert len(payload) == count + 7
                self.writes += 1; self.data[offset:offset+count] = payload[7:]
                result = b'\x83' if self.fail_write else b'\x00'
        elif op == b'B':
            assert payload == b'B\x00\x00'; self.burns += 1; result = b'\x04'
        else: raise AssertionError(payload)
        self.pending.extend(frame(result)); return len(wire)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'data'))
    monkeypatch.setattr(mod.wire.sys, 'platform', 'linux')
    monkeypatch.setattr(mod.time, 'sleep', lambda _: None)
    data = bytes((i % 251)+1 for i in range(300)); device = Device(data)
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=lambda **kw:device, SerialException=OSError))
    edited = tmp_path / 'edit.bin'; target = bytearray(data); target[10:12] = b'\x09\x09'; target[150] = 42; edited.write_bytes(target)
    return data, device, edited, bytes(target)


def test_ini_requires_matching_unambiguous_paged_commands():
    assert mod.parse_ini(INI) == (SIG, 300)
    for text in (INI.replace('300, 256', '0, 256'), INI.replace('"B%2i"', '"B"'),
                 INI.replace('"\\x00\\x00"', '"\\x01\\x00"'),
                 INI.replace('"C%2i%2o%2c%v"', '"X"'),
                 INI + '\npageSize=301\n', INI.replace('pageSize =', '#if FOO\npageSize =').replace('pageIdentifier =', '#endif\npageIdentifier =')):
        with pytest.raises(ValueError): mod.parse_ini(text)


def test_one_read_prepare_write_burn_and_working_crc(setup):
    data, device, edited, target = setup
    api = Api(Workstation(record=False))
    status, read = api.post_tools_rusefi_read({'action':'read-calibration', 'confirm':True,
        'port':'/dev/ttyACM0', 'baud':115200, 'ini':INI})
    assert status == 200 and read['original_verified'] is False
    assert Path(read['original_path']).read_bytes() == data
    assert [p[:1] for p in device.sent] == [b'S', b'R', b'R', b'R']
    status, review = api.post_tools_rusefi_read({'action':'prepare-calibration', 'confirm':True,
        'confirm_tuning':True, 'read_token':read['read_token'], 'edited_path':str(edited)})
    assert status == 200 and review['changed_bytes'] == 3 and device.writes == 0
    edited.write_bytes(data)  # staged bytes cannot change after review
    request = {'action':'write-calibration','confirm':True,'confirm_tuning':True,'confirm_write':True,'token':review['token']}
    status, result = api.post_tools_rusefi_read(request)
    assert status == 200 and result['target_sha256'] == hashlib.sha256(target).hexdigest()
    assert device.data == target and device.writes == 2 and device.burns == 1
    assert [p[:1] for p in device.sent[4:]] == [b'S',b'k',b'R',b'C',b'R',b'R',b'C',b'R',b'k',b'B',b'k',b'k']
    assert [p for p in device.sent if p[:1] == b'C'] == [b'C\x00\x00\x0a\x00\x02\x00\x09\x09', b'C\x00\x00\x96\x00\x01\x00\x2a']
    assert [p for p in device.sent if p[:1] == b'B'] == [b'B\x00\x00']
    assert api.post_tools_rusefi_read(request)[0] == 400
    assert api.post_tools_rusefi_read({'action':'prepare-calibration','confirm':True,'confirm_tuning':True,
        'read_token':read['read_token'],'edited_path':str(edited)})[0] == 400


def test_locked_zeros_wrong_signature_or_original_conflict_never_write(setup):
    data, device, edited, _ = setup
    device.data[:] = bytes(len(data))
    with pytest.raises(TransportError, match='all zero'):
        mod.read_original('/dev/ttyACM0', 115200, INI)
    device.data[:] = data
    result, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    device.version = 'rusEFI different'
    with pytest.raises(TransportError, match='No chunk or burn'):
        mod.execute(mod.prepare(evidence, str(edited)))
    device.version = SIG; device.data[200] ^= 1
    with pytest.raises(TransportError, match='CRC differs'):
        mod.execute(mod.prepare(evidence, str(edited)))
    assert device.writes == 0 and device.burns == 0


def test_write_failure_and_readback_mismatch_never_burn_or_retry(setup):
    data, device, edited, _ = setup
    _, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    plan = mod.prepare(evidence, str(edited))
    device.fail_write = True
    with pytest.raises(TransportError, match='Uncertain.*burn was not attempted'):
        mod.execute(plan)
    assert device.writes == 1 and device.burns == 0
    device.data[:] = data; device.writes = 0; device.fail_write = False; device.bad_readback = True
    with pytest.raises(TransportError, match='RAM readback mismatch'):
        mod.execute(plan)
    assert device.writes == 1 and device.burns == 0


def test_saved_original_tamper_and_evidence_expiry(setup):
    data, device, edited, _ = setup; api = Api(Workstation(record=False))
    _, read = api.post_tools_rusefi_read({'action':'read-calibration','confirm':True,'port':'/dev/ttyACM0','baud':115200,'ini':INI})
    original = Path(read['original_path']); original.write_bytes(bytes(len(data)))
    body = {'action':'prepare-calibration','confirm':True,'confirm_tuning':True,'read_token':read['read_token'],'edited_path':str(edited)}
    with pytest.raises(ValueError, match='original changed'): api.post_tools_rusefi_read(body)
    original.write_bytes(data); _, review = api.post_tools_rusefi_read(body)
    token, _, plan = api._rusefi_plan; api._rusefi_plan = (token, 0, plan)
    assert api.post_tools_rusefi_read({'action':'write-calibration','confirm':True,'confirm_tuning':True,'confirm_write':True,'token':review['token']})[0] == 400
    assert not device.writes


def test_new_identify_invalidates_evidence_and_plan(setup):
    data, device, edited, _ = setup; api = Api(Workstation(record=False))
    _, read = api.post_tools_rusefi_read({'action':'read-calibration','confirm':True,'port':'/dev/ttyACM0','baud':115200,'ini':INI})
    body = {'action':'prepare-calibration','confirm':True,'confirm_tuning':True,'read_token':read['read_token'],'edited_path':str(edited)}
    _, review = api.post_tools_rusefi_read(body)
    assert api.post_tools_rusefi_read({'action':'identify','confirm':True,'port':'/dev/ttyACM0','baud':115200})[0] == 200
    assert api.post_tools_rusefi_read(body)[0] == 400
    assert api.post_tools_rusefi_read({'action':'write-calibration','confirm':True,'confirm_tuning':True,'confirm_write':True,'token':review['token']})[0] == 400
    assert not device.writes


def test_original_tamper_after_review_blocks_connection(setup):
    data, device, edited, _ = setup
    _, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    plan = mod.prepare(evidence, str(edited)); old_frames = len(device.sent)
    Path(evidence.backup_path).write_bytes(bytes(len(data)))
    with pytest.raises(TransportError, match='original changed'):
        mod.execute(plan)
    assert len(device.sent) == old_frames and not device.writes and not device.burns


def test_changed_ram_after_write_blocks_burn(setup):
    data, device, edited, _ = setup
    _, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    plan = mod.prepare(evidence, str(edited))
    write = device.write
    def corrupt_extra(frame):
        result = write(frame)
        if frame[2:3] == b'C' and device.writes == 2:
            device.data[200] ^= 1
        return result
    device.write = corrupt_extra
    with pytest.raises(TransportError, match='Whole working-page CRC.*burn not sent'):
        mod.execute(plan)
    assert device.writes == 2 and device.burns == 0


def test_lost_burn_ack_reports_uncertain_and_no_retry(setup):
    data, device, edited, _ = setup
    _, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    plan = mod.prepare(evidence, str(edited))
    write = device.write
    def reject_burn(frame):
        result = write(frame)
        if frame[2:3] == b'B': device.pending[:] = globals()['frame'](b'\x83')
        return result
    device.write = reject_burn
    with pytest.raises(TransportError, match='burn was attempted'):
        mod.execute(plan)
    assert device.writes == 2 and device.burns == 1


def test_save_failure_read_has_no_write_evidence(setup, monkeypatch):
    _, _, _, _ = setup
    monkeypatch.setattr(mod, '_save', lambda data: (_ for _ in ()).throw(OSError('disk full')))
    result, evidence = mod.read_original('/dev/ttyACM0', 115200, INI)
    assert evidence is None and 'disk full' in result['write_review_unavailable']


def test_desktop_close_guard_for_rusefi_operation():
    from guzzionboard.desktop import DesktopApp
    app = DesktopApp(no_window=True, record=False)
    try:
        app.start(); app.handler.api._rusefi_active.set()
        assert app.busy()['name'] == 'rusEFI calibration operation'
        assert app._on_window_closing() is False
        app.handler.api._rusefi_active.clear()
    finally:
        app.shutdown()


def test_source_sized_page_is_chunked_without_second_full_read(setup):
    _, device, edited, _ = setup
    data = bytes((i % 251)+1 for i in range(23792)); device.data[:] = data
    ini = INI.replace('300, 256', '23792, 256')
    _, evidence = mod.read_original('/dev/ttyACM0', 115200, ini)
    assert evidence.original == data
    assert len([p for p in device.sent if p[:1] == b'R']) == 186
    target = bytearray(data); target[20000] ^= 1; edited.write_bytes(target)
    before = len(device.sent); mod.execute(mod.prepare(evidence, str(edited)))
    assert len([p for p in device.sent[before:] if p[:1] == b'R']) == 2
    assert device.burns == 1


def test_synthetic_single_read_map_export_review_write_full_stack(setup, tmp_path):
    """One synthetic page read -> map edit -> immutable plan -> RAM write/burn."""
    data, device, _, _ = setup
    api = Api(Workstation(record=False))
    _, read = api.post_tools_rusefi_read({'action':'read-calibration','confirm':True,
        'port':'/dev/ttyACM0','baud':115200,'ini':INI})
    xdf = tmp_path / 'user-rusefi.xdf'
    xdf.write_text('''<XDFFORMAT><XDFHEADER><deftitle>Synthetic rusEFI</deftitle><DEFAULTS signed="0" lsbfirst="0"/></XDFHEADER>
<XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
<XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>''')
    body = {'path':read['original_path'], 'xdf':str(xdf), 'address_base':0,
            'expected_source_sha256':read['sha256'], 'expected_xdf_sha256':hashlib.sha256(xdf.read_bytes()).hexdigest(),
            'changes':[{'kind':'table','id':'fuel','row':0,'col':1,'expected_raw':data[33],'value':42}]}
    status, preview = api.post_maps_research_preview(body)
    assert status == 200
    status, saved = api.post_maps_research_export({**body, 'region_start':0,'region_end':len(data),
        'accept_research_only':True,'expected_candidate_sha256':preview['candidate_sha256']})
    assert status == 201 and Path(saved['path']).read_bytes()[33] == 42
    _, review = api.post_tools_rusefi_read({'action':'prepare-calibration','confirm':True,
        'confirm_tuning':True,'read_token':read['read_token'],'edited_path':saved['path']})
    assert not device.writes and not device.burns
    status, _ = api.post_tools_rusefi_read({'action':'write-calibration','confirm':True,
        'confirm_tuning':True,'confirm_write':True,'token':review['token']})
    assert status == 200 and device.data[33] == 42 and device.writes == 1 and device.burns == 1
    assert Path(read['original_path']).read_bytes() == data
