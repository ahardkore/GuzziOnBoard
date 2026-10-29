# The bundled XDF library

`guzzionboard/xdfs/` contains TunerPro XDF definitions from multiple sources.
The GuzziDiag collection is published at <https://www.von-der-salierburg.de/download/GuzziDiag/> (the
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

- The GuzziDiag archive files are **third-party, community-authored files** — not written by this
  project. Primary authorship (where recorded in the XDF itself) is
  `beard` and the wider GuzziDiag/IAWDiag/wildguzzi.com community; see each
  file's own `<author>` field.
- The GuzziDiag origin site carries no explicit redistribution license; it publishes
  the files for free, non-commercial use with a blanket "use at your own
  risk, no liability" notice. We mirror that posture here: none of
  those GuzziDiag files are covered by the application's software license, no
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

**All 95 cataloged definitions** are vendored — 3880 tables and 2148
constants in total, every one parse-checked by `guzzionboard.maps.XdfFile`:

| Brand | Files | | Brand | Files |
|---|---|---|---|---|
| Ducati | 29 | | Morini | 4 |
| Moto Guzzi | 24 | | GasGas | 3 |
| Aprilia | 18 | | Gilera | 2 |
| Piaggio | 10 | | BMW / Honda / Husqvarna / Malaguti / Scomadi | 1 each |

Run `python3 scripts/import_xdfs.py --status` at any time to re-confirm the
count; if the catalog ever gains an entry that is not vendored yet, it
prints the missing file and its upstream URL.

The original GuzziDiag zips these were extracted from are mirrored, unmodified, in
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
  moto_guzzi/ aprilia/ ducati/ bmw/ gasgas/ gilera/ honda/ husqvarna/
  malaguti/ morini/ piaggio/ scomadi/
                       the actual .xdf files, one brand folder each,
                       named exactly as the origin site's zip (minus .zip)
```

`guzzionboard/maps.load_bundled_xdfs()` reads every `.xdf` under this tree
recursively; `guzzionboard/maps.available_xdfs()` is what the app actually
uses — it merges the bundled set with anything a user has dropped into
`~/.guzzionboard/xdfs/`, and a user file wins over a bundled file of the
same **filename** (so you can override or update one without touching the
repo).

## Choosing the right one: fitment

XDF titles are whatever their author typed. Several unrelated files call
themselves `15M Marelli`, and some have no title at all, so titles are no
basis for choosing — or for identifying — a definition. `catalog.json` is:
it records the brand, the ECU family and every motorcycle the origin site
publishes each file for.

`maps.fitment(path)` returns those facts for a file (`filename`, `family`,
`label`, `fits`, `brand_label`), `describe()` includes them, and
`maps.group_xdfs()` arranges the library the way the chooser shows it: one
group per brand, one sub-group per ECU family. `/api/maps` returns the
grouping plus the ECU currently selected, so the UI can put the definitions
that match the bike on the bench in their own group and mark everything else
as *not this ECU* — a definition from another family is not "slightly wrong",
it reads a different calibration layout at the same addresses.

Definitions are selected **by filename**. An ambiguous title is refused
rather than resolved by luck.

## Linked legends: where axis labels actually come from

A table in these files usually stores its breakpoints in the dump, on the
axis itself (`EMBEDDEDDATA` with an address), and those are what the editor
shows and writes. But many axes have no data of their own; they carry an
`<embedinfo type="3" linkobjid="0x7FDD" />` instead, which means *"my labels
are that other item's values"*. The target is always a **legend** table — a
name like `4C E 68 Legend EngineTemp` whose own `z` data is the list of
breakpoints — so this is the difference between a row header that reads
`13` and one that reads `82` (°C):

```
<XDFTABLE uniqueid="0x7FDD">            <!-- the legend, data at 0x4CE68 -->
  <title>4C E 68 Legend EngineTemp</title>
  <XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x4CE68" mmedelementsizebits="16" … />
    <MATH equation="X-40">…</MATH></XDFAXIS>
</XDFTABLE>

<XDFTABLE uniqueid="0x2F84">            <!-- the user of that legend -->
  <title>49 4 A0 Ignition Engine Temp correction Idle_1</title>
  <XDFAXIS id="y"><units>&#176;C</units><indexcount>16</indexcount>
    <embedinfo type="3" linkobjid="0x7FDD" />   <!-- labels from the legend -->
  </XDFAXIS>
```

`XdfFile.render()` reads the linked legend through **the legend's own**
address, element size and `MATH` equation — that is what makes the labels
engineering values rather than indexes — and reports the provenance on the
axis as `axes.y.legend` (`id`, `title`, `count`, `applied`, `reason`).
Rules it follows, because these are third-party files:

- An axis that **does** have its own address keeps its own values. Those are
  the bytes the map reads and edits; the link is not consulted.
- A legend **longer** than the axis labels the entries the axis has (the
  common case: a 20-value TPS legend on a 10-row table).
- A legend **shorter** than the axis labels only the entries it defines; the
  rest keep their plain indexes and `legend.reason` says so. Nothing is
  padded or read past the end of the legend's declared data — an RSV4
  definition that links a nine-value legend to 24-row tables is reported that
  way rather than given fifteen invented °C values.
- A dangling `linkobjid` is not a parse error: the axis keeps its own labels
  and the unresolved link is reported when the axis is rendered.

In the workstation editor the column/row headers keep a tooltip naming the
legend they came from, and a legend that could not label the whole axis puts
a line above the table saying so.

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

## Data-layout correction and research preview

Explicit item `mmedtypeflags` now control signedness, little/big endian and
column-major ordering; an absent attribute inherits the XDF header defaults.
The previous parser could interpret explicit flags incorrectly, including in
BMW, Husqvarna, Ducati and Aprilia definitions. **Do not rely on values,
exports or builds produced with the earlier parser**: return to the original
backup, rerender, re-create edits and check the byte diff and checksum. Map
project schema 3 records the layout revision; older schema 1 and 2 projects
must be recreated and reviewed rather than silently reinterpreted. This change
does not verify definition fitment or calibration correctness. See
`docs/PRIOR_ART.md` for references and unsupported encodings.

The desktop/local app can render a user-provided XDF placed in the user XDF
directory and preview staged edits even when that XDF/ECU family is not in the
catalog. The hosted demonstration uses synthetic images and bundled definitions
only. **Preview edits for research** checks the source and XDF SHA-256 and raw
cell locks, quantizes values in memory and shows the resulting diff; it writes
no image, does not repair any checksum, and does not validate ECU, software,
vehicle fitment or a tuning recommendation. The regular build and programming
gates are unchanged. A research preview is not a build authorization.

## Honda CBR1000RR 2012 US: offline image build

`honda/CBR1000RR_2012_US.xdf` is unmodified from [Ryan Hope and HondaECU
contributors' repository](https://github.com/roccofz1/HondaECU/tree/dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109)
(commit `dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109`); XDF SHA-256
`c942ffc16e498985dba5592388e7cf6f2d23e2adde94fde825b52d1287141415`.
The upstream repository has a GPL-3.0 license, reproduced in
`LICENSES/HondaECU-GPL-3.0.txt`. The checksum provider adapts its
`checksum8bitHonda`/`validate_checksum` logic: additive inverse of every byte
except the checksum byte, stored at `0x3FFF8` over a 256 KiB image.

Upstream names the XDF **CBR1000RR 2012 US** and groups the example image
`38770-MGP-A01.bin` under **2012–2013 CBR1000RR**. We associate that image
and definition on this shared model/year context; upstream does not explicitly
pair the two files. Offline, the source example renders 38 supported tables
and its full-image byte sum is zero. `Top Speed Limit` has an unsupported
`X >> 4` equation and is not editable. One synthetic edit to the upstream
example changed the selected data byte and checksum byte as expected; this
is not a hardware test or validation of every definition or tune.

To use the new workstation/desktop path: select **Honda → CBR1000RR (US) →
2012**, click **Select for offline maps**, render your own full original 256 KiB image with this XDF, select
**Honda CBR1000RR 2012 US / A01 checksum**, stage edits and follow the normal
preview/evidence/acknowledgement/build workflow. The original must have SHA-256
`c0fb37e60fbf38a8479166a5ef9ca0fdcc8b4f7c37de97f9dadaab1db0da0764`
and the definition must have the pinned hash above; other calibrations and
previously modified images can still be examined with research preview, not
built by this profile. No OEM firmware is shipped here. The checksum provider
requires an explicit selection, verifies its output and only changes one byte.
The source image/XDF association and an image hash do not establish physical
ECU identity; independently confirm your hardware and configuration. No Honda
read, write, flashing, live session, or hardware-test claim is enabled. The
static hosted demo can render/research-preview definitions but cannot execute
the workstation checksum provider or create an ECU-ready output.
