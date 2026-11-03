"""Batch 4 guards: the bench calculators' constants, panels and honesty notes.

The arithmetic itself is tested where it runs — `tests/browser/bench-calculators.spec.mjs`
executes `web/bench-calculators.js` in the browser and checks hand-computed
values. What is checked here is the part a browser test cannot see: that the
constants are the ones the documentation cites, that the panels are wired under
General, that the blend model is the single source of the petrol-family fuels,
and that the caution language is still in place.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


@pytest.fixture(scope="module")
def bench_js() -> str:
    return (WEB / "bench-calculators.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def help_js() -> str:
    return (WEB / "help-content.js").read_text(encoding="utf-8")


PANELS = [
    ("injectorPanel", "inj", ("Power", "Bsfc", "Cylinders", "Duty", "Fuel", "Pressure", "Rated", "Flow", "Run", "Out", "Meta")),
    ("dynoCorrectionPanel", "dyno", ("Measured", "Unit", "Standard", "Temp", "Pressure", "Humidity", "Altitude", "Run", "Out", "Meta")),
    ("fuelBlendPanel", "blend", ("Ethanol", "Mode", "Value", "Run", "Out", "Meta")),
]


def test_the_three_calculators_are_general_panels_with_their_controls(index_html: str):
    for panel_id, prefix, controls in PANELS:
        tag = re.search(rf'<article class="panel" id="{panel_id}"[^>]*>', index_html)
        assert tag, panel_id
        assert 'data-tool-brand="general"' in tag.group(0), panel_id
        for control in controls:
            assert f'id="{prefix}{control}"' in index_html, (panel_id, prefix + control)


def test_each_calculator_has_a_help_entry_with_a_jump_target(help_js: str):
    entries = {
        "injector-panel": "#injectorPanel",
        "dyno-correction": "#dynoCorrectionPanel",
        "fuel-blend": "#fuelBlendPanel",
    }
    for entry_id, selector in entries.items():
        block = re.search(rf"id: '{entry_id}'(.*?)\n    \}},", help_js, re.S)
        assert block, entry_id
        assert f"selector: '{selector}'" in block.group(1), entry_id
        assert "caution:" in block.group(1), entry_id


def test_the_constants_are_the_ones_the_docs_cite(bench_js: str):
    # SAE J1349's documented constants.
    assert "1.176 * ((990 / dry)" in bench_js
    assert "- 0.176" in bench_js
    assert "298.15" in bench_js
    # Reference conditions each standard is corrected against.
    assert "tempK: 293.15, pressureHpa: 1013.25" in bench_js     # DIN 70020
    assert "tempK: 288.15, pressureHpa: 1013.25" in bench_js     # SAE J607
    assert "tempK: 293.15, pressureHpa: 1000" in bench_js        # ISO 1585
    # Psychrometrics and ISA.
    assert "287.058" in bench_js and "461.495" in bench_js
    assert "2.25577e-5" in bench_js and "5.25588" in bench_js
    # lb → kg, and the four-stroke injection window.
    assert "0.45359237" in bench_js
    assert "120000 / speed" in bench_js


def test_petrol_family_fuels_are_derived_from_the_blend_model(bench_js: str):
    """One ethanol model, not two: the injector and blend panels must agree."""
    block = re.search(r"const BENCH_FUELS = \{(.*?)\n\};", bench_js, re.S)
    assert block, "BENCH_FUELS should exist"
    for fuel in ("petrol", "e10", "e85"):
        entry = re.search(rf"{fuel}: \{{(.*?)\}},", block.group(1), re.S)
        assert entry, fuel
        assert "ethanolBlend(" in entry.group(1), fuel
    # Methanol and diesel are not ethanol blends and keep their own constants.
    assert re.search(r"methanol: \{ id: 'methanol'.*stoich: 6\.5", block.group(1))
    assert re.search(r"diesel: \{ id: 'diesel'.*stoich: 14\.5", block.group(1))


def test_the_e85_model_difference_is_stated_rather_than_hidden(bench_js: str, index_html: str):
    """The linear model gives 9.86:1; handbooks quote 9.8:1. Say so."""
    assert "9.8:1" in bench_js
    assert "linear model" in bench_js
    panel = index_html[index_html.index('id="fuelBlendPanel"'):]
    panel = panel[:panel.index("</article>")]
    assert "model, not a measurement" in panel


def test_the_wideband_and_calculator_share_the_non_ethanol_fuels(bench_js: str):
    wideband = (WEB / "wideband-lab.js").read_text(encoding="utf-8")
    fuels = re.search(r"const WIDEBAND_FUELS = \{(.*?)\};", wideband, re.S)
    assert fuels, "wideband-lab.js should declare WIDEBAND_FUELS"
    stoich = {float(value) for value in re.findall(r"^\s*(\d+(?:\.\d+)?): '", fuels.group(1), re.M)}
    assert 6.5 in stoich      # methanol
    assert 14.5 in stoich     # diesel
    assert "stoich: 6.5" in bench_js and "stoich: 14.5" in bench_js


def test_every_panel_carries_a_caution(index_html: str):
    for panel_id, _, _ in PANELS:
        panel = index_html[index_html.index(f'id="{panel_id}"'):]
        panel = panel[:panel.index("</article>")]
        assert 'tip warn' in panel, panel_id


def test_the_calculators_never_claim_to_write_or_connect(index_html: str, bench_js: str):
    for panel_id, _, _ in PANELS:
        panel = index_html[index_html.index(f'id="{panel_id}"'):]
        panel = panel[:panel.index("</article>")]
        lowered = panel.lower()
        # No transmit, no adapter, no programming language in a calculator.
        assert "fetch(" not in panel
        assert "transmit" not in lowered or "never transmits" in lowered
    # The file talks to nothing: no network, no storage, no desktop host.
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "gobDesktop"):
        assert forbidden not in bench_js, forbidden
