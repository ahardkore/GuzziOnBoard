#!/usr/bin/env python3
"""Generate the small DDFI map XDF adaptations from a pinned XBTune database.

Requires Python 3.11+ and the *external* data/ecmdroid.toml from XBTune
c592b11b17e1a3cd5f55f8bc726f2890d892d63b; no database is bundled. Derived
facts and licensing are documented in docs/BUELL_DDFI_RESEARCH.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://github.com/kz6fittycent/XBTune/tree/c592b11b17e1a3cd5f55f8bc726f2890d892d63b'
EXPECTED = '378496702137c94633179e0487392674e40ff0a15d43ec5e2b21031272c5a259'
NAMES = ('Tab_Spark_Front', 'Tab_Spark_Rear', 'Tab_Fuel_Front', 'Tab_Fuel_Rear')
GROUPS = (
    ('BUEGC',), ('BUEIA',), ('BUEJA', 'BUEKA'), ('BUECB',), ('BUEGB',),
    ('B3R1D', 'BUE1D'), ('B3R2D', 'BUE2D'), ('B3R3D', 'BUE3D'),
    ('BUEOD',), ('BUEWD',), ('BUEYD',), ('BUEZD',),
)


def selection(db, ecm):
    variables = {v['var']: v for v in db['eeprom_vars'] if v['c'] == ecm['category']}
    result = []
    for name in NAMES:
        v = variables[name]; x = variables[v['xaxis']]; y = variables[v['yaxis']]
        # Only the simple unsigned layouts this adapter knows are accepted.
        assert v['type'] == 'Map' and v['elemsize'] == 1 and v['offset'] >= 0
        assert v['size'] == v['rows'] * (v['cols'] + v['skip'])
        assert v['offset'] + v['size'] <= ecm['size']
        assert x['elemsize'] == 2 and x['size'] >= v['cols'] * 2
        assert y['elemsize'] == 1 and y['size'] >= v['rows']
        assert x['scale'] == y['scale'] == 1 and x['translate'] == y['translate'] == 0
        assert (v['scale'], v['translate']) in ((1, 0), (0.25, 0))
        assert x['offset'] >= 0 and x['offset'] + x['size'] <= ecm['size']
        assert y['offset'] >= 0 and y['offset'] + y['size'] <= ecm['size']
        result.append((name, v['offset'], v['rows'], v['cols'], v['skip'],
                       v['scale'], x['offset'], y['offset']))
    return tuple(result)


def create(ids, size, tables):
    root = ET.Element('XDFFORMAT', version='1.60')
    header = ET.SubElement(root, 'XDFHEADER')
    for key, text in (
        ('deftitle', f"Buell {' / '.join(ids)} EEPROM maps (research)"),
        ('description', 'Source-derived flat XPR EEPROM image; use only with the matching ECM ID and verify definition. Synthetic tests only. Not flash-ready.'),
        ('author', 'EcmDroid / XBTune; adapted by GuzziOnBoard'), ('fileversion', '0.1'),
    ):
        ET.SubElement(header, key).text = text
    ET.SubElement(header, 'BASEOFFSET', offset='0', subtract='0')
    ET.SubElement(header, 'DEFAULTS', datasizeinbits='8', signed='0', lsbfirst='1', float='0')
    ET.SubElement(header, 'REGION', type='0xFFFFFFFF', startaddress='0x0', size=hex(size),
                  regionflags='0x0', name='XPR EEPROM', desc='Page 0 stored at end')
    for i, (name, start, rows, cols, skip, scale, xa, ya) in enumerate(tables, 1):
        table = ET.SubElement(root, 'XDFTABLE', uniqueid=hex(i))
        ET.SubElement(table, 'title').text = name
        for ident, address, width, count, unit in (('x', xa, 16, cols, 'RPM'), ('y', ya, 8, rows, 'Load')):
            axis = ET.SubElement(table, 'XDFAXIS', id=ident)
            ET.SubElement(axis, 'EMBEDDEDDATA', mmedtypeflags='0x02', mmedaddress=hex(address), mmedelementsizebits=str(width))
            ET.SubElement(axis, 'units').text = unit
            ET.SubElement(axis, 'indexcount').text = str(count)
            ET.SubElement(axis, 'MATH', equation='X')
        axis = ET.SubElement(table, 'XDFAXIS', id='z')
        ET.SubElement(axis, 'EMBEDDEDDATA', mmedtypeflags='0x02', mmedaddress=hex(start),
                      mmedelementsizebits='8', mmedrowcount=str(rows), mmedcolcount=str(cols),
                      mmedmajorstridebits=str((cols + skip) * 8))
        ET.SubElement(axis, 'units').text = 'degrees' if name.startswith('Tab_Spark') else 'raw'
        ET.SubElement(axis, 'decimalpl').text = '2' if scale == 0.25 else '0'
        ET.SubElement(axis, 'MATH', equation='X*0.25' if scale == 0.25 else 'X')
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise SystemExit('Source hash differs from the pinned XBTune data; refusing generation.')
    db = tomllib.loads(raw.decode('utf-8'))
    by_id = {e['id']: e for e in db['ecm']}
    catalog_path = ROOT / 'guzzionboard/xdfs/catalog.json'
    prov_path = ROOT / 'guzzionboard/xdfs/PROVENANCE.json'
    catalog = json.loads(catalog_path.read_text())
    provenance = json.loads(prov_path.read_text())
    for ids in GROUPS:
        ecm = by_id[ids[0]]
        tables = selection(db, ecm)
        assert all(selection(db, by_id[name]) == tables and by_id[name]['xsize'] == ecm['xsize'] for name in ids)
        file = f'{ids[0]}_source_research.xdf'
        relative = f'buell/{file}'
        data = create(ids, ecm['xsize'], tables)
        path = ROOT / 'guzzionboard/xdfs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        label = f"{' / '.join(ids)} EEPROM four-map source adaptation (research only)"
        catalog = [e for e in catalog if e.get('xdf_filename') != file]
        catalog.append({'source_url': SOURCE, 'brand': 'buell', 'family': ids[0], 'label': label,
                        'xdf_filename': file, 'vendor_path': relative,
                        'used_by': [{'brand': 'buell', 'label': f"{' / '.join(ids)} ECM IDs; verify independently"}],
                        'research_only': True})
        provenance[relative] = {'source_url': SOURCE, 'sha256': hashlib.sha256(data).hexdigest(),
                                'title': label, 'author': 'EcmDroid / XBTune, adapted by GuzziOnBoard',
                                'version': '0.1', 'verified_parse': True, 'license': 'GPL-3.0; see docs/BUELL_DDFI_RESEARCH.md',
                                'note': 'Adaptation of selected geometry, not a copy of the full database; synthetic tests only.'}
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    prov_path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
