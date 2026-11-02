"""Batch 3 cross-checks: the browser brand decoders and the Python modules.

`web/brand-tools.js` is the browser twin of four frozen Python decoders and of
the profiles in `web/multibrand-offline.js`. Nothing here repeats the arithmetic
— these tests read both sides and assert the *facts they share*: which
identifiers exist, which frames are acceptable, and which source addresses are
keyed. A formula changed on one side only will still decode; a changed identifier
list will not, so this is the seam worth guarding.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def brand_js() -> str:
    return _read(WEB / "brand-tools.js")


@pytest.fixture(scope="module")
def multi_js() -> str:
    return _read(WEB / "multibrand-offline.js")


@pytest.fixture(scope="module")
def index_html() -> str:
    return _read(WEB / "index.html")


# -- Indian: PGN and source-address table ------------------------------------

def _js_indian_table(source: str) -> dict[int, int]:
    block = re.search(r"const INDIAN_PGN_SOURCE = new Map\(\[(.*?)\]\);", source, re.S)
    assert block, "web/brand-tools.js should declare INDIAN_PGN_SOURCE"
    pairs = re.findall(r"\[(\d+),\s*(\d+)\]", block.group(1))
    assert pairs, block.group(1)
    return {int(pgn): int(source_address) for pgn, source_address in pairs}


def test_indian_source_addresses_match_the_python_module(brand_js: str):
    from guzzionboard.indian_springfield_can import FILTER_IDS, MASK, PGN_SOURCE

    assert _js_indian_table(brand_js) == dict(PGN_SOURCE)
    assert f"const INDIAN_MASK = 0x{MASK:08x};" in brand_js
    # Every key the Python decoder accepts is a key the browser filter accepts.
    mask = int(re.search(r"const INDIAN_MASK = 0x([0-9a-f]+);", brand_js).group(1), 16)
    assert mask == MASK
    js_ids = {(pgn << 8) | sa for pgn, sa in _js_indian_table(brand_js).items()}
    assert js_ids == FILTER_IDS


def test_indian_decoder_reads_the_same_pgns_as_python(brand_js: str):
    from guzzionboard.indian_springfield_can import decode_capture

    class Frame:
        def __init__(self, identifier, data):
            self.id = identifier
            self.extended = True
            self.direction = "R"
            self.data = data
            self.timestamp = 0.0

    # 1000 rpm, 7 % demand, then the 0xFFFF "not available" case.
    present = decode_capture([Frame((6 << 26) | (61444 << 8), bytes([0, 0, 0, 0x40, 0x1F, 0, 0, 0x84]))])
    absent = decode_capture([Frame((6 << 26) | (61444 << 8), bytes([0, 0, 0, 0xFF, 0xFF, 0, 0, 0xFF]))])
    assert present[0]["values"] == {"rpm_candidate": 1000.0, "engine_demand_percent_candidate": 7}
    assert absent[0]["values"] == {"rpm_candidate": None, "engine_demand_percent_candidate": None}
    # The browser prints the same numbers from the same bytes; the panel-level
    # assertions live in tests/browser/brand-tools.spec.mjs.
    assert "0xffff" in brand_js


# -- Ducati: identifiers and minimum lengths ---------------------------------

def test_ducati_frame_table_matches_the_python_module(brand_js: str):
    import inspect

    from guzzionboard import ducati_panigale_can

    source = inspect.getsource(ducati_panigale_can.decode_capture)
    assert "frame.id not in (0x18, 0x80, 0x100)" in source
    assert 'minimum = 7 if frame.id == 0x80 else 6' in source

    block = re.search(r"const DUCATI_FRAMES = \{(.*?)\n\};", brand_js, re.S)
    assert block, "web/brand-tools.js should declare DUCATI_FRAMES"
    entries = {
        int(identifier, 16): int(minimum)
        for identifier, minimum in re.findall(r"0x([0-9A-Fa-f]+):\s*\{ min: (\d)", block.group(1))
    }
    assert entries == {0x18: 6, 0x80: 7, 0x100: 6}


# -- Kawasaki: only advertise local IDs the decoder implements ---------------

def test_kawasaki_reference_table_lists_only_decodable_local_ids(brand_js: str, multi_js: str):
    sizes = re.search(r"const sizes = \{(.*?)\};", multi_js, re.S)
    assert sizes, "multibrand-offline.js should declare a local-ID length table"
    implemented = {int(key) for key in re.findall(r"(\d+): \d+", sizes.group(1))}
    assert implemented == {4, 6, 7, 9, 10, 11, 12}

    block = re.search(r"kawasaki: \{(.*?)\n  \},\n  suzuki:", brand_js, re.S)
    assert block, "web/brand-tools.js should describe the Kawasaki profile"
    advertised = {int(identifier, 16) for identifier in re.findall(r"\['0x([0-9A-Fa-f]+)'", block.group(1))}
    assert advertised == implemented

    # And the Python module knows at least those, plus request-only lengths.
    from guzzionboard.protocol.kawasaki_er6n import KawasakiER6nSession as Session

    assert advertised <= set(Session.LENGTHS)


def test_triumph_reference_table_lists_only_decodable_pids(brand_js: str, multi_js: str):
    block = re.search(r"triumph: \{(.*?)\n  \},\n  bmw:", brand_js, re.S)
    assert block
    advertised = {int(pid, 16) for pid in re.findall(r"\['PID 0x([0-9A-Fa-f]+)'", block.group(1))}
    triumph = multi_js[multi_js.index("function researchTriumph"):]
    sizes = re.search(r"const sizes = \{(.*?)\};", triumph, re.S)
    assert sizes
    implemented = {int(key) for key in re.findall(r"(\d+): \d+", sizes.group(1))}
    assert advertised == implemented


# -- the panels themselves ---------------------------------------------------

PANELS = [
    ("kawasakiKds", "kawasaki", "kawasaki"),
    ("suzukiSds", "suzuki", "suzuki"),
    ("triumphIso", "triumph", "triumph"),
    ("bmwCan", "bmw", "bmw"),
    ("ducatiCan", "ducati", "ducati"),
    ("indianJ1939", "indian", "indian"),
    ("iawGuzziPanel", "moto-guzzi", None),
    ("iawApriliaPanel", "aprilia", None),
]


def test_every_batch_three_panel_is_wired_to_its_own_controls(index_html: str):
    for panel_id, brand, prefix in PANELS:
        tag = re.search(rf'<article class="panel" id="{panel_id}"[^>]*>', index_html)
        assert tag, panel_id
        assert f'data-tool-brand="{brand}"' in tag.group(0), panel_id
        if prefix is None:
            stem = panel_id.removesuffix("Panel")
            for suffix in ("Preset", "File", "Size", "Base", "Definition", "Run", "Out", "Meta"):
                assert f'id="{stem}{suffix}"' in index_html, (panel_id, stem + suffix)
            continue
        for suffix in ("Frames", "Decode", "Out", "Meta", "Clear", "Ref"):
            assert f'id="{prefix}{suffix}"' in index_html, (panel_id, prefix + suffix)


def test_the_brand_scripts_load_after_the_decoders_they_use(index_html: str):
    """brand-tools.js calls decodeMultiResearch at click time and gobFrameLab at
    call time, so it only has to load after multibrand-offline.js; frame-lab.js
    may come later because it exports itself onto window.gobFrameLab."""
    multi = index_html.index('src="multibrand-offline.js"')
    for later in ('src="brand-tools.js"', 'src="iaw-layout.js"'):
        assert index_html.index(later) > multi, later
    assert 'window.gobBrandTools = {' in _read(WEB / "brand-tools.js")
    assert 'window.gobIawLayout = {' in _read(WEB / "iaw-layout.js")


def test_the_two_layout_panels_use_library_brands_that_exist():
    from guzzionboard.maps import library_payload

    brands = {row["brand"] for row in library_payload()["xdfs"]}
    assert {"moto_guzzi", "aprilia"} <= brands


def test_layout_geometry_matches_the_catalog_constant():
    """The panel states one fact; it must be the catalog's own number."""
    js = _read(WEB / "iaw-layout.js")
    assert "base: 0x4000," in js
    assert "size: 311296," in js
    assert "imageSize: 327680," in js

    five_am = json.loads(_read(ROOT / "guzzionboard" / "catalog" / "ecus" / "5am.json"))
    flash = five_am["memory"]["regions"]["flash"]
    assert (flash["start"], flash["size"]) == (0x4000, 311296)
