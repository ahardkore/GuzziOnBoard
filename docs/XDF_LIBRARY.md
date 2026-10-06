# The bundled XDF library

`guzzionboard/xdfs/` is a vendored copy of the TunerPro XDF definitions
published at <https://www.von-der-salierburg.de/download/GuzziDiag/> (the
GuzziDiag/IAWDiag archive — the same community reference the rest of this
project's protocol work is grounded in, see `docs/PRIOR_ART.md`).

## Why these files are vendored instead of fetched on demand

The archive is a small, non-commercial fan site with no API and no bulk
download, so getting every family's XDF into the hands of a new user used to
mean: find the right row for your exact ECU/bike on that page, download a
zip, unzip it, and copy the `.xdf` into `~/.guzzionboard/xdfs/`. That is the
*only* step most users needed GuzziDiag's own tools for — the actual
map-reading parser is this project's `guzzionboard/maps.py`. Shipping the
definitions removes that step entirely: pick a family in **Firmware → Maps &
tables** and the real, named tables are already there.

## Provenance and licensing

- These are **third-party, community-authored files** — not written by this
  project. Primary authorship (where recorded in the XDF itself) is
  `beard` and the wider GuzziDiag/IAWDiag/wildguzzi.com community; see each
  file's own `<author>` field.
- The origin site carries no explicit redistribution license; it publishes
  the files for free, non-commercial use with a blanket "use at your own
  risk, no liability" notice. We mirror that posture here: nothing in
  `guzzionboard/xdfs/` is covered by this repository's MIT license, no
  warranty is made about accuracy, and the files are kept only for
  diagnostic/tuning reference exactly as GuzziDiag users have used them for
  years.
- `guzzionboard/xdfs/PROVENANCE.json` records, per vendored file, the exact
  upstream URL it came from, a SHA-256 of the vendored bytes, and how/when it
  was retrieved. If you are the author of one of these files and want it
  removed, credited differently, or replaced with a newer version, please
  open an issue — this project has no interest in misattributing anyone's
  reverse-engineering work.
- If a file is ever found to be inaccurate, the fix is to replace it with a
  newer version from the origin site (via `scripts/import_xdfs.py`, below),
  not to hand-edit the vendored copy silently.

## What is bundled today

**72 of the 94 cataloged definitions** are vendored — 2616 tables and 1531
constants in total, every one parse-checked by `guzzionboard.maps.XdfFile`:

| Brand | Files | | Brand | Files |
|---|---|---|---|---|
| Ducati | 28 | | Morini | 4 |
| Moto Guzzi | 17 | | GasGas | 3 |
| Piaggio | 10 | | Gilera | 2 |
| Aprilia | 4 | | BMW / Husqvarna / Malaguti / Scomadi | 1 each |

The 22 still missing are the 7SM and MIU G3 Aprilia/Moto Guzzi definitions
(RSV4 variants, Caponord, Dorsoduro, RS4 125, SX125, V9, V7 III, California
1400, MGX21, V85TT) plus `5AM_Aprilia_GP850`, `5AM_Aprilia_Mana` and
`59M_Monster S4_28640191B`. Run `python3 scripts/import_xdfs.py --status`
for the exact list and upstream URLs.

The original zips these were extracted from are mirrored, unmodified, in
`vendor/guzzidiag/xdf/`, with sizes, SHA-256s and upstream URLs recorded in
`vendor/guzzidiag/MANIFEST.json` (see `vendor/guzzidiag/README.md`). That
mirror is the provenance record; `guzzionboard/xdfs/` is what the app loads.

## Layout

```
guzzionboard/xdfs/
  catalog.json        every file known to exist on the origin site: brand,
                       ECU family, model label, upstream URL and the path
                       it lands at once vendored
  PROVENANCE.json      per-vendored-file source URL, hash and import date
  moto_guzzi/ aprilia/ ducati/ bmw/ gasgas/ gilera/ husqvarna/
  malaguti/ morini/ piaggio/ scomadi/
                       the actual .xdf files, one brand folder each,
                       named exactly as the origin site's zip (minus .zip)
```

`guzzionboard/maps.load_bundled_xdfs()` reads every `.xdf` under this tree
recursively; `guzzionboard/maps.available_xdfs()` is what the app actually
uses — it merges the bundled set with anything a user has dropped into
`~/.guzzionboard/xdfs/`, and a user file wins over a bundled file of the
same title (so you can override or update one without touching the repo).

## Filling in the rest of the catalog

Only the files that have actually been fetched and parse-checked are
committed here (check `catalog.json` against the `*/` folders, or run
`python3 scripts/import_xdfs.py --status`, to see what's missing). To add
more:

1. Download whichever zips you want from
   <https://www.von-der-salierburg.de/download/GuzziDiag/> (TunerPro XDF
   section) into `vendor/guzzidiag/xdf/` — filenames must stay exactly as
   the site names them, the importer matches on that. (Any other folder
   works too, but keeping the mirror complete is preferred.)
2. Run:
   ```bash
   python3 scripts/import_xdfs.py --source vendor/guzzidiag/xdf
   python3 scripts/vendor_manifest.py      # refresh the mirror manifest
   ```
3. The script unzips each one, parses it with the project's own
   `guzzionboard.maps.XdfFile` (so anything that doesn't actually parse as a
   TunerPro XDF is rejected rather than silently vendored), places it at the
   right `guzzionboard/xdfs/<brand>/<name>.xdf`, and records the source URL
   and hash in `PROVENANCE.json`.
4. Review the diff — you're vetting both the parse result and that the file
   really is third-party content you're comfortable committing — and send a
   pull request.

A zip whose filename isn't in `catalog.json` still gets imported (into
`guzzionboard/xdfs/unsorted/`) with a warning, so one-off/new files from the
community aren't silently dropped; update `catalog.json` for it in the same
PR.
