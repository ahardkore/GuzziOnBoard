"""The hosted browser demo: data export, page wiring, and honesty.

The workstation UI is served two ways. Locally it talks to ``run_server.py``.
On a static host (GitHub Pages) ``web/demo-api.js`` answers the same /api calls
inside the page, from a catalog snapshot this suite keeps in sync.

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
    assert html.index('src="demo-api.js"') < html.index('src="app.js"')


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

LOCAL_ONLY_ENDPOINTS = (
    "/api/memory", "/api/memory/write", "/api/maps", "/api/maps/render",
    "/api/report", "/api/procedures", "/api/sessions/compare",
    "/api/tools/gearing", "/api/tools/rpmsignal", "/api/adapter",
)


def test_capabilities_that_need_the_local_tool_are_refused_not_faked():
    source = DEMO_API.read_text(encoding="utf-8")
    for path in LOCAL_ONLY_ENDPOINTS:
        assert f"'{path}'" in source, f"{path} is unhandled in the demo shim"
    assert "run python3 run_server.py" in source


def test_the_demo_cannot_claim_a_hardware_transport():
    source = DEMO_API.read_text(encoding="utf-8")
    assert "can only connect to the built-in simulator" in source


# -- behaviour (node) -----------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_demo_backend_drives_a_whole_session():
    """Run the browser-side shim through a full simulated session."""
    result = subprocess.run(
        ["node", str(Path(__file__).parent / "demo_browser_check.mjs")],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
