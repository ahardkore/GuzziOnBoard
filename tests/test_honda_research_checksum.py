"""Synthetic-only candidate/checksum geometry; not ECU or fitment validation."""
from pathlib import Path
import runpy
from guzzionboard.protocol.honda_cbr600rr import (
    HONDA_RESEARCH_LAYOUTS, HONDA_RESEARCH_IMAGE_SIZES, HONDA_RESEARCH_CHECKSUM_OFFSETS,
    HONDA_TABLE_ONLY_IDS,
)
ROOT = Path(__file__).resolve().parents[1]


def test_candidate_export_is_current_and_limited_to_known_file_offsets():
    generate = runpy.run_path(str(ROOT / 'scripts/build_honda_research_checksum.py'))['generate']
    assert (ROOT / 'web/honda-checksum-candidates.js').read_text() == generate()
    assert len(HONDA_RESEARCH_CHECKSUM_OFFSETS) == 44
    assert set(HONDA_RESEARCH_CHECKSUM_OFFSETS).issubset(HONDA_RESEARCH_LAYOUTS)
    assert all(0 < offset < HONDA_RESEARCH_IMAGE_SIZES[ecm]
               for ecm, offset in HONDA_RESEARCH_CHECKSUM_OFFSETS.items())
    assert HONDA_RESEARCH_CHECKSUM_OFFSETS[bytes.fromhex('01 01 35 05 01')] == 0x9fff
    assert HONDA_RESEARCH_CHECKSUM_OFFSETS[bytes.fromhex('01 02 13 05 01')] == 0x5fff
    assert HONDA_RESEARCH_CHECKSUM_OFFSETS[bytes.fromhex('01 02 49 01 01')] == 0xffff8
    assert HONDA_TABLE_ONLY_IDS == {bytes.fromhex('01 00 7c 01 02'), bytes.fromhex('01 00 aa 01 02')}
    for unspecified in ['01 01 35 01 01', '01 00 fa 10 01', '01 00 c5 0d 02', '01 02 ca 05 01', '01 02 de 05 01']:
        assert bytes.fromhex(unspecified) not in HONDA_RESEARCH_CHECKSUM_OFFSETS


def test_synthetic_honda_review_and_checksum_export(tmp_path, monkeypatch):
    import hashlib
    import json
    from guzzionboard.server import Api
    from guzzionboard.workstation import Workstation
    monkeypatch.setenv('GUZZIONBOARD_HOME', str(tmp_path / 'data'))
    api = Api(Workstation(record=False))
    source = tmp_path / 'honda.bin'
    original = bytearray(0x40000)
    original[0x17fc7:0x17fcc] = bytes.fromhex('01 01 25 05 01')
    original[0x20:0x24] = bytes([10,20,30,40])
    original[0x3fff8] = (-sum(original)) & 255
    source.write_bytes(original)
    xdf = tmp_path / 'test.xdf'
    xdf.write_text('''<XDFFORMAT><XDFHEADER><deftitle>Synthetic Honda</deftitle><DEFAULTS signed="0" lsbfirst="0"/><REGION size="0x40000"/></XDFHEADER>
<XDFTABLE uniqueid="fuel"><title>Fuel</title><XDFAXIS id="x"><indexcount>2</indexcount></XDFAXIS><XDFAXIS id="y"><indexcount>2</indexcount></XDFAXIS>
<XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20" mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/><MATH equation="X"/></XDFAXIS></XDFTABLE></XDFFORMAT>''')
    sha = lambda d: hashlib.sha256(d).hexdigest()
    body = {'path':str(source), 'xdf':str(xdf), 'address_base':0,
            'expected_source_sha256':sha(original), 'expected_xdf_sha256':sha(xdf.read_bytes()),
            'changes':[{'kind':'table', 'id':'fuel', 'row':0, 'col':1, 'expected_raw':20, 'value':25}]}
    status, preview = api.post_maps_research_preview(body)
    assert status == 200 and not preview['writes_file']
    proposals = preview['honda_checksum_candidates']
    assert len(proposals) == 1
    p = proposals[0]
    assert p['ecm_id'] == '0101250501' and p['checksum_offset'] == 0x3fff8
    assert (p['before'] - p['after']) & 255 == 5
    args = {**body, 'accept_research_only':True, 'expected_candidate_sha256':preview['candidate_sha256'],
            'region_start':0, 'region_end':len(original), 'honda_checksum_ecm_id':p['ecm_id'],
            'confirm_honda_checksum':True, 'expected_checksum_output_sha256':p['output_sha256']}
    for bad in ({'confirm_honda_checksum':False}, {'confirm_honda_checksum':'true'},
                {'expected_checksum_output_sha256':'0'*64}, {'honda_checksum_ecm_id':'0101250B01'},
                {'region_end':0x100}, {'expected_candidate_sha256':'0'*64}, {'accept_research_only':False}):
        assert api.post_maps_research_export({**args, **bad})[0] == 400
    assert api.post_maps_harley_research_export(args)[0] == 400
    status, saved = api.post_maps_research_export(args)
    assert status == 201
    output = Path(saved['path']).read_bytes()
    assert source.read_bytes() == original and sha(output) == p['output_sha256']
    assert sum(output) & 255 == 0 and output[0x21] == 25
    assert {i for i, (a,b) in enumerate(zip(original,output)) if a != b} == {0x21, 0x3fff8}
    manifest = json.loads(Path(saved['manifest_path']).read_text())
    assert manifest['honda_checksum'] == p and manifest['reviewed_candidate_sha256'] == preview['candidate_sha256']
    assert manifest['research_only'] and not manifest['flash_ready']
    assert api.post_maps_preview(body)[0] == 400
    source.write_bytes(bytes(len(original)))
    assert api.post_maps_research_export(args)[0] == 400


def test_checksum_proposals_reject_wrong_id_size_or_original_sum():
    from guzzionboard.honda_checksum_research import proposals
    original = bytearray(0x40000)
    original[0x17fc7:0x17fcc] = bytes.fromhex('01 01 25 05 01')
    original[0x3fff8] = (-sum(original)) & 255
    edited = original.copy(); edited[0x100] = 7
    assert len(proposals(original, edited)) == 1
    changed_id = edited.copy(); changed_id[0x17fc7] ^= 1
    assert proposals(original, changed_id) == []
    assert proposals(original[:-1], edited) == []
    invalid = original.copy(); invalid[0] ^= 1
    assert proposals(invalid, edited) == []
    checksum_only = original.copy(); checksum_only[0x3fff8] ^= 1
    assert proposals(original, checksum_only) == []


def test_example_only_associations_never_inherit_guessed_checksum_locations():
    from guzzionboard.protocol.honda_cbr600rr import (HONDA_EXAMPLE_ONLY_IDS,
        HONDA_EXAMPLE_INFERRED_IDS, HONDA_FAMILY_INFERRED_IDS, HONDA_SOURCE_CONFLICTS)
    expected = {
        '0100b00401':('38770-MFL-691',0x2880a), '0100b00501':('38770-MFL-861',0x2880a),
        '0100b00801':('38770-MFL-871',0x2880a), '0100b70301':('38770-MFL-F21',0x2880a),
        '0100b70501':('38770-MFL-L21',0x2880a), '0102480501':('38770-MKF-L13',0x7c745),
        '0101110f01':('38770-KPP-602',0xc3cc), '0102f20111':('38770-MJW-DR1',0x18bb7),
        '0100330401':('38770-MFJ-A02',0x280b5), '01014e0d03':('38770-MJE-T15',0x15f72),
        '01019c0d02':('38770-MJE-T52',0x15f72),
    }
    assert HONDA_EXAMPLE_ONLY_IDS == {bytes.fromhex(k) for k in expected}
    for text, layout in expected.items():
        ecm = bytes.fromhex(text)
        assert HONDA_RESEARCH_LAYOUTS[ecm] == layout
        assert ecm in HONDA_EXAMPLE_INFERRED_IDS
        assert ecm not in HONDA_RESEARCH_CHECKSUM_OFFSETS
    table_id, example_id = bytes.fromhex('0102490501'), bytes.fromhex('0102480501')
    assert table_id in HONDA_FAMILY_INFERRED_IDS
    assert HONDA_RESEARCH_LAYOUTS[table_id] == HONDA_RESEARCH_LAYOUTS[example_id]
    assert HONDA_RESEARCH_CHECKSUM_OFFSETS[table_id] == 0xffff8
    assert 'differs' in HONDA_SOURCE_CONFLICTS[table_id] and 'differs' in HONDA_SOURCE_CONFLICTS[example_id]
    assert all(bytes.fromhex(k) in HONDA_SOURCE_CONFLICTS for k in list(expected)[:5])


def test_every_synthetic_python_candidate_matches_generated_browser_source_data():
    import json
    from guzzionboard.honda_checksum_research import proposals
    text = (ROOT / 'web/honda-checksum-candidates.js').read_text()
    data = json.loads(text.split('const HONDA_CHECKSUM_CANDIDATES = ', 1)[1].split(';\n', 1)[0])
    for ecm, offset in HONDA_RESEARCH_CHECKSUM_OFFSETS.items():
        part, id_offset = HONDA_RESEARCH_LAYOUTS[ecm]
        original = bytearray(HONDA_RESEARCH_IMAGE_SIZES[ecm])
        original[id_offset:id_offset+5] = ecm
        original[offset] = (-sum(original)) & 255
        edited = original.copy(); edited[0] = 1
        match = next(c for c in proposals(original, edited) if c['ecm_id'] == ecm.hex().upper())
        web = data[ecm.hex().upper()]
        for key in ('part','id_offset','checksum_offset','read_start','source','commented'):
            assert match[key] == web[key]
        assert match['part'] == part and match['after'] == ((original[offset] - 1) & 255)
        if part.startswith('38770-MNF-'):
            assert 'example filename' in match['conflict'] and match['conflict'] == web['conflict']
