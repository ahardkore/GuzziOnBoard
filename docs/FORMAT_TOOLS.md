# Format tools: logs, databases, transcripts and tunes

Four tools that bring other people's files into the workstation. They live in
the **General** brand group because none of them is manufacturer-specific — the
*files* they read often are. Like the rest of the tool bench they run entirely
in the browser, in the installed app and in the hosted demo alike.

| Tool | Panel | Reads |
| --- | --- | --- |
| MLVLG log importer | `#mlgLogPanel` | `.mlg` binary logs from TunerStudio, MegaLogViewer, Speeduino |
| CAN database & frame decoder | `#dbcPanel` | Vector `.dbc` plus a candump capture |
| OBD-II / EOBD explorer | `#obdExplorerPanel` | ELM327 transcripts, candump of `0x7E8`, typed codes |
| Tune-file diff | `#tuneDiffPanel` | `.msq`, TunerStudio-style `.ini`, logger CSV |

## MLVLG log importer (`web/mlg-import.js`)

`.mlg` is the binary log TunerStudio and MegaLogViewer write; it carries its own
channel definitions, so a reader needs no log-format file beside it.

Layout, as implemented:

- 6-byte magic `MLVLG`, `int16` version (1 or 2), `int32` start timestamp,
  `int16`/`int32` info-data start, `int32` data start, `int16` record length and
  `int16` channel count;
- one 55-byte (v1) or 89-byte (v2) record per channel: type, 34-byte name,
  10-byte units, display style, then either `float32` scale, `float32`
  transform, digits and (v2) a 34-byte category, or a bit-field style, name
  index, bit count, 3 unused bytes and category;
- an optional bit-field name table, a quoted info line, then the data blocks —
  `type (0 = data, 1 = marker)`, counter, `uint16` stamp, the channel values in
  their declared types, and a checksum byte.

The importer applies each channel's own `raw × scale + transform`, reports the
minimum and maximum actually present, shows the first records and exports CSV.
A file without the `MLVLG` magic, or with a version other than 1 or 2, is
refused by name.

**What it does not do:** the stamp is a 16-bit counter that wraps and the format
does not record its unit, so no seconds are invented; the per-record checksum
byte is skipped because reading a log is not verifying the device that wrote it.

Implementation is independent, written from the format as documented in
[karniv00l/mlg-converter](https://github.com/karniv00l/mlg-converter)
`src/parser.ts`, revision `3c4253bec864` (MIT, Copyright (c) 2020 Piotr
Rogowski). The upstream notice is in `LICENSES/Mlg-Converter-MIT.txt`.

## CAN database (DBC) importer (`web/dbc-lab.js`)

Parses the parts of the Vector DBC format a capture review needs:

- `BO_` messages — identifier, name, DLC, sender;
- `SG_` signals — start bit, length, `@1` Intel / `@0` Motorola, `+`/`-`, factor,
  offset, min/max, unit, receivers, `M`/`m<n>` multiplexer flag;
- `VAL_` value tables, `CM_` comments, `SIG_VALTYPE_` floats and
  `BA_ "GenSigStartValue"`, `BA_ "GenMsgCycleTime"`.

Decoding follows DBC bit numbering, where bit 0 is the least significant bit of
byte 0. An Intel signal starts at its least significant bit and grows with the
bit position; a Motorola signal starts at its most significant bit and walks
down within a byte, jumping from bit 0 to bit 7 of the next byte. Signed values
are two's complement; floats are read from the byte at `start >> 3`.

The decoder consumes candump lines through `frame-lab.js`, so `can0 253#…` and
`can0 18FEF100 [8] …` both work. Identifiers that are not in the database are
counted and listed rather than silently ignored, and multiplexed signals are
skipped rather than guessed — both are decisions the operator should see.

Format semantics follow the
[canmatrix](https://github.com/ebroecker/canmatrix) documentation (BSD-2-Clause,
revision `8b54a41dd44b`); no code was copied, and no DBC file is bundled — the
database is yours.

## OBD-II / EOBD explorer (`web/obd-explorer.js`)

Accepts the three shapes an OBD-II answer arrives in:

- an ELM327 transcript, with or without `>` prompts, `0:` frame numbers or a
  `7E8` header;
- a candump capture, where ISO-TP single frames and multi-frame answers are
  split apart per identifier — one identifier can carry many independent
  answers, so frames are walked in order rather than reassembled as a group;
- bare codes such as `P0133`.

Decoded: Mode 01 live PIDs (load, coolant, MAP, RPM, speed, timing advance, IAT,
MAF, throttle, O2, run time, fuel level, baro, module voltage, ambient, oil
temperature, fuel rate), Mode 03/07 stored and pending DTCs, Mode 09 VIN,
calibration ID and ECU name. A negative response (`7F`) is reported as a
refusal, and an announced-but-missing code count is called out.

Scalings are the SAE J1979 formulae. They are public standard arithmetic, so
they apply to any compliant motorcycle; the profile only decides what to read
first.

**Royal Enfield 650 profile.** One owner's [Royal Enfield OBD-II
dashboard](https://github.com/moca-owner-dev/RoyalEnfieldObd), `backend/obd.py`
revision `2317442d813f` (MIT, Copyright (c) 2026 David Moca — notice in
`LICENSES/RoyalEnfieldObd-MIT.txt`), polls `0x0C` RPM, `0x0D` speed, `0x11`
throttle, `0x0B` MAP, `0x0F` intake air, `0x5C` engine oil temperature and
`0x04` load, and estimates a gear from RPM and road speed. That becomes a
reading list with a gear calculator that needs the real ratios, primary and
final drive before it will answer — with none supplied it declines rather than
guessing.

## Tune-file diff (`web/tune-diff.js`)

Recognises files by content, not extension:

- **`.msq`** (TunerStudio, MegaSquirt, Speeduino): `<constant name value>` pairs
  and `<table>` bodies with `<x>`, `<y>`, `<z>` rows. Tables are compared cell by
  cell, with the row and column of the first changes, whether an axis moved and
  whether the shape changed.
- **`.ini`**: `[Section]` headers and `key = value` pairs; keys are compared as
  `Section.key`.
- **CSV**: columns matched by header, each with a changed-cell count, largest
  and mean delta and sample rows, plus columns that only exist on one side.

Constants compare numerically within 1e-9 and as text otherwise. The summary
counts changes, additions and removals, and the panel says plainly that a
difference is a question, not an instruction: identical numbers can mean
different things under a different firmware's addressing.

## Tests

- `tests/browser/toolkit-formats.spec.mjs` — eleven cases: bench counts, an
  MLVLG fixture written byte by byte, DBC parsing and Intel/Motorola/signed/
  float decoding, unknown identifiers, OBD transcripts, candump ISO-TP framing,
  the Royal Enfield profile and gear maths, MSQ and CSV diffs, and a refused
  mismatch between formats.
- `tests/test_help_module.py` — every bench panel, including these four, has a
  help entry.
- `tests/test_demo_mode.py` — the demo's simulated endpoints stay labelled, and
  the XDF library index still matches a fresh parse.

The pure functions are exposed for those tests as `window.gobMlg`,
`window.gobDbc`, `window.gobObd` and `window.gobTuneDiff`.
