from __future__ import annotations

import hashlib
from functools import partial
from pathlib import Path

import pytest

from guzzionboard import honda_tuning as honda, server
from guzzionboard.checksums import ChecksumUnavailable
from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import XdfFile
from guzzionboard.tuning import TUNING_ACKNOWLEDGEMENT, TuningError, _xdf_sha256, build_tune
from guzzionboard.workstation import Workstation

XDF = Path('guzzionboard/xdfs/honda/CBR1000RR_2012_US.xdf')


def test_vendored_honda_definition_is_exact_and_exposes_unsupported_item():
    xdf = XdfFile.from_file(XDF)
    assert xdf.file_sha256 == honda.XDF_SHA256
    assert xdf.title == 'CBR1000RR 2012 US'
    assert xdf.checksums == ['Honda Checksum']
    assert len(xdf.tables) == 38
    assert [item['title'] for item in xdf.unsupported] == ['Top Speed Limit']


def test_checksum_scope_and_byte_changes(monkeypatch):
    data = bytearray(honda.IMAGE_SIZE)
    data[123] = 0x42
    original = bytes(data)
    monkeypatch.setattr(honda, 'SOURCE_SHA256', hashlib.sha256(original).hexdigest())
    context = {'xdf_sha256': honda.XDF_SHA256, 'source_sha256': honda.SOURCE_SHA256,
               'address_base': 0, 'declared_checksums': ['Honda Checksum'], 'changes': []}
    output, audit = honda.provider().apply(original, context)
    assert output[honda.CHECKSUM_OFFSET] == 0xbe
    assert sum(output) & 0xff == 0
    assert audit['byte_changes'] == [{'offset': '0x3FFF8', 'length': 1,
                                      'before_hex': '00', 'after_hex': 'be'}]
    assert output[:honda.CHECKSUM_OFFSET] == original[:honda.CHECKSUM_OFFSET]
    assert output[honda.CHECKSUM_OFFSET + 1:] == original[honda.CHECKSUM_OFFSET + 1:]
    for key, bad in [('xdf_sha256', '0' * 64), ('source_sha256', '0' * 64),
                     ('address_base', 0x4000), ('declared_checksums', ['other'])]:
        with pytest.raises(ChecksumUnavailable):
            honda.provider().apply(original, {**context, key: bad})
    with pytest.raises(ChecksumUnavailable, match='overlap'):
        honda.provider().apply(original, {**context, 'changes': [
            {'image_offset': '0x3FFF7', 'after_hex': '0000'}]})
    with pytest.raises(ChecksumUnavailable):
        honda.provider().apply(original[:-1], context)


def test_end_to_end_honda_build_is_hash_and_selection_scoped(tmp_path, monkeypatch):
    # No OEM firmware in the test suite. Override only the accepted source hash
    # to exercise the actual bundled XDF, provider, API, plan and image sidecar.
    source_path = tmp_path / 'synthetic.bin'
    source_path.write_bytes(bytes(honda.IMAGE_SIZE))
    monkeypatch.setattr(honda, 'SOURCE_SHA256', hashlib.sha256(source_path.read_bytes()).hexdigest())
    monkeypatch.setattr(server, 'build_tune', partial(build_tune, output_dir=tmp_path / 'out'))
    api = server.Api(Workstation(session_dir=tmp_path / 'sessions'))
    api.ws.select(make='Honda', model='CBR1000RR (US)', year=2012)
    body = {'path': str(source_path), 'xdf': honda.XDF_NAME,
            'changes': [{'kind': 'table', 'id': '0x3A51', 'row': 0, 'col': 0,
                         'expected_raw': 0, 'value': 1}],
            'checksum_provider': honda.provider().provider_id}
    status, result = api.post_maps_preview(body)
    assert status == 200, result
    assert result['checksum_provider']['byte_changes'][0]['offset'] == '0x3FFF8'
    assert not result['writes_file']
    assert not (tmp_path / 'out').exists()
    build = {**body, 'accept_non_base_source': True,
             'expected_plan_sha256': result['plan_sha256'],
             'acknowledgement': TUNING_ACKNOWLEDGEMENT,
             'recommendation': {'title': 'Example test evidence', 'url': 'https://example.org/test',
                                'rationale': 'Synthetic test input, not a tune recommendation.'}}
    status, output = api.post_maps_build(build)
    assert status == 201, output
    built = FirmwareImage.from_file(output['path'])
    assert built.ecu_id == honda.ECU_ID
    assert built.data[0x2e1de:0x2e1e0] == b'\x00\x01'
    assert built.data[honda.CHECKSUM_OFFSET] == 0xff
    assert sum(built.data) & 0xff == 0
    assert source_path.read_bytes() == bytes(honda.IMAGE_SIZE)
    assert output['manifest']['source']['sha256'] == honda.SOURCE_SHA256
    assert output['manifest']['xdf']['sha256'] == honda.XDF_SHA256
    for invalid in [{**body, 'checksum_provider': ''}, {**body, 'address_base': '0x4000'}]:
        status, _ = api.post_maps_preview(invalid)
        assert status == 400
    source_path.write_bytes(b'\x01' + bytes(honda.IMAGE_SIZE - 1))
    status, result = api.post_maps_preview(body)
    assert status == 400 and 'exact 38770-MGP-A01' in result['error']
    api.ws.select(make='Honda', model='CBR600RR', year=2005)
    source_path.write_bytes(bytes(honda.IMAGE_SIZE))
    status, _ = api.post_maps_preview(body)
    assert status == 400


def test_modified_xdf_and_stale_parsed_bytes_are_refused(tmp_path, monkeypatch):
    data = bytes(honda.IMAGE_SIZE)
    monkeypatch.setattr(honda, 'SOURCE_SHA256', hashlib.sha256(data).hexdigest())
    path = tmp_path / honda.XDF_NAME
    path.write_bytes(XDF.read_bytes())
    xdf = XdfFile.from_file(path)
    api = server.Api(Workstation(session_dir=tmp_path / 'sessions'))
    api.ws.select(make='Honda', model='CBR1000RR (US)', year=2012)
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(TuningError, match='changed after parsing'):
        _xdf_sha256(xdf)
    modified = XdfFile.from_file(path)
    with pytest.raises(TuningError, match='pinned HondaECU XDF'):
        api._check_build_fitment(modified, FirmwareImage(data=data))


def test_builtin_provider_is_listed_and_cannot_be_shadowed(tmp_path, monkeypatch):
    (tmp_path / 'duplicate.py').write_text(
        "PROVIDER_ID='honda-cbr1000rr-2012-us-a01-v1'\n"
        "SUPPORTED_CHECKSUMS=('Honda Checksum',)\n"
        "def update(image, context): return image\n"
        "def verify(image, context): return True\n")
    from guzzionboard.checksums import load_providers
    monkeypatch.setattr(server, 'load_local_checksum_providers', lambda: load_providers(tmp_path))
    providers, errors = server.load_checksum_providers()
    assert len([p for p in providers if p.provider_id == honda.provider().provider_id]) == 1
    assert errors and 'reserved' in errors[0]['error']
    assert server.checksum_provider_by_id(honda.provider().provider_id).update_fn == honda.update
