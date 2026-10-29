"""Synthetic tests for the source-locked offline MGZ-A03 path."""
from __future__ import annotations

import hashlib
from functools import partial
from pathlib import Path
import pytest

from guzzionboard import honda_mgz as mgz, server
from guzzionboard.checksums import ChecksumUnavailable
from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import XdfFile, fitment
from guzzionboard.tuning import TUNING_ACKNOWLEDGEMENT, TuningError, build_tune
from guzzionboard.workstation import Workstation

XDFS = Path('guzzionboard/xdfs/honda')
RESEARCH = ['38770-MEL.xdf', '38770-MGZ.xdf', '38770-MJW.xdf',
            '38770-KYK-D12.xdf', '38770-MKE-DataSettings.xdf', '38770-K26-911.xdf',
            '38770-K26-B13.xdf', '38770-K26-C31.xdf', '38770-K0F-A01.xdf']


def test_additional_original_xdfs_are_catalogued_and_research_only(tmp_path):
    api = server.Api(Workstation(session_dir=tmp_path / 'sessions'))
    for name in RESEARCH:
        xdf = XdfFile.from_file(XDFS / name)
        fit = fitment(xdf.path)
        assert fit['research_only'] and fit['brand'] == 'honda' and fit['source_url']
        assert xdf.tables
        with pytest.raises(TuningError, match='research-only'):
            api._check_build_fitment(xdf, FirmwareImage(data=bytes(0x40000)))
    assert len([x for x in XdfFile.from_file(XDFS / '38770-K26-C31.xdf').unsupported if x['kind'] == 'table']) == 2
    assert len([x for x in XdfFile.from_file(XDFS / '38770-MJW.xdf').unsupported if x['kind'] == 'flag']) == 56


def test_adapted_xdf_checksum_provider_and_observed_axis():
    xdf = XdfFile.from_file(XDFS / mgz.XDF_NAME)
    assert xdf.file_sha256 == mgz.XDF_SHA256
    assert not xdf.little_endian and xdf.checksums == [mgz.CHECKSUM_NAME]
    assert len(xdf.tables) == 17 and [x['kind'] for x in xdf.unsupported] == ['flag']
    # Synthetic bytes copied from the source's observed RPM axis, not a ROM.
    data = bytearray(mgz.IMAGE_SIZE)
    data[0x2876c:0x28772] = bytes.fromhex('03 20 03 e8 04 4c')
    rendered = xdf.render(FirmwareImage(data=bytes(data)), address_base=0)
    t = next(t for t in rendered['tables'] if t['id'] == '0x1011')
    assert t['y'][:3] == ['800', '1000', '1100']
    assert mgz.provider().provider_id in [p.provider_id for p in server.load_checksum_providers()[0]]


def test_scoped_build_corrects_checksum_and_rejects_mismatch(tmp_path, monkeypatch):
    data = bytearray(mgz.IMAGE_SIZE)
    data[0x287b4:0x287b6] = bytes.fromhex('06 d7')
    data[mgz.CHECKSUM_OFFSET] = (-sum(data)) & 255
    path = tmp_path / 'synthetic.bin'; path.write_bytes(data)
    monkeypatch.setattr(mgz, 'SOURCE_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(server, 'build_tune', partial(build_tune, output_dir=tmp_path / 'out'))
    api = server.Api(Workstation(session_dir=tmp_path / 'sessions'))
    api.ws.select(make='Honda', model='CBR500R', year=2014)
    body = {'path': str(path), 'xdf': mgz.XDF_NAME, 'address_base': 0,
            'changes': [{'kind': 'table', 'id': '0x1011', 'row': 0, 'col': 0,
                         'expected_raw': 1751, 'value': 1752}],
            'checksum_provider': mgz.provider().provider_id}
    status, report = api.post_maps_preview(body)
    assert status == 200, report
    assert report['changes'][0]['before_hex'] == '06d7' and report['changes'][0]['after_hex'] == '06d8'
    assert report['checksum_provider']['byte_changes'][0]['offset'] == '0x3FFF8'
    status, result = api.post_maps_build({**body, 'accept_non_base_source': True,
        'expected_plan_sha256': report['plan_sha256'], 'acknowledgement': TUNING_ACKNOWLEDGEMENT,
        'recommendation': {'title': 'Synthetic test', 'url': 'https://example.org/test',
                           'rationale': 'Synthetic test only, not a tuning recommendation.'}})
    assert status == 201, result
    built = FirmwareImage.from_file(result['path'])
    assert built.ecu_id == mgz.ECU_ID and sum(built.data) & 255 == 0
    assert [i for i in range(len(data)) if built.data[i] != data[i]] == [0x287b5, 0x3fff8]
    assert path.read_bytes() == data
    api.ws.select(make='Honda', model='CB500F', year=2013)
    assert api.post_maps_preview(body)[0] == 200
    api.ws.select(make='Honda', model='CBR1000RR (US)', year=2012)
    assert api.post_maps_preview(body)[0] == 400
    api.ws.select(make='Honda', model='CB500F', year=2013)
    path.write_bytes(b'\x01' + bytes(data[1:]))
    assert api.post_maps_preview(body)[0] == 400


def test_provider_refuses_wrong_context_and_checksum_edits(monkeypatch):
    image = bytes(mgz.IMAGE_SIZE)
    monkeypatch.setattr(mgz, 'SOURCE_SHA256', hashlib.sha256(image).hexdigest())
    ctx = {'address_base': 0, 'xdf_sha256': mgz.XDF_SHA256,
           'source_sha256': mgz.SOURCE_SHA256, 'declared_checksums': [mgz.CHECKSUM_NAME], 'changes': []}
    assert mgz.provider().apply(image, ctx)[0] == image
    for key, value in [('address_base', 0x4000), ('source_sha256', '0' * 64),
                       ('xdf_sha256', '0' * 64), ('declared_checksums', [])]:
        with pytest.raises(ChecksumUnavailable): mgz.provider().apply(image, {**ctx, key: value})
    with pytest.raises(ChecksumUnavailable, match='overlap'):
        mgz.provider().apply(image, {**ctx, 'changes': [{'image_offset': '0x3FFF7', 'after_hex': '0000'}]})
