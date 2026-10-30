#!/usr/bin/env python3
"""Generate the read-only Worker manifest from exactly the app's catalog.

No guessed geometry or research-only path is admitted. Run with --check in CI.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from guzzionboard.catalog import load_catalog, source_fingerprint


def render():
    result = {}
    for profile in load_catalog(overlays=False).ecus.values():
        memory = profile.memory or {}
        if not memory.get('read_supported') or memory.get('research_read_only'):
            continue
        regions = {name: region['size'] for name, region in (memory.get('regions') or {}).items()
                   if type(region.get('size')) is int and region['size'] > 0}
        if regions:
            result[profile.id] = {'fingerprint': source_fingerprint(profile.id), 'regions': regions}
    return json.dumps(result, indent=2, sort_keys=True) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'cloudflare' / 'catalog.json'
    contents = render()
    if args.check:
        if not path.exists() or path.read_text() != contents:
            raise SystemExit('Cloudflare catalog is stale; run scripts/build_cloudflare_catalog.py')
        print('Cloudflare catalog is up to date')
    else:
        path.write_text(contents)
        print(f'Wrote {path.relative_to(ROOT)}')

if __name__ == '__main__':
    main()
