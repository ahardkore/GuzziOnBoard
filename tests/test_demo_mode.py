"""The hosted browser demo: data export, page wiring, and honesty.

The workstation UI is served two ways. Locally it talks to ``run_server.py``.
On a static host (GitHub Pages) ``web/demo-api.js`` answers the same /api calls
inside the page, from a catalog snapshot this suite keeps in sync, and
``web/demo-lab.js`` simulates the half of the workstation that needs files,
long jobs or a dump: ECU memory, maps, sessions, reports, guided tests and the
workshop tools.

These tests guard the three ways that arrangement can rot:

* the snapshot drifting away from the Python catalog,
* the page losing the script that makes it work (or the marker that switches
  it off when the real server *is* there),
* the demo quietly claiming a capability it does not have.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DEMO_DATA = WEB / "demo-data.json"
DEMO_API = WEB / "demo-api.js"
DEMO_LAB = WEB / "demo-lab.js"

sys.path.insert(0, str(ROOT))

from guzzionboard.catalog import load_catalog              # noqa: E402
from guzzionboard.server import mark_live_backend          # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import build_demo_data                                     # noqa: E402


# -- the exported catalog -------------------------------------------------

def test_demo_data_is_in_sync_with_the_catalog():
    """Regenerating must be a no-op; otherwise the demo shows stale coverage."""
    expected = build_demo_data.render(build_demo_data.build())
    assert DEMO_DATA.read_text(encoding="utf-8") == expected, (
        "web/demo-data.json is stale — run python3 scripts/build_demo_data.py"
    )


def test_demo_data_covers_every_ecu_and_vehicle():
    data = json.loads(DEMO_DATA.read_text(encoding="utf-8"))
    catalog = load_catalog(overlays=False)
    assert len(data["catalog"]["ecus"]) == len(catalog.ecus)
    assert len(data["vehicle_entries"]) == len(catalog.vehicles)
    assert set(data["profiles"]) == set(catalog.ecus)


def test_demo_data_carries_the_scaling_the_browser_needs():
    """A sample without its scaling would be a number the demo invented."""
    data = json.loads(DEMO_DATA.read_text(encoding="utf-8"))
    rpm = data["profiles"]["5am"]["parameters"]["rpm"]
    coolant = data["profiles"]["5am"]["parameters"]["coolant_temp"]
    assert rpm["local_id"] == 0x30
    assert coolant["bias"] == -40
    for param in data["profiles"]["5am"]["parameters"].values():
        assert {"scale", "bias", "recip", "local_id"} <= set(param)


def test_demo_data_confidence_is_never_promoted():
    """The demo must not look more trustworthy than the catalog it came from."""
    data = json.loads(DEMO_DATA.read_text(encoding="utf-8"))
    catalog = load_catalog(overlays=False)
    for ecu in data["catalog"]["ecus"]:
        assert ecu["confidence"] == catalog.ecus[ecu["id"]].confidence


def test_the_hosted_demo_never_shows_a_locally_applied_protocol_update():
    """A promotion is per-install evidence; the published snapshot is not one."""
    data = json.loads(DEMO_DATA.read_text(encoding="utf-8"))
    assert data["catalog"]["summary"]["protocol_updates"]["applied"] is False
    for ecu in data["catalog"]["ecus"]:
        assert ecu.get("field_confirmation", {}) == {}
        assert ecu.get("capability_confidence", {}) == {}


# -- page wiring ----------------------------------------------------------

def test_workstation_page_loads_the_demo_shim_before_the_app():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'src="demo-api.js"' in html
    assert 'src="demo-lab.js"' in html
    # demo-lab.js builds on demo-api.js, and both must be in place before
    # app.js makes its first call.
    assert html.index('src="demo-api.js"') < html.index('src="demo-lab.js"')
    assert html.index('src="demo-lab.js"') < html.index('src="app.js"')


def test_local_server_marks_the_page_so_the_shim_stands_down():
    marked = mark_live_backend(b"<html>\n<body>\n<p>hi</p>\n</body></html>")
    assert b'<body data-backend="live">' in marked
    # Idempotent: serving it twice must not double-mark.
    assert mark_live_backend(marked) == marked
    assert 'document.body.dataset.backend === \'live\'' in \
        DEMO_API.read_text(encoding="utf-8")


def test_landing_page_links_the_workstation_demo():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'href="web/index.html"' in html


def test_workstation_has_accessible_guided_state_prompts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'role="dialog"' in html and 'aria-modal="true"' in html
    assert "prepareEngineState" in source
    for instruction in (
        "stop it with the kill switch",
        "Leave the ignition key ON",
        "start the engine",
        "Turn the ignition key OFF",
        "Begin listening",
    ):
        assert instruction.lower() in source.lower()
    assert "window.confirm" not in source


def test_the_protocol_evidence_panel_is_wired_and_honest():
    """The field-confirmation UI: every control exists, and no promise it cannot keep."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    for ident in (
        "protocolPanel", "protocolOut", "protocolUrl", "protocolRefreshBtn",
        "protocolCheckBtn", "protocolRevertBtn", "protocolKeysDetails",
        "protocolKeysOut", "protocolKeyId", "protocolKeyHex", "protocolPinBtn",
        "confirmationBuildBtn", "confirmationNoteChk", "protocolActionOut",
    ):
        assert f'id="{ident}"' in html, ident
    # ... and the controls the script drives are ones the page actually has.
    for ident in (
        "protocolOut", "protocolUrl", "protocolRefreshBtn", "protocolCheckBtn",
        "protocolRevertBtn", "protocolKeysOut", "protocolKeyId", "protocolKeyHex",
        "protocolPinBtn", "confirmationBuildBtn", "confirmationNoteChk",
        "protocolActionOut",
    ):
        assert ident in source, ident
    # Pinning must be a paste, never a click that trusts whatever arrived.
    prose = " ".join(html.split())
    assert "never one taken from the pack you are about to install" in prose
    assert "'/api/protocol-updates/pin-key'" in source
    assert "Forget it first" in source
    assert "window.prompt" not in source and "window.confirm" not in source
    for endpoint in (
        "'/api/protocol-updates'",
        "'/api/protocol-updates/check'",
        "'/api/protocol-updates/apply'",
        "'/api/protocol-updates/revert'",
        "'/api/confirmations/build'",
    ):
        assert endpoint in source, endpoint
    # Applying quotes the digest from the preview, so consent cannot be reused.
    assert "expected_sha256" in source
    assert "two independent sessions" in html.lower()
    assert "Nothing is uploaded by GuzziOnBoard" in html
    assert "A simulated session cannot confirm anything about hardware" in html


def test_map_builder_exposes_professional_editing_without_weakening_the_gate():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    for ident in (
        "mapSetBtn", "mapAddBtn", "mapPercentBtn",
        "mapInterpolateRowsBtn", "mapInterpolateColsBtn",
        "mapSmoothBtn", "mapBlendBtn", "mapCopyBtn", "mapPasteBtn",
        "mapUndoBtn", "mapRedoBtn", "mapExportProjectBtn", "mapImportProjectBtn",
        "mapsValidateDefinitionBtn", "mapLogAnalyzeBtn", "mapLogStageBtn",
        "mapLogStddev",
        "mapChecksumProvider", "mapPackageSelect", "mapPackageStageBtn",
    ):
        assert f'id="{ident}"' in html
    assert "'/api/maps/preview'" in source
    assert "expected_plan_sha256" in source
    assert "Shift-click for a rectangle" in html
    assert "source SHA-256" in source
    assert "liability acknowledgement" in source.lower()


def test_unvalidated_can_ids_are_only_defaults_in_the_virtual_rehearsal():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    tour = (WEB / "tour.html").read_text(encoding="utf-8")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'id="canTxId" placeholder="not validated"' in html
    assert 'id="canRxId" placeholder="not validated"' in html
    assert "else if (kind === 'cansim')" in source
    assert "A virtual pair for transport rehearsal only" in source
    assert "physical CAN sessions are blocked" in tour
    assert "assumes the standard pair" not in tour


# -- honesty --------------------------------------------------------------

#: Simulated in the browser by demo-lab.js — each of these has to be both
#: implemented *and* labelled.
SIMULATED_ENDPOINTS = (
    "/api/memory", "/api/memory/read", "/api/memory/backup",
    "/api/memory/validate", "/api/memory/write", "/api/maps",
    "/api/maps/render", "/api/maps/diff", "/api/maps/validate-definition",
    "/api/maps/analyze-log", "/api/maps/preview", "/api/maps/build",
    "/api/checksum-providers", "/api/recommendations",
    "/api/recommendations/validate", "/api/physical-validation",
    "/api/physical-validation/validate", "/api/report", "/api/procedures",
    "/api/procedures/start", "/api/procedures/advance", "/api/sessions",
    "/api/sessions/replay", "/api/sessions/export", "/api/sessions/compare",
    "/api/tools/gearing", "/api/tools/z2dif", "/api/tools/rpmsignal",
    "/api/tools/canlog", "/api/tools/klinelog", "/api/adapter",
)


def test_the_simulated_half_is_implemented_not_refused():
    source = DEMO_LAB.read_text(encoding="utf-8")
    for path in SIMULATED_ENDPOINTS:
        assert f"'{path}'" in source, f"{path} is not handled by demo-lab.js"


def test_the_simulated_half_says_that_it_is_simulated():
    """Faking a process is fine; letting it pass for the real thing is not."""
    source = DEMO_LAB.read_text(encoding="utf-8")
    assert "simulated: true" in source
    # The two compressions the user has to be told about.
    assert "Time-compressed" in source
    assert "time-compressed" in source.lower()
    # And the banner has to establish the virtual boundary before a click.
    assert "Nothing here can " in source and "connect to real hardware." in source


def test_the_hosted_demo_is_virtual_only_but_connector_steps_are_runnable():
    api_source = DEMO_API.read_text(encoding="utf-8")
    lab_source = DEMO_LAB.read_text(encoding="utf-8")
    app_source = (WEB / "app.js").read_text(encoding="utf-8")
    combined = api_source + lab_source
    assert "name: 'Demo motorcycle'" in api_source
    assert "transport: 'simulator'" in api_source
    assert "demo://virtual-adapter" in api_source
    assert "demo://virtual-kline" in lab_source
    assert "SIMULATED CONNECTOR" in lab_source
    assert "isHostedDemo" in app_source
    assert "vehicle.ecu === '5am'" in app_source
    assert "Griso 1200 8V" in app_source
    # The stand-ins never request browser access to real hardware.
    assert "navigator.serial" not in combined
    assert "navigator.usb" not in combined


# -- behaviour (node) -----------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_demo_backend_drives_a_whole_session():
    """Run the browser-side shim through a full simulated session."""
    result = subprocess.run(
        ["node", str(Path(__file__).parent / "demo_browser_check.mjs")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


#: Three definitions chosen to span the shapes the parser has to get right:
#: a big 5AM table set, a 15M/15P one, and a non-Guzzi family.
PARITY_XDFS = (
    "moto_guzzi/5AM_GuzziDiag_Two_Lambda_V1.40.xdf",
    "moto_guzzi/15M_GuzziDiag_V2.32.xdf",
    "aprilia/5AM_Aprilia_GP850_V1.00.xdf",
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_xdf_parser_agrees_with_the_python_one(tmp_path):
    """demo-lab.js carries a port of maps.py; a port that disagrees with the
    original would show the reader tables that are subtly wrong."""
    from guzzionboard import maps

    image = bytes((i * 7 + 13) % 256 for i in range(311296))
    image_path = tmp_path / "image.bin"
    image_path.write_bytes(image)

    checked = 0
    for relative in PARITY_XDFS:
        xdf_path = maps.BUNDLED_XDF_DIR / relative
        if not xdf_path.exists():                      # pragma: no cover
            continue
        out = tmp_path / (xdf_path.stem + ".json")
        result = subprocess.run(
            ["node", str(Path(__file__).parent / "demo_xdf_parity.mjs"),
             str(xdf_path), str(image_path), str(out)],
            capture_output=True, text=True, cwd=ROOT, timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        expected = maps.XdfFile.from_file(xdf_path).render(image)
        rendered = json.loads(out.read_text(encoding="utf-8"))
        assert rendered == json.loads(json.dumps(expected)), (
            f"{relative}: the browser render differs from maps.py"
        )
        checked += 1
    assert checked, "no bundled definition was available to compare"
