"""Synthetic source-derived EEPROM map layout and edit checks; no ECU tested."""
from guzzionboard.maps import BUNDLED_XDF_DIR, XdfFile, fitment


def test_bueib_four_map_layout_and_research_edit():
    path = BUNDLED_XDF_DIR / 'buell' / 'BUEIB_source_research.xdf'
    xdf = XdfFile.from_file(path)
    assert fitment(path)['research_only']
    source = bytes(i & 255 for i in range(1210))
    rendered = xdf.render(source, address_base=0)
    assert rendered['errors'] == []
    tables = {table['title']: table for table in rendered['tables']}
    assert set(tables) == {'Tab_Spark_Front', 'Tab_Spark_Rear', 'Tab_Fuel_Front', 'Tab_Fuel_Rear'}
    spark = tables['Tab_Spark_Front']
    assert (spark['rows'], spark['cols']) == (10, 10)
    assert spark['values'][0][0] == source[670] * 0.25
    assert int(spark['x'][0]) == int.from_bytes(source[612:614], 'little')
    fuel = tables['Tab_Fuel_Front']
    assert (fuel['rows'], fuel['cols']) == (12, 13)
    assert fuel['raw_values'][1][0] == source[884]  # 13 data bytes + 1 skip
    edited, changes = xdf.apply_changes(source, [{'kind': 'table', 'title': 'Tab_Fuel_Front',
        'row': 1, 'col': 0, 'expected_raw': source[884], 'value': 42}], address_base=0)
    assert edited[884] == 42 and edited[883] == source[883]
    assert sum(a != b for a, b in zip(source, edited)) == 1
    assert changes[0]['image_offset'] == '0x374'


def test_bundled_buell_definition_can_export_reviewed_research_copy(tmp_path, monkeypatch):
    import hashlib
    import json
    from guzzionboard.server import Api
    from guzzionboard.workstation import Workstation
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'data'))
    source = tmp_path / 'BUEIB-synthetic.xpr'
    original = bytes(i & 255 for i in range(1210)); source.write_bytes(original)
    path = BUNDLED_XDF_DIR / 'buell' / 'BUEIB_source_research.xdf'
    sha = lambda data: hashlib.sha256(data).hexdigest()
    body = {'path': str(source), 'xdf': str(path), 'address_base': 0,
            'expected_source_sha256': sha(original), 'expected_xdf_sha256': sha(path.read_bytes()),
            'changes': [{'kind': 'table', 'title': 'Tab_Fuel_Front', 'row': 1, 'col': 0,
                         'expected_raw': original[884], 'value': 42}]}
    api = Api(Workstation(record=False))
    status, preview = api.post_maps_research_preview(body)
    assert status == 200
    body.update(accept_research_only=True, expected_candidate_sha256=preview['candidate_sha256'],
                region_start=0, region_end=1210)
    status, result = api.post_maps_research_export(body)
    assert status == 201
    candidate = __import__('pathlib').Path(result['path']).read_bytes()
    manifest = json.loads(__import__('pathlib').Path(result['manifest_path']).read_text())
    assert candidate[884] == 42 and source.read_bytes() == original
    assert manifest['research_only'] and not manifest['flash_ready']
    assert api.post_maps_harley_research_export(body)[0] == 400


def test_all_nineteen_ecm_ids_have_four_source_maps():
    from guzzionboard.buell_ddfi import IMAGE_LAYOUTS
    layouts = {
        'BUEGC': ('BUEGC', 588, 788, 13, 0),
        'BUEIA': ('BUEIA', 544, 744, 13, 0),
        'BUEJA': ('BUEJA', 560, 760, 13, 0), 'BUEKA': ('BUEJA', 560, 760, 13, 0),
        'B2RIB': ('BUEIB', 670, 870, 13, 1), 'BUEIB': ('BUEIB', 670, 870, 13, 1),
        'BUEIC': ('BUEIB', 670, 870, 13, 1),
        'BUECB': ('BUECB', 602, 802, 13, 1), 'BUEGB': ('BUEGB', 662, 862, 13, 1),
        'B3R1D': ('B3R1D', 1792, 2072, 20, 0), 'BUE1D': ('B3R1D', 1792, 2072, 20, 0),
        'B3R2D': ('B3R2D', 2048, 2328, 20, 0), 'BUE2D': ('B3R2D', 2048, 2328, 20, 0),
        'B3R3D': ('B3R3D', 2048, 2408, 20, 0), 'BUE3D': ('B3R3D', 2048, 2408, 20, 0),
        'BUEOD': ('BUEOD', 1308, 1816, 20, 0), 'BUEWD': ('BUEWD', 1492, 1816, 20, 0),
        'BUEYD': ('BUEYD', 1536, 1816, 20, 0), 'BUEZD': ('BUEZD', 1792, 2072, 20, 0),
    }
    assert set(layouts) == set(IMAGE_LAYOUTS)
    for ecm, (definition, spark_at, fuel_at, cols, skip) in layouts.items():
        path = BUNDLED_XDF_DIR / 'buell' / (definition + '_source_research.xdf')
        xdf = XdfFile.from_file(path)
        assert fitment(path)['research_only']
        size = sum(length for _, length in IMAGE_LAYOUTS[ecm])
        source = bytes(i & 255 for i in range(size))
        result = xdf.render(source, address_base=0)
        assert not result['errors'], (ecm, result['errors'])
        maps = {t['title']: t for t in result['tables']}
        assert len(maps) == 4
        assert maps['Tab_Spark_Front']['values'][0][0] == source[spark_at] * .25
        assert maps['Tab_Fuel_Front']['raw_values'][1][0] == source[fuel_at + cols + skip]
        updated, changes = xdf.apply_changes(source, [{'kind': 'table', 'title': 'Tab_Fuel_Front',
             'row': 1, 'col': 0, 'expected_raw': source[fuel_at + cols + skip],
             'value': (source[fuel_at + cols + skip] + 1) % 256}], address_base=0)
        assert sum(a != b for a, b in zip(source, updated)) == 1
        assert changes[0]['image_offset'] == hex(fuel_at + cols + skip).upper().replace('0X', '0x')
