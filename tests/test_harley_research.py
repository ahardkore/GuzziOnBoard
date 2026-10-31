"""Synthetic Delphi-layout XDF edits: no ECU or hardware is exercised."""
import hashlib
import json
from pathlib import Path

import pytest

from guzzionboard.server import Api
from guzzionboard.workstation import Workstation

XDF = '''<XDFFORMAT version="1.60"><XDFHEADER><deftitle>Synthetic Harley</deftitle>
<DEFAULTS signed="0" lsbfirst="0"/><REGION size="0x28000"/></XDFHEADER>
<XDFTABLE uniqueid="fuel"><title>Synthetic table</title>
<XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS>
<XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
<XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="ADDRESS" mmedelementsizebits="8"
mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS>
</XDFTABLE><XDFCHECKSUM><title>Unknown</title></XDFCHECKSUM></XDFFORMAT>'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'appdata'))
    api = Api(Workstation(record=False))
    def make(size=0x4000, address=0x20, name='harley_user.xdf'):
        source = tmp_path / 'source.bin'
        data = bytearray(size)
        data[address:address+4] = bytes([10, 20, 30, 40])
        source.write_bytes(data)
        xdf = tmp_path / name
        xdf.write_text(XDF.replace('ADDRESS', hex(address)))
        body = {'path': str(source), 'xdf': str(xdf), 'address_base': 0,
                'expected_source_sha256': sha(data), 'expected_xdf_sha256': sha(xdf.read_bytes()),
                'changes': [{'kind': 'table', 'id': 'fuel', 'row': 0, 'col': 1,
                             'expected_raw': 20, 'value': 25}]}
        return api, body, source, xdf
    return make


@pytest.mark.parametrize('size,address', [(0x4000, 0x20), (0x28000, 0x1c020)])
def test_reviewed_edits_export_separate_research_copy(fixture, size, address):
    api, body, source, xdf = fixture(size, address)
    original = source.read_bytes()
    status, preview = api.post_maps_research_preview(body)
    assert status == 200 and preview['writes_file'] is False
    body.update(accept_research_only=True, expected_candidate_sha256=preview['candidate_sha256'])
    status, result = api.post_maps_harley_research_export(body)
    assert status == 201
    output = Path(result['path']).read_bytes()
    assert source.read_bytes() == original
    assert output[address+1] == 25
    assert sum(a != b for a, b in zip(original, output)) == 1
    assert sha(output) == preview['candidate_sha256']
    manifest = json.loads(Path(result['manifest_path']).read_text())
    assert manifest['research_only'] is True and manifest['flash_ready'] is False
    assert manifest['source']['sha256'] == sha(original)
    assert manifest['xdf']['sha256'] == sha(xdf.read_bytes())
    assert manifest['declared_checksums'] == ['Unknown']
    assert 'not verified or repaired' in manifest['warning']
    assert api.post_maps_preview(body)[0] == 400  # does not change the normal build gate
    status2, result2 = api.post_maps_harley_research_export(body)
    assert status2 == 201 and result2['path'] != result['path']


def test_export_requires_confirmation_and_exact_reviewed_bytes(fixture):
    api, body, source, xdf = fixture()
    _, preview = api.post_maps_research_preview(body)
    assert api.post_maps_harley_research_export(body)[0] == 400
    good = {**body, 'accept_research_only': True, 'expected_candidate_sha256': preview['candidate_sha256']}
    for alteration in ({'accept_research_only': 'true'}, {'expected_candidate_sha256': '0'*64},
                       {'expected_source_sha256': '0'*64}, {'expected_xdf_sha256': '0'*64},
                       {'changes': [{**body['changes'][0], 'value': 26}]}):
        assert api.post_maps_harley_research_export({**good, **alteration})[0] == 400
    source.write_bytes(b'\x00' * 0x4000)
    assert api.post_maps_harley_research_export(good)[0] == 400


def test_export_refuses_outside_region_and_catalogued_xdf(fixture):
    api, body, _, _ = fixture(0x28000, 0x20)
    _, preview = api.post_maps_research_preview(body)
    status, response = api.post_maps_harley_research_export({**body, 'accept_research_only': True,
                                   'expected_candidate_sha256': preview['candidate_sha256']})
    assert status == 400 and 'inside' in response['error']
    api, body, _, _ = fixture(0x4000, 0x20, '5AM_synthetic.xdf')
    _, preview = api.post_maps_research_preview(body)
    status, response = api.post_maps_harley_research_export({**body, 'accept_research_only': True,
                                   'expected_candidate_sha256': preview['candidate_sha256']})
    assert status == 400 and 'uncatalogued' in response['error']


def test_invalid_size_refused(fixture):
    api, body, _, _ = fixture(0x8000)
    _, preview = api.post_maps_research_preview(body)
    status, response = api.post_maps_harley_research_export({**body, 'accept_research_only': True,
                                   'expected_candidate_sha256': preview['candidate_sha256']})
    assert status == 400 and 'exactly 16 KiB or 160 KiB' in response['error']


def test_export_never_overwrites_or_deletes_existing_file(fixture, monkeypatch, tmp_path):
    from guzzionboard import server
    api, body, _, _ = fixture()
    _, preview = api.post_maps_research_preview(body)
    directory = tmp_path / 'appdata' / 'research' / 'harley-delphi'
    directory.mkdir(parents=True)
    monkeypatch.setattr(server.secrets, 'token_hex', lambda _: '1' * 16)
    existing = directory / ('harley-research-' + preview['candidate_sha256'][:12] + '-' + '1'*16 + '.bin')
    existing.write_bytes(b'not to be touched')
    status, _ = api.post_maps_harley_research_export({**body, 'accept_research_only': True,
                                'expected_candidate_sha256': preview['candidate_sha256']})
    assert status == 400 and existing.read_bytes() == b'not to be touched'
