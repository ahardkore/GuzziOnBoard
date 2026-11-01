"""Source XDFs are research-only; binary firmware is not redistributed."""
import json
from pathlib import Path
import pytest
from guzzionboard.maps import XdfFile

ROOT = Path(__file__).resolve().parents[1] / 'guzzionboard' / 'xdfs'

@pytest.mark.parametrize('variant,tables,expected_title', [
    ('773', 45, 'Honda VFR1200F 2010 NA 38770-MGE-773'),
    ('701', 46, 'Honda VFR1200F 2010 NA 38770-MGE-773'),  # upstream title conflict
    ('D41', 45, 'Honda VFR1200F 2013 German 38770-MGE-D41'),
])
def test_vfr_xdf_parse_and_research_catalog(variant, tables, expected_title):
    name = f'HONDA_VFR1200F_MGE_{variant}.xdf'
    xdf = XdfFile.from_file(ROOT / 'honda' / name)
    assert xdf.title == expected_title
    assert len(xdf.tables) == tables and len(xdf.constants) == 2
    assert xdf.data_end() == 0x7fff9 and not xdf.unsupported
    entries = json.loads((ROOT / 'catalog.json').read_text())
    entry = next(e for e in entries if e.get('xdf_filename') == name)
    assert entry['research_only'] is True
    if variant == '701':
        assert 'title' in entry['label'] and '773' in entry['label']
