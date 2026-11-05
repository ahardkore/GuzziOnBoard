"""EcmSpy .epr / 'Reihe:' hex-dump import tests. Synthetic data only."""
import hashlib
import stat
from pathlib import Path

import pytest

from guzzionboard import buell_ddfi, buell_epr, resources
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


def fixture_image(ecm_id='BUEIB'):
    """Deterministic bytes for the normal pages of one layout."""
    return bytes((i * 7 + (i >> 8) * 13) & 0xFF for i in range(sum(
        size for page, size in buell_ddfi.IMAGE_LAYOUTS[ecm_id] if page)))


def dump_text(ecm_id='BUEIB', *, header=None, data=None, page_zero=b'',
              line=16, newline='\r\n', skip=(), extra=()):
    data = fixture_image(ecm_id) if data is None else data
    lines = [header or f'{ecm_id}310 12-11-03']
    at = 0
    for page, size in buell_ddfi.IMAGE_LAYOUTS[ecm_id]:
        if page and page not in skip:
            lines.append(f'Reihe: {page}')
            chunk = data[at:at + size]
            for start in range(0, len(chunk), line):
                lines.append(' '.join(f'{byte:02X}' for byte in chunk[start:start + line]))
        if page:
            at += size
    if page_zero:
        lines.append('Reihe: 0')
        for start in range(0, len(page_zero), line):
            lines.append(' '.join(f'{byte:02X}' for byte in page_zero[start:start + line]))
    lines.extend(extra)
    return newline.join(lines) + newline


def test_hex_dump_round_trip_and_metadata():
    read = buell_epr.parse_hex_dump(dump_text())
    assert read.ecm_id == 'BUEIB' and read.kind == 'hex-dump'
    assert read.header == 'BUEIB310 12-11-03' and read.date == '12-11-03'
    assert read.identification == 'header'
    assert read.data == fixture_image()
    assert read.pages == ((1, 256), (2, 256), (3, 158), (4, 256), (5, 256), (6, 24))
    assert not read.page_zero_present
    assert read.sha256 == hashlib.sha256(read.data).hexdigest()


def test_hex_dump_with_page_zero_matches_xpr_order():
    normal = fixture_image()
    zero = b'\xEE\xBB\x55\xAA'
    read = buell_epr.parse_hex_dump(dump_text(page_zero=zero))
    assert read.page_zero_present
    assert read.data == normal + zero
    assert len(read.data) == sum(size for _, size in buell_ddfi.IMAGE_LAYOUTS['BUEIB'])
    assert read.pages[-1] == (0, 4)


def test_hex_dump_header_is_case_insensitive():
    read = buell_epr.parse_hex_dump(dump_text().lower())
    assert read.ecm_id == 'BUEIB' and read.header == 'bueib310 12-11-03'
    assert read.data == fixture_image()


def test_hex_dump_accepts_lf_and_short_lines():
    text = dump_text(line=7, newline='\n')
    assert buell_epr.parse_hex_dump(text).data == fixture_image()


@pytest.mark.parametrize('text, message', [
    ('', 'empty'),
    ('BUEIB310 12-11-03\n', 'missing'),
    ('NOTANID 12-11-03\nReihe: 1\n00\n', 'supported Buell ECM ID'),
    ('BUEIB310\nReihe: 7\n00\n', 'not part of'),
    ('BUEIB310\nReihe: 8\n00\n', 'not part of'),
    ('BUEIB310\n00 11\nReihe: 1\n', 'before the first'),
    ('BUEIB310\nReihe: 1\n0G\n', 'two-digit hex'),
])
def test_hex_dump_rejects_malformed_input(text, message):
    with pytest.raises(buell_epr.BuellImportError, match=message):
        buell_epr.parse_hex_dump(text)


def test_hex_dump_rejects_wrong_page_sizes_and_duplicates():
    with pytest.raises(buell_epr.BuellImportError, match='Page 6 has 23 bytes'):
        buell_epr.parse_hex_dump(dump_text(data=fixture_image()[:-1]))
    duplicate = dump_text().replace('Reihe: 2', 'Reihe: 1', 1)
    with pytest.raises(buell_epr.BuellImportError, match='more than once'):
        buell_epr.parse_hex_dump(duplicate)
    with pytest.raises(buell_epr.BuellImportError, match='missing'):
        buell_epr.parse_hex_dump(dump_text(skip=(4,)))


def test_binary_layout_identification():
    normal = fixture_image()
    by_name = buell_epr.parse_binary(normal, name='BUEIB-XB9-RACEMAPS.epr')
    assert by_name.ecm_id == 'BUEIB' and by_name.identification == 'filename'
    assert by_name.kind == 'epr-binary' and not by_name.page_zero_present
    with pytest.raises(buell_epr.BuellImportError, match='enter the ECM ID'):
        buell_epr.parse_binary(normal, name='race-maps.epr')
    explicit = buell_epr.parse_binary(normal, ecm_id='BUEIB', name='race-maps.epr')
    assert explicit.identification == 'explicit' and explicit.data == normal
    with pytest.raises(buell_epr.BuellImportError, match='do not match'):
        buell_epr.parse_binary(normal, ecm_id='BUEGC')
    with pytest.raises(buell_epr.BuellImportError, match='no bundled source page layout'):
        buell_epr.parse_binary(normal, ecm_id='ZZZZZ')


def test_binary_full_layout_keeps_page_zero():
    zero = b'\xEE\xBB\x55\xAA'
    full = fixture_image() + zero
    read = buell_epr.parse_binary(full, ecm_id='BUEIB')
    assert read.page_zero_present and read.data == full
    assert read.pages[-1] == (0, 4)
    assert buell_epr.describe(read)['missing_page_zero'] is False


def test_binary_unknown_size_and_empty():
    with pytest.raises(buell_epr.BuellImportError, match='several layouts or none'):
        buell_epr.parse_binary(b'\0' * 999, name='x.epr')
    with pytest.raises(buell_epr.BuellImportError, match='empty'):
        buell_epr.parse_binary(b'', ecm_id='BUEIB')


def test_load_read_requires_absolute_path_and_detects_formats(tmp_path):
    text_path = tmp_path / 'BUEIB-XB9-RACEMAPS.txt'
    text_path.write_text(dump_text())
    binary_path = tmp_path / 'BUEIB-XB9-RACEMAPS.epr'
    binary_path.write_bytes(fixture_image())
    assert buell_epr.load_read(text_path).kind == 'hex-dump'
    binary = buell_epr.load_read(binary_path)
    assert binary.kind == 'epr-binary' and binary.data == fixture_image()
    with pytest.raises(buell_epr.BuellImportError, match='absolute'):
        buell_epr.load_read('BUEIB-XB9-RACEMAPS.epr')
    with pytest.raises(buell_epr.BuellImportError, match='Choose a local'):
        buell_epr.load_read(None)
    with pytest.raises(buell_epr.BuellImportError, match='five characters'):
        buell_epr.load_read(binary_path, 'BUEI')


def test_save_import_is_private_and_prefixed(tmp_path):
    read = buell_epr.parse_hex_dump(dump_text())
    saved = Path(buell_epr.save_import(read, tmp_path))
    assert saved.name.startswith('BUEIB-epr-import-') and saved.suffix == '.bin'
    assert saved.read_bytes() == read.data
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    full = buell_epr.parse_hex_dump(dump_text(page_zero=b'\x01\x02\x03\x04'))
    assert Path(buell_epr.save_import(full, tmp_path)).suffix == '.xpr'


def test_describe_reports_missing_page_zero_and_definition():
    report = buell_epr.describe(buell_epr.parse_hex_dump(dump_text()))
    assert report['ecm_id'] == 'BUEIB' and report['size'] == 1206
    assert report['map_xdf'] == 'BUEIB_source_research.xdf'
    assert report['missing_page_zero'] is True and report['page_zero_size'] == 4
    assert report['address_base'] == 0 and report['synthetic_tested'] is True
    assert any('Page zero' in warning for warning in report['warnings'])
    assert any('binary .epr carries no ECM ID' in warning
               for warning in buell_epr.describe(
                   buell_epr.parse_binary(fixture_image(), name='BUEIB-x.epr'))['warnings'])


def test_api_import_needs_no_confirmation_and_saves_copy(tmp_path, monkeypatch):
    monkeypatch.setenv(resources.HOME_ENV, str(tmp_path / 'home'))
    source = tmp_path / 'BUEIB-XB9-RACEMAPS.txt'
    source.write_text(dump_text())
    api = Api(Workstation())
    status, result = api.post_tools_buell_ddfi({'action': 'import', 'path': str(source)})
    assert status == 200, result
    assert result['ecm_id'] == 'BUEIB' and result['size'] == 1206
    saved = Path(result['saved_path'])
    assert saved.is_file() and saved.parent.name == 'buell-imports'
    assert saved.read_bytes() == fixture_image()
    assert result['missing_page_zero'] is True

    status, error = api.post_tools_buell_ddfi({'action': 'import', 'path': str(tmp_path / 'nope.epr')})
    assert status == 400 and 'Cannot read' in error['error']
