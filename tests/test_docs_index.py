"""The documentation index must not point at files that do not exist.

``docs/README.md`` is the only map of ~45 documents. Every link in it, in the
root README and in CONTRIBUTING is checked here: a dead link in the index is
how a project ends up with 40 documents nobody can navigate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

LINK = re.compile(r"\[[^\]]+\]\(([^)#]+)\)")


def markdown_files() -> list[Path]:
    return [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md",
            ROOT / "CODE_OF_CONDUCT.md", ROOT / "CHANGELOG.md", DOCS / "README.md"]


@pytest.mark.parametrize("page", markdown_files(), ids=lambda p: p.name)
def test_local_links_resolve(page):
    missing = []
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (page.parent / target).resolve()
        if not resolved.exists():
            missing.append(target)
    assert not missing, f"{page.name}: dead links {sorted(set(missing))}"


def test_the_index_covers_every_guide():
    """A document that exists but is unreachable may as well not exist."""
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    guides = {path.name for path in DOCS.glob("*.md") if path.name != "README.md"}
    missing = [name for name in guides if name not in index]
    assert not missing, (
        f"docs/README.md does not link: {sorted(missing)}; add each to a group"
    )


def test_the_index_says_which_documents_are_dated_snapshots():
    """Dated research must be labelled, or a reader takes it for current."""
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    assert "Research snapshots" in index
    assert "the code and its tests are current" in index


def test_root_files_that_github_expects_are_present():
    for name in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                 "CHANGELOG.md", "LICENSE"):
        assert (ROOT / name).is_file(), name
    assert (DOCS / "API.md").is_file()
