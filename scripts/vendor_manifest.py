#!/usr/bin/env python3
"""Regenerate ``vendor/guzzidiag/MANIFEST.json``.

``vendor/guzzidiag/`` is the mirror of the download archive published at
<https://www.von-der-salierburg.de/download/GuzziDiag/> exactly as it is
distributed: the original zips, untouched. This script records what is in
that mirror — size, SHA-256, the files inside each zip and the upstream URL
it came from — so a reader can verify any mirrored byte against the origin
site without unzipping anything.

Usage::

    python3 scripts/vendor_manifest.py          # write the manifest
    python3 scripts/vendor_manifest.py --check  # fail if it is out of date
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = REPO_ROOT / "vendor" / "guzzidiag"
MANIFEST_PATH = VENDOR_ROOT / "MANIFEST.json"
BASE_URL = "https://www.von-der-salierburg.de/download/GuzziDiag"

# The origin site serves the TunerPro definitions out of /xdf/ and the
# Windows tools out of the archive root.
SECTION_URL = {"xdf": f"{BASE_URL}/xdf", "tools": BASE_URL}


def describe(path: Path, section: str) -> dict:
    data = path.read_bytes()
    entry = {
        "filename": path.name,
        "section": section,
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_url": f"{SECTION_URL[section]}/{path.name}",
    }
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            entry["contents"] = [
                {"name": i.filename, "bytes": i.file_size,
                 "modified": "%04d-%02d-%02dT%02d:%02d:%02d" % i.date_time}
                for i in zf.infolist()
                if not i.is_dir() and "__MACOSX" not in i.filename
            ]
    return entry


def build() -> dict:
    files = []
    for section in ("xdf", "tools"):
        folder = VENDOR_ROOT / section
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file():
                files.append(describe(path, section))
    return {
        "origin": f"{BASE_URL}/",
        "note": (
            "Byte-for-byte mirror of the GuzziDiag archive as published. "
            "Nothing here is authored by this project; see "
            "docs/XDF_LIBRARY.md for provenance and licensing."
        ),
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the manifest is out of date")
    args = parser.parse_args()

    manifest = build()
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = MANIFEST_PATH.read_text(encoding="utf-8") \
            if MANIFEST_PATH.exists() else ""
        if current != text:
            print("MANIFEST.json is out of date; run "
                  "python3 scripts/vendor_manifest.py")
            return 1
        print(f"MANIFEST.json up to date ({manifest['file_count']} files)")
        return 0

    MANIFEST_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}: "
          f"{manifest['file_count']} files, "
          f"{manifest['total_bytes'] / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
