"""The `vendor/guzzidiag/` mirror and what was imported out of it.

These tests are integrity checks on third-party content, not on behaviour:
they fail if the mirrored archive drifts from its manifest, if a vendored
XDF no longer matches the bytes recorded in PROVENANCE.json, or if an
imported file stops parsing with this project's own parser.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from guzzionboard.maps import XdfFile, load_bundled_xdfs

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = REPO_ROOT / "vendor" / "guzzidiag"
MANIFEST_PATH = VENDOR_ROOT / "MANIFEST.json"
XDF_ROOT = REPO_ROOT / "guzzionboard" / "xdfs"


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST_PATH.exists():
        pytest.skip("vendor mirror not present in this checkout")
    return load(MANIFEST_PATH)


def test_manifest_matches_the_files_on_disk(manifest):
    listed = {e["path"] for e in manifest["files"]}
    actual = {
        str(p.relative_to(REPO_ROOT))
        for section in ("xdf", "tools")
        for p in (VENDOR_ROOT / section).iterdir()
        if p.is_file()
    }
    assert listed == actual, (
        "run python3 scripts/vendor_manifest.py after changing the mirror"
    )


def test_every_mirrored_file_hashes_as_recorded(manifest):
    for entry in manifest["files"]:
        data = (REPO_ROOT / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"], entry["filename"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], \
            entry["filename"]


def test_xdf_section_holds_xdfs_and_tools_section_does_not(manifest):
    for entry in manifest["files"]:
        if entry["section"] != "xdf":
            continue
        names = [c["name"].lower() for c in entry["contents"]]
        assert any(n.endswith(".xdf") for n in names), entry["filename"]


def test_no_duplicate_archives_in_the_mirror(manifest):
    by_hash: dict[str, list[str]] = {}
    for entry in manifest["files"]:
        by_hash.setdefault(entry["sha256"], []).append(entry["filename"])
    dupes = {h: n for h, n in by_hash.items() if len(n) > 1}
    assert not dupes, f"duplicate downloads in the mirror: {dupes}"


def test_every_mirrored_xdf_zip_was_imported(manifest):
    provenance = load(XDF_ROOT / "PROVENANCE.json")
    imported = {e["origin_zip"].lower() for e in provenance.values()
                if e.get("origin_zip")}
    missing = sorted(
        e["filename"] for e in manifest["files"]
        if e["section"] == "xdf" and e["filename"].lower() not in imported
    )
    assert not missing, (
        "mirrored but not imported — run "
        f"scripts/import_xdfs.py --source vendor/guzzidiag/xdf: {missing}"
    )


def test_vendored_xdfs_match_provenance_hashes():
    provenance = load(XDF_ROOT / "PROVENANCE.json")
    assert provenance, "nothing vendored"
    for vendor_path, entry in provenance.items():
        data = (XDF_ROOT / vendor_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], vendor_path


def test_vendored_xdfs_came_out_of_the_mirror_bytes_unchanged(manifest):
    provenance = load(XDF_ROOT / "PROVENANCE.json")
    mirrored = {e["filename"].lower(): REPO_ROOT / e["path"]
                for e in manifest["files"] if e["section"] == "xdf"}
    checked = 0
    for vendor_path, entry in provenance.items():
        zip_path = mirrored.get(str(entry.get("origin_zip", "")).lower())
        if zip_path is None:
            continue
        with zipfile.ZipFile(zip_path) as zf:
            member = next(m for m in zf.namelist()
                          if m.lower().endswith(".xdf")
                          and "__macosx" not in m.lower())
            assert zf.read(member) == (XDF_ROOT / vendor_path).read_bytes(), \
                vendor_path
        checked += 1
    assert checked, "no vendored file could be traced back to the mirror"


def test_every_bundled_xdf_still_parses():
    files = load_bundled_xdfs()
    assert len(files) >= 72
    assert all(isinstance(f, XdfFile) for f in files)
    assert sum(len(f.tables) for f in files) >= 2600


def test_catalog_entries_are_consistent_with_what_is_vendored():
    catalog = load(XDF_ROOT / "catalog.json")
    provenance = load(XDF_ROOT / "PROVENANCE.json")
    for vendor_path in provenance:
        if vendor_path.startswith("unsorted/"):
            continue
        assert any(e["vendor_path"] == vendor_path for e in catalog), (
            f"{vendor_path} is vendored but absent from catalog.json"
        )
