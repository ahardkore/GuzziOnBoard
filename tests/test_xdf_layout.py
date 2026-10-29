"""Synthetic XDF layout fixtures: flags must survive rendering and writing."""
from pathlib import Path

import pytest

from guzzionboard.maps import XdfError, XdfFile


def definition(flags, *, signed=1, lsbfirst=1, float_default=0, major=0, minor=0):
    attr = '' if flags is None else f'mmedtypeflags="{flags}"'
    return f'''<XDFFORMAT><XDFHEADER><deftitle>Layout</deftitle>
      <DEFAULTS signed="{signed}" lsbfirst="{lsbfirst}" float="{float_default}"/>
      <REGION size="0x100"/></XDFHEADER>
      <XDFTABLE uniqueid="cells"><title>Cells</title>
        <XDFAXIS id="x"><indexcount>3</indexcount></XDFAXIS>
        <XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
        <XDFAXIS id="z"><EMBEDDEDDATA {attr} mmedaddress="0x20"
          mmedelementsizebits="16" mmedrowcount="2" mmedcolcount="3"
          mmedmajorstridebits="{major}" mmedminorstridebits="{minor}"/>
          <MATH equation="X"/></XDFAXIS></XDFTABLE>
      <XDFCONSTANT uniqueid="valid"><title>Valid</title>
        <EMBEDDEDDATA mmedtypeflags="0x00" mmedaddress="0x10" mmedelementsizebits="8"/>
        <MATH equation="X"/></XDFCONSTANT></XDFFORMAT>'''


@pytest.mark.parametrize('flags,signed,little,column', [
    (None, True, True, False), ('0x00', False, False, False),
    ('0x01', True, False, False), ('0x02', False, True, False),
    ('0x03', True, True, False), ('0x04', False, False, True),
    ('0x05', True, False, True), ('0x06', False, True, True),
    ('0x07', True, True, True),
])
def test_per_item_flags_override_defaults_and_write_correct_bytes(flags, signed, little, column):
    xdf = XdfFile.from_string(definition(flags))
    data = bytearray(0x100)
    raws = [-2, 3, 4, 5, 6, 7] if signed else [65534, 3, 4, 5, 6, 7]
    for row in range(2):
        for col in range(3):
            i = row * 3 + col
            p = 0x20 + (col * 2 + row if column else i) * 2
            data[p:p+2] = raws[i].to_bytes(2, 'little' if little else 'big', signed=signed)
    render = xdf.render(bytes(data))
    assert render['tables'][0]['raw_values'] == [raws[:3], raws[3:]]
    after, changes = xdf.apply_changes(bytes(data), [
        {'kind': 'table', 'id': 'cells', 'row': 1, 'col': 1, 'expected_raw': 6, 'value': 0x1234},
        {'kind': 'table', 'id': 'cells', 'row': 0, 'col': 2, 'expected_raw': 4, 'value': 0x1256},
    ])
    p = 0x20 + (3 if column else 4) * 2
    q = 0x20 + (4 if column else 2) * 2
    assert after[p:p+2] == (0x1234).to_bytes(2, 'little' if little else 'big')
    assert after[q:q+2] == (0x1256).to_bytes(2, 'little' if little else 'big')
    assert changes[0]['image_offset'] == f'0x{p:X}'
    assert xdf.render(after)['tables'][0]['raw_values'][1][1] == 0x1234


@pytest.mark.parametrize('kwargs', [
    {'flags': '0x10002'}, {'flags': '0x08'}, {'flags': None, 'float_default': 1},
    {'flags': '0x06', 'major': 32}, {'flags': '0', 'major': -16},
    {'flags': '0', 'minor': 12},
])
def test_unimplemented_encodings_and_strides_are_reported_not_interpreted(kwargs):
    xdf = XdfFile.from_string(definition(**kwargs))
    assert not xdf.tables
    assert len(xdf.unsupported) == 1
    assert 'not supported' in xdf.unsupported[0]['reason'] or 'unsupported' in xdf.unsupported[0]['reason']


def test_real_mbc1_definition_explicit_unsigned_overrides_signed_header():
    path = Path('guzzionboard/xdfs/husqvarna/MBC1_Nuda_900_V1.00.xdf')
    xdf = XdfFile.from_file(path)
    assert xdf.signed_default and xdf.little_endian
    items = [t for t in xdf.tables if t.embedded.little_endian and not t.embedded.signed]
    assert items, 'real bundled MBC1 contains explicit unsigned little-endian data'
    assert items[0].embedded.read(b'\xff' * (items[0].embedded.count * 2), 0, little_endian=False)[0] == 65535


def test_unnamed_checksum_is_still_a_declared_checksum():
    text = definition('0x02').replace('</XDFFORMAT>', '<XDFCHECKSUM/><XDFCHECKSUM><title>Named</title></XDFCHECKSUM></XDFFORMAT>')
    xdf = XdfFile.from_string(text)
    assert xdf.checksums == ['(unnamed checksum #1)', 'Named']


def test_real_miug3_definition_item_byte_order_overrides_header():
    path = Path('guzzionboard/xdfs/aprilia/MIUG3_Aprilia_RS4_125_CM088115_V1.02.xdf')
    xdf = XdfFile.from_file(path)
    assert not xdf.little_endian
    item = next(t for t in xdf.tables if t.embedded.little_endian and t.embedded.size_bits == 16)
    data = (b'\x34\x12' * item.embedded.count)
    assert item.embedded.read(data, 0, little_endian=False)[0] == 0x1234
