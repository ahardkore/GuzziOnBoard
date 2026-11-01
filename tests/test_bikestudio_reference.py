"""Source-listed fitments are research references, never communication evidence."""
import json
import re
from pathlib import Path

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportUnavailable

DATA = json.loads(Path('web/bikestudio-fitment.json').read_text())


def test_curated_subset_has_source_scoped_records_and_preserves_bad_data():
    groups = DATA['groups']
    assert len(groups) == 32 and sum(len(g['entries']) for g in groups) == 260
    assert DATA['source'] == 'https://bikestudio.io/ecu?lang=en'
    assert len({g['slug'] for g in groups}) == len(groups)
    for group in groups:
        assert re.fullmatch(r'(honda|yamaha)-[a-z0-9-]+', group['slug'])
        assert group['make'] in ('Honda', 'Yamaha') and group['entries']
        assert all(re.fullmatch(r'[A-Z0-9/-]+', e['part']) for e in group['entries'])
        assert all(set(e) == {'part','years','cc','market'} for e in group['entries'])
    cbr = next(g for g in groups if g['slug'] == 'honda-cbr-1000-rr')
    assert next(e for e in cbr['entries'] if e['part'] == '38770-MGP-A01')['cc'] == '150'
    ct = next(g for g in groups if g['slug'] == 'honda-ct-125')
    assert next(e for e in ct['entries'] if e['part'] == '38770-K2E-T31')['years'] == '2025–2024'
    cb = next(g for g in groups if g['slug'] == 'honda-cb-150-r')
    assert next(e for e in cb['entries'] if e['part'] == '38770-K94-T02')['years'] == '2021–2019'
    assert next(e for e in cb['entries'] if e['part'] == '38770-K15-903')['cc'] == '149,48'
    cbr650 = next(g for g in groups if g['slug'] == 'honda-cbr-650-f')
    assert next(e for e in cbr650['entries'] if e['part'] == '38770-MJE-T52')['cc'] == '550'
    xmax = next(g for g in groups if g['slug'] == 'yamaha-xmax')
    assert next(e for e in xmax['entries'] if e['part'] == 'B741') == {'part':'B741', 'years':'', 'cc':'', 'market':'Asia'}
    assert next(e for e in xmax['entries'] if e['part'] == 'B5X0')['cc'] == '292'
    pcx = next(g for g in groups if g['slug'] == 'honda-pcx-150')
    assert next(e for e in pcx['entries'] if e['part'] == '30400-K97A-U01')['market'] == 'Philippines'
    mgz = next(g for g in groups if g['slug'] == 'honda-cb-500-f-cbr-500-r')
    assert any(e['part'] == '38770-MGZ-A03' and e['years'] == '2013–2016' and e['market'] == 'Asia' for e in mgz['entries'])


def test_reference_profile_is_neutral_and_no_new_bike_claims_protocol():
    c = load_catalog(overlays=False)
    p = c.ecu('bikestudio_reference_only')
    assert p.transport == 'none' and not p.capabilities and p.session['physical_supported'] is False
    assert p.session['simulator_supported'] is False and not p.memory['read_supported'] and not p.memory['write_supported']
    for make, model, y in [('Yamaha','YZF-R15',2021),('Yamaha','Mio M3',2018),('Yamaha','AEROX 155',2020),('Yamaha','NMAX 155',2022),('Yamaha','NMAX NEW',2026),('Honda','Grom / MSX 125',2016),('Honda','CT 125',2022),('Honda','ADV 150',2021),('Honda','ADV 160',2023),('Honda','ADV 160',2026),('Honda','PCX-150',2019),('Honda','PCX 160',2023),('Honda','PCX 160',2025),('Yamaha','AEROX NEW',2024),('Yamaha','MT15',2020),('Yamaha','XSR 155',2020),('Yamaha','WR 155',2021),('Yamaha','XMAX',2023)]:
        entry, profile = c.resolve(model,y,make)
        assert profile.id == p.id and entry.confidence == 'unknown'
        for kind in ('simulator', 'kline', 'can'):
            ws = Workstation(record=False)
            ws.select(make=make, model=model, year=y, transport=kind)
            with pytest.raises(TransportUnavailable):
                ws.connect(mode='simulator' if kind == 'simulator' else 'read_only')
            assert ws.service is None or not ws.service.connected


def test_new_reference_coverage_is_supported_by_valid_source_years():
    c = load_catalog(overlays=False)
    for v in c.vehicles:
        if v.ecu != 'bikestudio_reference_only':
            continue
        group = next(g for g in DATA['groups'] if g['make'] == v.make and v.model in g['garage_models'])
        covered = set()
        for record in group['entries']:
            match = re.fullmatch(r'(\d{4})(?:–(\d{4}))?', record['years'])
            if match:
                a,b = int(match[1]),int(match[2] or match[1])
                if a <= b:
                    covered.update(range(a,b+1))
        assert all(y in covered for y in range(v.year_from,v.year_to+1)), v.model
