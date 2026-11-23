"""The API reference has to describe the routes that exist.

``docs/API.md`` is the only place a contributor can see all 103 routes at
once. A reference that silently omits a new route is worse than none: it is a
document that looks complete.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from guzzionboard.server import ROUTES_GET, ROUTES_POST

DOC = Path(__file__).resolve().parent.parent / "docs" / "API.md"


@pytest.fixture(scope="module")
def reference() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("method,routes", [("GET", ROUTES_GET), ("POST", ROUTES_POST)])
def test_every_route_is_documented(reference, method, routes):
    missing = [path for path in routes if f"`{method} {path}`" not in reference]
    assert not missing, f"undocumented {method} routes: {sorted(missing)}"


@pytest.mark.parametrize("method,routes", [("GET", ROUTES_GET), ("POST", ROUTES_POST)])
def test_every_documented_route_exists(reference, method, routes):
    """A removed route must not linger in the table as if it still answered."""
    documented = {
        line.split("`")[1].split(" ", 1)[1]
        for line in reference.splitlines()
        if line.startswith("| `") and line.split("`")[1].startswith(f"{method} ")
    }
    assert documented == set(routes)


def test_the_reference_documents_the_error_contract(reference):
    for code in ("bad_request", "safety", "token", "not_connected", "internal"):
        assert f"`{code}`" in reference, code
    assert "demo_local_only" in reference
    assert "X-GuzziOnBoard-Token" in reference


def test_the_reference_does_not_promise_the_lan_by_default(reference):
    """The console server binds loopback; the doc must say so."""
    assert "binds loopback only" in reference
