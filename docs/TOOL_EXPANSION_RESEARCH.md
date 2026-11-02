# Tools we could add next: brand-specific and general

Research pass, 2026-11-02. This is a proposal, not a commitment: nothing here is
implemented yet. Every entry says where the protocol or format knowledge comes
from, what the repo's licence is, and whether the tool needs a motorcycle
plugged in. Sources are pinned to the commit that was read.

The rule the existing code already follows applies to all of it: a decoded byte
is a research lead, not vehicle identification, not a verified backup and never
a write authorisation. Tools that touch a user's own file stay offline and
local; tools that describe an ECU say so in the panel.

## Where the bench stands

24 tools in 10 brand groups (11 general, Harley 4, Honda 2, and one each for
Bajaj, Buell, CFMoto, Yamaha, BRT Juken, Dynojet, rusEFI).

Two obvious gaps show up when you count what the repository already ships:

| Asset | Bundled now | Brand group on the bench |
| --- | --- | --- |
| Vehicle catalog | 525 entries — Harley 207, Honda 121, Moto Guzzi 81, Kawasaki 53, Ducati 29, Suzuki 14, Yamaha 10, Aprilia 8, Triumph 2 | Harley, Honda, Yamaha … no Guzzi, Kawasaki, Ducati, Suzuki, Aprilia, Triumph |
| XDF definitions | 121 files in 13 folders — Ducati 29, Moto Guzzi 24, Aprilia 18, Honda 14, Buell 13, Piaggio 10, Morini 4, GASGAS 3, Gilera 2, BMW 1, Husqvarna 1, Malaguti 1, Scomadi 1 | none of them can be searched or filtered by brand |
| Protocol modules | KWP2000, ISO-TP, legacy IAW, HD J1850, HD Delphi CAN, Honda PGM-FI, Honda CBR600RR, Kawasaki ER-6n, Kawasaki Ninja 7, Triumph Daytona, OBD-CAN, Aster K-Line, plus Ducati Panigale CAN, Indian J1939, Yamaha R9/MTO3, Buell DDFI, rusEFI | Kawasaki, Triumph, Ducati, Indian and Suzuki exist only as dropdowns inside the diagnostics view |

So roughly half of the proposals below are **not new reverse engineering**: they
surface capability that is already tested in `guzzionboard/protocol/` but is
buried three clicks deep. The rest are new offline tools built from published
formats and source-described register maps.

Effort is S (one panel, <300 lines), M (a parser or a decode table, 300–800),
L (a format implementation plus fixtures). "Offline" means the hosted demo can
run it with no adapter and no bike.

## The short list

| # | Tool | Group | What it gives the user | Offline | Effort | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Checksum workbench & algorithm finder | general | Paste a modified image, learn which of eight known algorithms and which offset it fails on, repair a copy | yes | M | `NetworkDir/moto-ecu-checksum` @ `43ccc5f`, plus our `checksums.py` |
| 2 | ROM region & entropy map | general | Heat-map an unknown dump to find tables, repeated rows and the calibration region before editing | yes | S–M | binwalk-style technique, no code needed |
| 3 | XDF library table finder | general | Search all 121 bundled definitions by table name, units, address or size; filter by brand | yes | S | our `maps.py` + `xdfs/` |
| 4 | OBD-II / EOBD explorer | general | Decode Mode 01/03/09 from a pasted ELM327 or candump log; per-bike PID profiles | yes | M | `moca-owner-dev/RoyalEnfieldObd` @ `2317442` (MIT), our `obd_can.py` |
| 5 | CAN database (DBC) importer & frame decoder | general | Load a DBC, list messages/signals, decode a capture to engineering units, export CSV | yes | L | `ebroecker/canmatrix` @ `8b54a41` (BSD-2) for format semantics |
| 6 | `.mlg` binary log importer | general | Open TunerStudio / MegaLogViewer / Speeduino logs and feed the AFR and VE analysis | yes | M | `karniv00l/mlg-converter` @ `3c4253b` (MIT), MLVLG format |
| 7 | Suzuki SDS tool | suzuki | Read-only SDS conversation plus an offline decoder for a pasted response | no (decode: yes) | M | `KDS2Bluetooth` @ `bb8be32` (GPL-3) offsets, `BananaJoh/sv650overlay` |
| 8 | Kawasaki KDS tool | kawasaki | KDS register inspector, live values, DTC decode, offline response decoder | partial | M | `gabrielerandazzo/iKawa` @ `79eb904` (MIT, already vendored) |
| 9 | Ducati Panigale / Mitsubishi tool | ducati | Make the existing CAN decoder a first-class tool; 29 bundled XDFs get a brand home | yes (decode) | S | `ducati_panigale_can.py`, `Fatom2k/DucatiCanBus` @ `7f4beff` |
| 10 | Moto Guzzi / Aprilia IAW layout tool | moto-guzzi, aprilia | 5AM/7SM/MIUG3 image layout, region map and checksum check for 42 bundled definitions | yes | L | our `protocol/legacy_iaw.py` + `xdfs/` |
| 11 | Royal Enfield OBD-II | royal-enfield | 650-class PID profile, gear-from-RPM/speed, Hunter 350 keyed-checksum research stub | yes (decode) | S–M | `moca-owner-dev/RoyalEnfieldObd` (MIT), `moto-ecu-checksum` (unsupported case) |
| 12 | BMW Motorrad CAN decoder | bmw | Decode engine temperature, brake lever, wonder-wheel nibbles from a capture | yes | S | `diogocardoso28/BmwMotorradCanbusDecoder` @ `a128889` |
| 13 | KTM / Husqvarna KMSK16 KWP explorer | ktm, husqvarna | Closed KWP job set for a read-only identify/DTC session | no | L | `gobftald/CCM450-diag` @ `43104d2`, `Junix330/AD-KTM-ECU` @ `d61be53` |
| 14 | Zero / Energica EV decoder | zero, energica | Decode pack SoC and charge time from EV broadcast frames | yes | S | `Slevinoo/ZeroMotorcycles_SRS_CANbus` @ `28de213` |
| 15 | Tune-file diff | general | Compare two `.msq` / `.ini`-described tunes or two `.mtl` maps cell by cell | yes | M | `rusefi/rusefi`, `speeduino/speeduino`, our `rusefi_tune.py` |
| 16 | J1939 + ISO-TP frame lab | general | PGN/PF/PS/SA resolver, 15765-2 segmenter, KWP frame checksum | yes | S | our `isotp.py`, `kwp2000.py`, `indian_springfield_can.py` |
| 17 | Wideband transfer-function lab | general | Any wideband log to λ/AFR; free-air recalibration; E10/E85 conversions | yes | S–M | vendor curves, our `logconvert.py` |
| 18 | Injector & fuel-system calculator | general | Size injectors from target power, duty cycle at pressure, dead time, E85 derate | yes | S | general tuning arithmetic |
| 19 | Speedometer / gearing correction | general | Extend `gearingPanel` with sprocket change %, tyre growth, speedo-healer factor | yes | S | our `gearingPanel` |
| 20 | Dyno correction factors | general | SAE J1349 / DIN / STD correction plus air-density from altitude and conditions | yes | S | standard formulae |

## What each one would actually do

### 1. Checksum workbench & algorithm finder — the highest-value general tool

The single most common dead end in this hobby is "I changed three cells and the
ECU rejects the image". Today the app verifies whole-file checksums for a few
specific profiles; a workbench generalises that.

- Drop a file, pick "find the checksum": the tool sweeps candidate widths
  (1/2/4 bytes), endianness, offsets (start, end, `0x4000`, `0x8000`, tail) and
  algorithms (sum-8/16/32, XOR, CRC-16/CCITT, CRC-16/XMODEM, CRC-32/zlib) and
  reports every combination that would make a stored word match, ranked by how
  many *other* candidate words agree.
- A brand profile list names what is known, not what is guessed: Bosch MSE6.0,
  MSE8.0, MG1; Dell'Orto ECM; Honda Keihin; Italjet/Suzuki; QH250; Yamaha MT.
  Those names and the region rules come from `NetworkDir/moto-ecu-checksum`
  (`algorithms/*.js`), which has no root licence file but declares MIT in its
  README — treat it as facts to reimplement, not code to copy, until that is
  confirmed.
- Repair writes to a **copy** and reports before/after bytes and the SHA-256,
  exactly like the existing external-backup attestation flow.
- Risk: the tool never claims a repaired image is flash-ready. That sentence
  goes in the panel, the help article and the exported report.

### 2. ROM region & entropy map

Unknown dumps are opaque. A sliding-window entropy strip plus a
"runs-and-repeats" detector makes the shape of an image visible in one screen:
code and compressed blocks look different from a 16-bit table grid, and a
repeated row often marks an axis. Deliverables: the strip, a table of candidate
regions with size and fill ratio, click-to-hex, and a two-image diff view
(added / removed / identical regions). No hardware, no external data, works in
the hosted demo. This is the natural companion to the XDF editor: find the
region here, then author or load a definition for it.

### 3. XDF library table finder

We bundle 121 definitions and the app can only show them one at a time. A
finder answers questions like "which Ducati definitions expose an injection
table above 0x8000", "which files define `Idle RPM` and do they agree on the
address", "show every table whose units are `ms`". It reuses `maps.py` parsing,
adds an index across the library, and plugs into the brand filter that already
exists on the Tools bench. Cheap, brand-organised and unique to this project.

### 4. OBD-II / EOBD explorer

Many modern bikes (Royal Enfield 650s, Euro-5 machines, several Triumphs) speak
plain OBD-II over a 16-pin or 6-pin connector. A decoder for Mode 01 live PIDs,
Mode 03/07 stored and pending DTCs, Mode 09 VIN/CAL-ID, plus a PID dictionary
with the standard scaling, is a general tool with per-brand profiles on top.

- `moca-owner-dev/RoyalEnfieldObd` (MIT) documents the Interceptor 650 polling
  set — `0x0C` RPM, `0x0D` speed, `0x11` throttle, `0x0B` MAP, `0x0F` IAT,
  `0x5C` engine-oil temperature, `0x04` load — with the standard conversions
  (`0x0C` = (A·256+B)/4, `0x0F` = A−40, `0x11` = A·100/255) and a gear estimate
  from RPM and speed. That is a ready-made Royal Enfield profile.
- Accepts either a connected adapter (desktop) or a pasted ELM327/candump log
  (hosted demo), so the same panel works in both builds.

### 5. CAN database (DBC) importer & frame decoder

Every capture tool in this space eventually needs one. Import a `.dbc`, read
`BO_`/`SG_` messages and signals (start bit, length, endianness, scale, offset,
min/max, unit, value tables), then decode a `candump` log or the live observer
against it and export CSV. `ebroecker/canmatrix` (BSD-2-Clause) documents the
format semantics and the traps (`@1+` Motorola vs Intel, multiplexed signals,
`VAL_` tables). A bundled example can be the Yamaha R9 `analysis/r9.dbc` this
repo already references, and the Zero DBC below — but check the licence of each
DBC file itself before bundling it; several of these repos have no root licence.

### 6-16. Format and protocol tools

- **`.mlg` importer**: MLVLG is a documented binary log (header, channel
  definitions, per-record type tags). `karniv00l/mlg-converter` (MIT) is a
  working reference implementation in JS, which means the importer can live in
  the web build rather than in Python. Once channels are parsed, the existing
  AFR/VE analysis, the JetDrive overlay and the dyno view all get new inputs.
- **Suzuki SDS**: `KDS2Bluetooth` `TSuzuki.ino` decodes a fixed response:
  DTC count at byte 6, two frozen frames at 7–12, speed at 16, RPM from 17/18
  (×100), throttle at 19, MAP at 20 (`A·166.7/255−20`), coolant at 21 and IAT at
  22 (`A·160/255+10`), gear at 26. That is exactly the shape of the existing
  `hondaOffline` decoder, so the tool is a table plus a panel. The repo is
  GPL-3.0 with no hardware validation from us: ship it as a research decoder
  with the offsets cited and a "source bike: GSX-R 600 K6" note.
- **Kawasaki KDS**: the iKawa session is already vendored (MIT) and switched on
  in the diagnostics view, with `0x04` throttle, `0x02` boolean and `0x44`
  converted to hours at whole-minute resolution. The tool adds a register table,
  the offline response decoder, and the Ninja 7 KWP-on-CAN lengths from
  `kawasaki_ninja7.py`.
- **Ducati**: the Panigale/Mitsubishi decoder is already written and tested
  against synthetic frames; the tool is mostly UI plus the 29 bundled
  definitions. `Fatom2k/DucatiCanBus` adds one more frame (`0x00000080`) for
  cross-checking.
- **Moto Guzzi / Aprilia**: 42 bundled definitions and a working legacy IAW
  reader, with no brand group and no way to see an image's layout. The tool is
  "pick definition → drop image → see region, checksum and the tables the XDF
  claims", which also finally gives the project's namesake brand a home.
- **Royal Enfield**: the OBD-II profile above, plus an explicit research entry
  for Hunter 350 keyed/signature checksums, which `moto-ecu-checksum` documents
  as unsupported. Recording the gap is more useful than pretending.
- **BMW Motorrad**: `BmwMotorradCanbusDecoder` shows the arithmetic pattern —
  engine temperature = byte·0.75−24, a brake-lever nibble, wonder-wheel codes
  `0xFD`/`0xFE` — over a capture. Small, honest, offline decoder.
- **KTM / Husqvarna**: `gobftald/CCM450-diag` implements a candidate KMSK16 KWP
  session (and reports that the CCM 450 and Husqvarna 449/511 share it);
  `Junix330/AD-KTM-ECU` is a read-only attempt. This one is deliberately last:
  it is the least verified and the closest to a write path.
- **Zero / Energica**: an EV brand group sounds off-brand for a Guzzi app, but
  the same users own them and the frames are simple — the Zero SR/S DBC defines
  `SoC_Percentage` on `0x253` with remaining charge time. Note the repo has no
  licence, so re-derive the message from a user-supplied DBC instead of
  bundling theirs.
- **Tune-file diff**: `.msq` and TunerStudio `.ini` semantics are documented by
  rusEFI and Speeduino; MotoLink's `.mtl` is a third dialect. Comparing two
  tunes cell by cell — and exporting a patch — complements the existing
  session-diff and XDF tools.
- **J1939 / ISO-TP frame lab**: the arithmetic already exists in `isotp.py`,
  `kwp2000.py` and the Indian J1939 profile; the tool just exposes it. Useful
  for anyone staring at an extended-ID capture asking "what PGN is that".
- **Wideband lab**: the ZT-2 → LogWorks converter is one curve. Innovate
  LC-2/MTX-L, AEM X-series, 14Point7 SLC and Bosch LSU 4.9/4.2 all publish
  transfer functions, and every one of them also needs λ↔AFR and E10/E85
  stoich conversions before two logs can be compared.
- **Injector / fuel calculator** and **dyno correction factors** are classic
  bench tools that pair naturally with the existing VE analysis and the JetDrive
  overlay; both are arithmetic, both fit in a panel.

## Suggested sequence

**Batch 1 — offline, no hardware, highest payoff per line** *(shipped — see
[the offline toolkit](OFFLINE_TOOLKIT.md))* (fits the hosted
demo and needs no new protocol risk): checksum workbench, ROM region map, XDF
library finder, wideband lab, J1939/ISO-TP lab. All five are pure file-in,
answer-out, and all five make the existing tuning pipeline more useful.

**Batch 2 — new external formats**: `.mlg` importer, DBC importer, OBD-II
explorer with the Royal Enfield profile, tune-file diff. *(shipped — see
[format tools](FORMAT_TOOLS.md))* These bring other
people's data into the workstation and are the tools most likely to be used
weekly.

**Batch 3 — brand bench**: Kawasaki, Suzuki, Ducati, Moto Guzzi/Aprilia,
Triumph and Indian tools that surface the protocol modules already in the tree,
plus BMW and Zero decoders. This is where the brand organisation pays off, but
each one needs the same care the Harley tools got: source scope, synthetic
tests, and no write claim.

**Batch 4 — only with a hardware plan**: KTM/Husqvarna KMSK16, CFMoto MSE8/MG1
checksums, Royal Enfield keyed checksums. Lowest evidence, highest risk.

## Sources read for this pass

| Source | Pin | Licence | Taken |
| --- | --- | --- | --- |
| [NetworkDir/moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum) | `43ccc5f3663e` | none detected; README says MIT | Algorithm names, region rules — facts only |
| [HerrRiebmann/KDS2Bluetooth](https://github.com/HerrRiebmann/KDS2Bluetooth) | `bb8be32a6ed5` | GPL-3.0 | Suzuki/Kawasaki/Honda response offsets |
| [gabrielerandazzo/iKawa](https://github.com/gabrielerandazzo/iKawa) | `79eb9049d130` | MIT | Already vendored; KDS registers |
| [moca-owner-dev/RoyalEnfieldObd](https://github.com/moca-owner-dev/RoyalEnfieldObd) | `2317442d813f` | MIT | OBD-II PID set and scalings |
| [diogocardoso28/BmwMotorradCanbusDecoder](https://github.com/diogocardoso28/BmwMotorradCanbusDecoder) | `a12888976707` | none | Frame arithmetic only |
| [Fatom2k/DucatiCanBus](https://github.com/Fatom2k/DucatiCanBus) | `7f4beffe9509` | none | One frame ID for cross-checking |
| [Junix330/AD-KTM-ECU](https://github.com/Junix330/AD-KTM-ECU) | `d61be53a8ffe` | none | Read-only KTM lead |
| [gobftald/CCM450-diag](https://github.com/gobftald/CCM450-diag) | `43104d2cfca9` | none | KMSK16 KWP job list |
| [Slevinoo/ZeroMotorcycles_SRS_CANbus](https://github.com/Slevinoo/ZeroMotorcycles_SRS_CANbus) | `28de21313a8e` | none | DBC structure example |
| [ebroecker/canmatrix](https://github.com/ebroecker/canmatrix) | `8b54a41dd44b` | BSD-2-Clause | DBC/ARXML semantics |
| [karniv00l/mlg-converter](https://github.com/karniv00l/mlg-converter) | `3c4253bec864` | MIT | MLVLG format |
| [RomRaider/RomRaider](https://github.com/RomRaider/RomRaider) | `dafe0c36c1a6` | GPL-2.0 | Definition/log XML semantics only — GPL-2.0 is not compatible with this AGPL-3.0-only tree |
| [danielhrisca/asammdf](https://github.com/danielhrisca/asammdf) | `8491873b5fe8` | "other" — verify first | MDF4 reading, if the licence allows |

Bundled third-party assets keep the existing convention: provenance in
`guzzionboard/xdfs/PROVENANCE.json`, licence text in `LICENSES/`, and a row in
the relevant `docs/` file.
