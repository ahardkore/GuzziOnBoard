# The offline toolkit: five tools that need no motorcycle

`Tools` carries five general utilities that work entirely on data the operator
supplies — a binary image, a log, a pasted capture or a search term. They need
no adapter, no engine and no ECU, so they behave the same in the installed app
and in the hosted demo, and nothing in them can change a motorcycle.

They sit in the **General** brand group because none of them is
manufacturer-specific; the definitions and captures they read can be.

The four tools that read *other formats* — MLVLG logs, DBC databases, OBD-II
transcripts and tune files — are documented in [format tools](FORMAT_TOOLS.md).


| Tool | Panel id | Works on |
| --- | --- | --- |
| Checksum workbench & algorithm finder | `#checksumWorkbench` | a `.bin` image |
| ROM region & entropy map | `#romMapPanel` | one or two images |
| XDF library table finder | `#xdfFinderPanel` | the bundled definitions |
| Wideband transfer-function lab | `#widebandLab` | a pasted voltage column or CSV |
| J1939 & ISO-TP frame lab | `#frameLabPanel` | pasted candump lines or hex |

## Checksum workbench (`web/checksum-workbench.js`)

The question behind most "the ECU rejects my edited file" reports is arithmetic.
The workbench computes nine checksums over the bytes *before* a candidate stored
word and reports every one that agrees with the word already in the file:

- byte sum (8- and 16-bit), byte XOR,
- 16-bit word sums (big- and little-endian words), 32-bit word sum,
- CRC-16/CCITT-FALSE, CRC-16/XMODEM, CRC-32 (zlib/IEEE).

Candidate positions are the tail of the image (`len-1`, `len-2`, `len-4`,
`len-8`, `len-16`, `len-32` …), a header window (`0x00`–`0x100`) and whatever
offset the operator types. Each position is tried in both byte orders, and a
stored one's complement counts as a match but is labelled separately.

Ranking prefers wider words and more specific algorithms, and boosts an
algorithm that matches at exactly one position — a 16-bit sum will often match
somewhere by chance, a CRC-32 will not.

**Repair** recomputes the chosen algorithm from the data start, writes the word
into a *copy*, and shows the SHA-256 of both files. The original on disk is
never opened for writing, and the panel says plainly that a matching checksum is
not flash approval: the backup, base-map and confirmation gates still apply.

The family list (Bosch MSE6.0/MSE8.0/MG1, Honda Keihin, Dell'Orto, Yamaha MT,
Italjet/Suzuki and QH250) exists to send the operator to the dedicated tool that
implements the full record walk, not to imply this generic sweep reproduces it.

Source: the algorithm set and family notes follow
[NetworkDir/moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum)
(`algorithms/*.js`, revision `43ccc5f`), whose README declares MIT while the
repository carries no licence file. Only the arithmetic is shared knowledge; no
code was copied. The arithmetic conventions match `guzzionboard/checksums.py`
and `guzzionboard/maps.py`.

## ROM region & entropy map (`web/rom-map.js`)

A sliding-window Shannon entropy profile of an unknown image, rendered as an SVG
strip and merged into regions:

- **padding / blank** — one byte fills ≥ 98 % of the window,
- **code or compressed** — entropy ≥ 7.2 bits/byte,
- **table-like data** — entropy between 3.5 and 7.2,
- **sparse** — below 3.5.

Windows default to 256 bytes; the profile is capped at 4,096 windows by growing
the stride on large images, so a 16 MiB dump still renders quickly. Load a
second image and the panel lists every changed run with offsets and lengths.

The strip says what *kind* of data a region holds, never which table it is: that
claim still belongs to an XDF. It is the natural first step before authoring or
loading a definition.

## XDF library table finder (`web/xdf-finder.js`)

The XDF & ROM view describes one definition at a time because a table needs an
image to show values. Finding the definition needs none of that, so
`guzzionboard/maps.py::library_index()` publishes a table-level index of all 121
bundled definitions — 4,280 tables with title, category, units, address, shape,
cell type and the XDF's own math string, and no cell values.

- Desktop: `GET /api/maps/library` parses the library live, so a definition
  dropped into `~/.guzzionboard/xdfs/` appears without regenerating anything.
- Hosted demo: the same payload is generated into `web/xdf-library.json` by
  `scripts/build_demo_data.py`, and `demo-lab.js` answers the same route from it.
  `tests/test_demo_mode.py` regenerates and compares the file, so the demo
  cannot search a different library from the one the desktop build reads.

Search matches table name, units, category, equation, definition label or
address, optionally narrowed by brand; the address field accepts `0xB024`,
`B024` or a decimal offset. **Copy** puts `filename · table @ address` on the
clipboard and opens the ECU memory view, where the definition can be selected
and an image dropped.

## Wideband transfer-function lab (`web/wideband-lab.js`)

Converts a logged voltage to AFR and lambda using the controller's published
analog-output default:

| Preset | Curve | Valid range |
| --- | --- | --- |
| Innovate LC-2 / MTX-L | 0 V = 7.35 AFR, 5 V = 22.39 AFR (LC-2 manual 11-0137C) | 0–5 V |
| Zeitronix ZT-2 | AFR = 2 × V + 9.6 (ZT-2 instructions) | 0–5 V |
| AEM X-series 30-0300 | AFR = 2.3750 × V + 7.3125 (30-0300 manual) | 0.5–4.5 V |
| Custom | two operator-supplied points | 0–5 V |

Lambda is computed against the selected fuel's stoichiometric ratio (petrol
14.7, E10 14.1, E85 9.8, methanol 6.5, diesel 14.5). An AEM reading below 0.5 V
is reported as **sensor not ready** and above 4.5 V as **sensor error** rather
than being converted into a confident-looking number.

The two-point check answers the other common question — "is this log
calibrated?" — by showing the scale factor, the percentage error and the AFR
offset at λ 1 that a measured-versus-reference correction would apply.

This complements, and does not replace, the ZT-2 → LogWorks converter
(`#z2ConverterPanel`), which reformats the CSV rather than converting volts.

## J1939 & ISO-TP frame lab (`web/frame-lab.js`)

Three pieces of arithmetic that every capture eventually needs:

- **J1939 identifier decode** — priority, EDP/DP, PF, PS, source address, PGN,
  PDU1 (destination in PS) versus PDU2 (broadcast), plus a small PGN name table
  (EEC1, EEC2, ET1, CCVS, LFE, DD, the transport-protocol PGNs and address
  claim). Unknown PGNs say so instead of guessing a name.
- **ISO-TP segmentation and reassembly** — classic CAN 8-byte data field,
  single/first/consecutive frames, configurable padding byte, and reassembly
  that refuses a sequence gap with the offset it expected.
- **KWP2000 framing** — the same format byte, addressing rule, long form and
  low-byte sum as `guzzionboard/protocol/kwp2000.py`, with a round-trip decode
  showing that the checksum validates.

`describeFrames()` also accepts a whole `candump` log in either common form
(`can0 18FEF100 [8] 01 02 …` or `can0 18FEF100#0102…`) and prints a per-identifier
census with sample bytes.

## Testing

- `tests/browser/toolkit-batch.spec.mjs` — eight cases covering the bench
  counts, the J1939/ISO-TP/KWP arithmetic, the wideband curves, ROM regions and
  diff, checksum repair, and the library finder's search and brand filter.
- `tests/test_maps.py` — `library_index()` and `library_payload()` invariants.
- `tests/test_http_validation.py` — `GET /api/maps/library` over the real
  handler.
- `tests/test_demo_mode.py` — `web/xdf-library.json` matches a fresh parse.
- `tests/test_help_module.py` — every bench panel has a help entry, and the
  brand join between `web/app.js` and `web/help-content.js` still holds.

The pure functions are exposed for those tests as `window.gobFrameLab`,
`window.gobWidebandLab`, `window.gobRomMap`, `window.gobChecksumWorkbench` and
`window.gobXdfFinder`.
