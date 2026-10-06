#!/usr/bin/env python3
"""Vendor TunerPro XDF files from the GuzziDiag archive into this repo.

The archive at <https://www.von-der-salierburg.de/download/GuzziDiag/>
(TunerPro XDF section) has no bulk download and no API, so filling in
``guzzionboard/xdfs/`` is a manual "download the zips you want" step. This
script turns the rest of that chore — unzip, parse-check, place in the right
brand folder, record provenance — into one command.

Usage
-----
    # see what's already vendored vs. what catalog.json still lists
    python3 scripts/import_xdfs.py --status

    # import every zip/xdf found in a folder of downloads
    python3 scripts/import_xdfs.py --source ~/Downloads/guzzidiag-xdfs

Only files that parse as a real TunerPro XDF via this project's own
``guzzionboard.maps.XdfFile`` are vendored — anything else is reported and
skipped, never guessed at or fabricated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
XDF_ROOT = REPO_ROOT / "guzzionboard" / "xdfs"
CATALOG_PATH = XDF_ROOT / "catalog.json"
PROVENANCE_PATH = XDF_ROOT / "PROVENANCE.json"

sys.path.insert(0, str(REPO_ROOT))
from guzzionboard.maps import XdfError, XdfFile  # noqa: E402


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def catalog_by_zip(catalog: list[dict]) -> dict[str, dict]:
    return {entry["zip_filename"].lower(): entry for entry in catalog}


def iter_candidate_xdfs(source: Path):
    """Yield (origin_zip_name, xdf_filename, xdf_bytes) for every .xdf we can
    find under ``source`` — inside zips, or loose on disk."""
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    members = [
                        m for m in zf.namelist()
                        if m.lower().endswith(".xdf")
                        and "__macosx" not in m.lower()
                    ]
                    if not members:
                        print(f"  skip {path.name}: no .xdf inside the zip")
                        continue
                    for member in members:
                        yield path.name, Path(member).name, zf.read(member)
            except zipfile.BadZipFile:
                print(f"  skip {path.name}: not a valid zip")
        elif suffix == ".xdf":
            yield path.name, path.name, path.read_bytes()


def status(catalog: list[dict]) -> int:
    missing = []
    present = []
    for entry in catalog:
        dest = XDF_ROOT / entry["vendor_path"]
        (present if dest.exists() else missing).append(entry)
    print(f"{len(present)}/{len(catalog)} cataloged files vendored")
    if missing:
        print("\nMissing:")
        for e in missing:
            print(f"  [{e['brand']}/{e['family']}] {e['label']}"
                  f"  ->  {e['source_url']}")
    return 0


def import_from(source: Path, catalog: list[dict]) -> int:
    by_zip = catalog_by_zip(catalog)
    provenance = load_json(PROVENANCE_PATH, {})

    imported = skipped = unmatched = 0
    for origin_zip, xdf_filename, data in iter_candidate_xdfs(source):
        try:
            text = data.decode("ISO-8859-1")
            xdf = XdfFile.from_string(text)
        except (XdfError, UnicodeDecodeError) as exc:
            print(f"  REJECT {xdf_filename} (from {origin_zip}): {exc}")
            skipped += 1
            continue

        entry = by_zip.get(origin_zip.lower())
        if entry is not None:
            vendor_path = entry["vendor_path"]
            source_url = entry["source_url"]
        else:
            vendor_path = f"unsorted/{xdf_filename}"
            source_url = None
            print(f"  WARNING: {origin_zip!r} is not in catalog.json — "
                  f"vendoring to {vendor_path}; please add it to the "
                  f"catalog in your pull request")
            unmatched += 1

        dest = XDF_ROOT / vendor_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        provenance[vendor_path] = {
            "source_url": source_url,
            "origin_zip": origin_zip,
            "sha256": hashlib.sha256(data).hexdigest(),
            "title": xdf.title,
            "author": xdf.author,
            "version": xdf.version,
            "imported_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verified_parse": True,
        }
        print(f"  OK {vendor_path}  ({xdf.title!r} v{xdf.version}, "
              f"{len(xdf.tables)} tables, {len(xdf.constants)} constants)")
        imported += 1

    save_json(PROVENANCE_PATH, provenance)
    print(f"\nImported {imported}, rejected {skipped}, "
          f"unmatched-but-vendored {unmatched}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        help="folder of downloaded .zip/.xdf files from the GuzziDiag archive",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="report which cataloged files are vendored vs. still missing",
    )
    args = parser.parse_args()

    catalog = load_json(CATALOG_PATH, [])

    if args.status or not args.source:
        return status(catalog)
    if not args.source.is_dir():
        parser.error(f"{args.source} is not a directory")
    return import_from(args.source, catalog)


if __name__ == "__main__":
    raise SystemExit(main())
