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
    catalog = load_catalog()
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
    catalog = load_catalog()
    for ecu in data["catalog"]["ecus"]:
        assert ecu["confidence"] == catalog.ecus[ecu["id"]].confidence


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


# -- honesty --------------------------------------------------------------

#: Still refused in the browser, and meant to stay that way: a web page
#: cannot open a serial port or a CAN interface, and faking one would teach
#: the reader something false about their motorcycle.
HARDWARE_ONLY_CLAIMS = (
    "can only connect to the built-in simulator",
    "cannot enumerate",
)

#: Simulated in the browser by demo-lab.js — each of these has to be both
#: implemented *and* labelled.
SIMULATED_ENDPOINTS = (
    "/api/memory", "/api/memory/read", "/api/memory/backup",
    "/api/memory/validate", "/api/memory/write", "/api/maps",
    "/api/maps/render", "/api/maps/diff", "/api/report", "/api/procedures",
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
    # And the banner has to say it before anything is clicked.
    assert "Nothing here has touched a motorcycle." in source


def test_the_demo_shim_still_refuses_what_it_cannot_do():
    """demo-api.js keeps its 501 list for anything demo-lab.js has not taken
    over, and the message points at the local tool."""
    source = DEMO_API.read_text(encoding="utf-8")
    assert "run python3 run_server.py" in source
    assert "LOCAL_ONLY" in source


def test_the_demo_cannot_claim_a_hardware_transport():
    combined = (DEMO_API.read_text(encoding="utf-8")
                + DEMO_LAB.read_text(encoding="utf-8"))
    for claim in HARDWARE_ONLY_CLAIMS:
        assert claim in combined
    # No Web Serial, no WebUSB, no pretending.
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
