"""The Help & Reference module: wiring, content integrity and cross-links.

The knowledge base lives in ``web/help-content.js`` (data) and
``web/help-module.js`` (search, routing, spotlight). Nothing here renders a
browser page - the behaviour is covered by ``tests/browser/help-center.spec.mjs``
and the desktop suite. These tests keep the *content* honest: every internal
``#help/...`` link must resolve, ids must be unique, the acknowledgement text
must match the strings the safety code actually compares against, and the page
must load the module in the right order.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from guzzionboard.programming import ProgrammingService
from guzzionboard.safety import SafetyGate
from guzzionboard.tuning import CUSTOM_RECOMMENDATION_MODES, TUNING_ACKNOWLEDGEMENT

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX = WEB / "index.html"
CONTENT = WEB / "help-content.js"
MODULE = WEB / "help-module.js"
STYLES = WEB / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def content() -> str:
    return _read(CONTENT)


@pytest.fixture(scope="module")
def index_html() -> str:
    return _read(INDEX)


@pytest.fixture(scope="module")
def topic_ids(content: str) -> set[str]:
    return set(re.findall(r"id: '([a-z0-9-]+)',\s*title:", content))


@pytest.fixture(scope="module")
def tool_ids(content: str) -> set[str]:
    # Tools declare id and name on one line; protocols put the name on the next.
    return set(re.findall(r"id: '([a-z0-9-]+)', name:", content))


@pytest.fixture(scope="module")
def protocol_ids(content: str) -> set[str]:
    return set(re.findall(r"id: '([a-z0-9-]+)',\n\s+name:", content))


@pytest.fixture(scope="module")
def glossary_slugs(content: str) -> set[str]:
    terms = re.findall(r"\{ term: '([^']+)'", content)
    return {re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") for term in terms}


def test_files_exist_and_load_before_app_helpers():
    assert CONTENT.is_file()
    assert MODULE.is_file()
    html = _read(INDEX)
    # help-content.js defines window.GOB_HELP; help-module.js consumes it.
    assert html.index('src="help-content.js"') < html.index('src="help-module.js"')
    # app.js must load first: show('help') calls window.renderHelpCenter().
    assert html.index('src="app.js"') < html.index('src="help-module.js"')


def test_help_workspace_and_spotlight_markup(index_html: str):
    for element_id in (
        "help", "helpIntroPanel", "helpCategoryPills", "helpSearchInput",
        "helpSearchResultsPanel", "helpMainLayout", "helpTopicTree", "helpArticlePane",
        "helpSpotlightModal", "helpSpotlightInput", "helpSpotlightResults",
        "helpSpotlightFilters", "helpMenu", "helpMenuBtn", "menubarHelpSearchBtn",
    ):
        assert f'id="{element_id}"' in index_html, element_id
    assert 'data-view="help"' in index_html
    assert "Help &amp; guides" in index_html
    assert 'src="help-content.js"' in index_html
    assert 'src="help-module.js"' in index_html


def test_every_help_menu_topic_exists(index_html: str, topic_ids: set[str]):
    referenced = set(re.findall(r'data-help-topic="([a-z0-9-]+)"', index_html))
    assert referenced, "the Help menu should link to specific articles"
    for topic in referenced:
        assert topic == "glossary" or topic in topic_ids, topic


def test_categories_are_the_documented_seven(content: str):
    block = re.search(r"const CATEGORIES = \[(.*?)\n  \];", content, re.S)
    assert block, "web/help-content.js should declare CATEGORIES"
    categories = re.findall(r"\{ id: '([a-z]+)', label:", block.group(1))
    assert categories == ["howto", "tools", "protocols", "ecus", "checksums", "safety", "glossary"]


def test_content_volume_is_a_complete_manual(topic_ids, tool_ids, protocol_ids, content):
    assert len(topic_ids) >= 34, sorted(topic_ids)
    assert len(tool_ids) >= 45, sorted(tool_ids)
    assert len(protocol_ids) >= 14, sorted(protocol_ids)
    assert content.count("{ term: '") >= 60

    required_topics = {
        "getting-started",
        "howto-first-connection",
        "howto-setup-desktop",
        "howto-backup-basemap",
        "howto-xdf-editing",
        "howto-afr-jetdrive-tuning",
        "howto-custom-build-and-flash",
        "howto-brand-workflows",
        "howto-guided-diagnostics",
        "howto-sessions-and-reports",
        "tools-directory",
        "tools-search-and-links",
        "tools-keyboard-shortcuts",
        "protocols-overview",
        "protocol-evidence",
        "ecus-overview",
        "ecus-xdf-library",
        "ecu-confidence",
        "ecus-memory-geometry",
        "ecu-iaw-family",
        "ecu-5am",
        "ecu-harley-family",
        "ecu-buell",
        "ecu-honda",
        "ecu-suzuki-kawasaki",
        "ecu-triumph-other",
        "checksums-overview",
        "checksums-plugins",
        "checksums-xdf-math",
        "checksums-validate",
        "safety-gates",
        "write-path",
        "safety-recovery",
        "safety-troubleshooting",
        "safety-blocked-capabilities",
        "safety-legal",
    }
    assert required_topics <= topic_ids, sorted(required_topics - topic_ids)

    required_tools = {
        "view-garage", "view-live", "view-firmware", "view-tools", "view-discovery",
        "view-faults", "view-procedures", "view-service", "view-sessions", "view-report",
        "view-simulator", "view-overview", "view-equipment", "view-help",
        "global-search", "preferences-dialog", "preset-browser", "menu-bar",
        "adapter-panel", "backup-panel", "base-map-panel", "validate-panel",
        "maps-panel", "write-panel", "security-panel", "memory-compare-panel",
        "protocol-panel", "identity-panel", "harley-code-reference",
        "ecu-lookup", "shared-ecu-research", "honda-vfr-checksum", "honda-offline",
        "multi-research", "etv-research", "tuning-research", "juken-research",
        "harley-region", "centurion-research", "pvv-editor", "jetdrive-panel",
        "harley-memory", "buell-ddfi", "rusefi-research", "yamaha-research",
        "bajaj-checksum", "cfmoto-checksum", "service-interval", "manual-search",
        "shim-worksheet", "gearing-calculator", "z2-converter", "rpm-signal",
        "canlog-analyzer", "hdlan-observe", "yamaha-kline-observe",
        "kline-discovery", "replay-panel", "report-panel",
    }
    assert required_tools <= tool_ids, sorted(required_tools - tool_ids)

    required_protocols = {
        "kwp2000", "iso9141", "legacy-iaw", "can-iso-tp", "j1850", "hdlan",
        "kds-sds", "honda-pgmfi", "yamaha-dashboard", "buell-ddfi",
        "rusefi-serial", "jetdrive", "j2534", "security-access",
    }
    assert required_protocols <= protocol_ids, sorted(required_protocols - protocol_ids)


def test_tool_entries_are_usable(tool_ids: str | set[str], content: str):
    # Each entry declares an id, a name, a category and a summary.
    blocks = re.findall(r"\{\s*\n\s*id: '([a-z0-9-]+)', name: '([^']+)', category: '([a-z]+)',(.*?)\n\s*\},", content, re.S)
    assert len(blocks) >= 45
    for tool_id, name, category, body in blocks:
        assert name.strip(), tool_id
        assert category in {"link", "dash", "diagnostics", "memory", "calibration",
                            "telemetry", "hardware", "workshop", "search", "reference"}, tool_id
        assert "summary:" in body, tool_id
        # Every view-scoped tool must offer a jump target.
        if tool_id.startswith("view-"):
            assert re.search(r"view: '[a-z]+'", body), tool_id


def test_internal_help_links_resolve(content: str, topic_ids, tool_ids, protocol_ids, glossary_slugs):
    targets = {
        target for target in re.findall(r'#help/([A-Za-z0-9_./-]+)', content)
        if not target.endswith("/")  # placeholders such as #help/tool/<id>
    }
    assert targets

    def resolves(target: str) -> bool:
        target = target.strip("/")
        if target in topic_ids or target in tool_ids or target in protocol_ids:
            return True
        if target.startswith("tool/"):
            return target[5:] in tool_ids
        if target.startswith("tool-"):
            return target[5:] in tool_ids
        if target.startswith("protocol/"):
            return target[9:] in protocol_ids
        if target.startswith("protocol-"):
            return target[9:] in protocol_ids
        if target.startswith("topic/"):
            return target[6:] in topic_ids
        if target.startswith("topic-"):
            return target[6:] in topic_ids
        if target.startswith("glossary/"):
            return target[9:] in glossary_slugs or target == "glossary"
        # Generated at run time from /api/catalog and /api/maps.
        if target.startswith(("ecu/", "xdf/")):
            return True
        return target in topic_ids or target in tool_ids or target in protocol_ids

    broken = sorted(target for target in targets if not resolves(target))
    assert not broken, broken


def test_related_references_resolve(content: str, topic_ids, tool_ids, protocol_ids):
    related_lists = re.findall(r"related: \[([^\]]*)\]", content)
    assert related_lists
    referenced = set()
    for chunk in related_lists:
        referenced.update(re.findall(r"'([a-z0-9/-]+)'", chunk))
    assert referenced
    broken = []
    for ref in sorted(referenced):
        if ref in topic_ids or ref in protocol_ids or ref in tool_ids:
            ok = True
        elif ref.startswith("topic-"):
            ok = ref[6:] in topic_ids
        elif ref.startswith("protocol-"):
            ok = ref[9:] in protocol_ids
        elif ref.startswith("tool-"):
            ok = ref[5:] in tool_ids
        elif ref.startswith(("ecu/", "xdf/")):
            ok = True
        else:
            ok = ref in topic_ids or ref in protocol_ids or ref in tool_ids
        if not ok:
            broken.append(ref)
    assert not broken, broken


def test_acknowledgements_are_verbatim_from_the_safety_code(content: str):
    """The help text quotes what the program compares against. Keep them equal."""
    assert SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT in content
    assert SafetyGate.UNVERIFIED_WRITER_ACKNOWLEDGEMENT in content
    assert ProgrammingService.EXTERNAL_BACKUP_ACKNOWLEDGEMENT in content
    assert TUNING_ACKNOWLEDGEMENT in content


def test_custom_build_modes_are_documented(content: str):
    for mode in CUSTOM_RECOMMENDATION_MODES:
        assert mode in content
    assert "external" in content
    assert "authored-not-endorsed" in content


def test_iu_geometry_matches_the_catalog(content: str):
    """The 5AM numbers quoted in the guides must match the profile on disk."""
    import json

    from guzzionboard.catalog import load_catalog  # noqa: F401 - presence check only

    profile = json.loads(
        (Path(__file__).resolve().parent.parent / "guzzionboard" / "catalog" / "ecus" / "5am.json").read_text()
    )
    flash = profile["memory"]["regions"]["flash"]
    assert flash["start"] == 0x4000
    assert flash["size"] == 0x4C000
    assert profile["memory"]["image_size"] == 0x50000
    assert f"{flash['size']:,}" in content      # 311,296
    assert f"{profile['memory']['image_size']:,}" in content  # 327,680
    assert "0x4000" in content and "0x50000" in content


def test_module_api_and_keyboard_contract():
    module = _read(MODULE)
    for symbol in (
        "window.renderHelpCenter",
        "window.guzziHelpOpen",
        "window.guzziHelpSearch",
        "window.guzziHelpRoutes",
        "window.guzziHelpState",
        "openSpotlight",
        "renderSpotlight",
        "renderHelpCenter",
        "hashchange",
        "popstate",
    ):
        assert symbol in module, symbol
    assert "key === 'k'" in module
    assert "event.key === 'F1'" in module
    assert "'/api/catalog'" in module
    assert "'/api/maps'" in module
    assert "kind: 'action'" in module
    assert "kind: 'panel'" in module


def test_styles_cover_the_help_surfaces():
    css = _read(STYLES)
    for selector in (
        ".help-layout", ".help-sidebar-panel", ".help-topic-tree", ".help-tree-item",
        ".help-article-panel", ".help-article-title", ".help-table", ".help-jump",
        ".help-result", ".help-spotlight-card", ".help-spot-result",
        ".help-ecu-card", ".help-xdf-card", ".help-directory-card",
        ".help-glossary-term", ".help-focus-ring", ".help-search-results",
    ):
        assert selector in css, selector
    assert "@media print" in css
    assert '@media (max-width: 900px)' in css


# -- brand organisation (Tools bench and the help directory) ----------------

BRANDS_BLOCK = re.compile(r"const BRANDS = \[(.*?)\n  \];", re.S)


def _brand_ids(content: str) -> list[str]:
    match = BRANDS_BLOCK.search(content)
    assert match, "web/help-content.js should declare a BRANDS array"
    return re.findall(r"\{ id: '([a-z0-9-]+)', label:", match.group(1))


def test_tools_bench_tags_every_panel_with_a_brand(index_html: str, content: str):
    brands = _brand_ids(content)
    assert brands[0] == "general"
    assert {"harley", "honda", "buell", "yamaha", "bajaj", "cfmoto", "rusefi"} <= set(brands)

    tools_section = index_html[index_html.index('id="tools"'):]
    tools_section = tools_section[:tools_section.index("</section>")]
    panels = re.findall(r"<article[^>]*data-tool-cat=\"[a-z-]+\"[^>]*>", tools_section)
    assert len(panels) == 33, len(panels)
    tagged = {}
    for panel in panels:
        pid = re.search(r'id="([^"]+)"', panel).group(1)
        brand = re.search(r'data-tool-brand="([a-z0-9-]+)"', panel)
        assert brand, f"{pid} has no data-tool-brand"
        assert brand.group(1) in brands, (pid, brand.group(1))
        tagged[pid] = brand.group(1)
    # Every documented brand owns at least one bench module.
    assert set(tagged.values()) == set(brands), set(brands) - set(tagged.values())
    # The brand-specific ones land in the right group.
    assert tagged["harleyMemory"] == "harley"
    assert tagged["pvvEditor"] == "harley"
    assert tagged["hondaOffline"] == "honda"
    assert tagged["buellDdfi"] == "buell"
    assert tagged["gearingPanel"] == "general"
    assert tagged["ecuLookup"] == "general"


def test_both_brand_dropdowns_offer_exactly_the_documented_brands(index_html: str, content: str):
    brands = _brand_ids(content)
    for select_id in ("toolsBrandSelect", "helpBrandSelect"):
        block = re.search(
            r'<select id="' + select_id + r'".*?</select>', index_html, re.S)
        assert block, select_id
        values = re.findall(r'<option value="([a-z0-9-]+)"', block.group(0))
        assert values == ["all"] + brands, (select_id, values)


def test_the_bench_and_help_lists_stay_in_step(content: str):
    """web/app.js (the bench) and help-content.js (the directory) each keep a
    brand list; they must agree, in order, or a heading and a filter diverge."""
    app = _read(WEB / "app.js")
    block = re.search(r"const TOOL_BRANDS = \[(.*?)\n  \];", app, re.S)
    assert block, "web/app.js should declare TOOL_BRANDS"
    app_ids = re.findall(r"\{ id: '([a-z0-9-]+)', label:", block.group(1))
    assert app_ids == _brand_ids(content)


def test_help_tool_entries_carry_the_brand_of_their_bench_panel(content: str):
    brands = set(_brand_ids(content))
    tagged = dict(re.findall(r"id: '([a-z0-9-]+)', name: '[^']+', category: '[a-z]+', brand: '([a-z0-9-]+)'", content))
    assert len(tagged) == 13, sorted(tagged)
    assert set(tagged.values()) <= brands
    assert tagged["harley-memory"] == "harley"
    assert tagged["honda-vfr-checksum"] == "honda"
    assert tagged["jetdrive-panel"] == "dynojet"
    assert tagged["juken-research"] == "britek"
    # Everything without a brand is filed under General.
    all_tools = re.findall(r"id: '([a-z0-9-]+)', name: '[^']+', category: '[a-z]+'", content)
    assert set(tagged) <= set(all_tools)


def test_bench_js_has_the_brand_plumbing():
    app = _read(WEB / "app.js")
    for symbol in ("TOOL_BRANDS", "initToolsBranding", "setToolBrand", "data-brand-only", "data-tool-brand"):
        assert symbol in app, symbol
    # Filtering must combine category, brand and search.
    assert "brandMatch" in app and "catMatch" in app and "textMatch" in app

    module = _read(WEB / "help-module.js")
    for symbol in ("matchesBrand", "entryKindBrand", "renderToolDirectory", "helpBrandSelect"):
        assert symbol in module, symbol


def test_brand_styles_exist():
    css = _read(STYLES)
    for selector in (".tools-brand-bar", "#toolsBrandSelect", ".tool-brand-badge.filtered",
                     ".tools-brand-heading", ".tools-brand-only", ".help-brand-chip"):
        assert selector in css, selector


def test_every_tools_bench_panel_has_a_help_entry(index_html: str, content: str):
    """The help center must explain every tool, including the ones added later."""
    tools_section = index_html[index_html.index('id="tools"'):]
    tools_section = tools_section[:tools_section.index("</section>")]
    panels = re.findall(r"<article[^>]*>", tools_section)
    described = []
    for tag in panels:
        if 'class="panel"' not in tag or "data-tool-cat" not in tag:
            continue
        pid = re.search(r'id="([^"]+)"', tag).group(1)
        described.append(pid)
        assert f"selector: '#{pid}'" in content, f"{pid} has no TOOLS entry in help-content.js"
    assert len(described) >= 33, described
