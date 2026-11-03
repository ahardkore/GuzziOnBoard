# Brand tools — one decoder per manufacturer

Batch 3 of the [tool expansion](TOOL_EXPANSION_RESEARCH.md). Six brand decoder
panels and two image-layout panels, all of them offline: nothing here talks to a
motorcycle, and none of them can transmit, clear a fault or write a byte.

Two rules run through every panel.

1. **Formulas are not invented here.** Each decoder is the browser twin of a
   Python protocol module already in the tree, or of a profile in
   `web/multibrand-offline.js`. Where the Python and the browser disagree the
   Python is the reference and the browser follows it.
2. **A refusal beats a guess.** A frame with the wrong length, the wrong
   identifier, the wrong checksum or the wrong source address is rejected with
   the reason. An unverified channel is shown raw and labelled unverified.

The safety rule the rest of the program uses still applies: **a decoded byte is a
research lead. It is not vehicle identification, not a verified backup, and never
a write authorisation.**

## Where the panels are

Tools → Brand dropdown → the manufacturer. Each panel lives under its own brand
heading, and the Help center has one article per panel (search the brand name).

| Panel | Brand | What it decodes |
| --- | --- | --- |
| `#kawasakiKds` | Kawasaki | KDS K-Line answers, local identifier by local identifier |
| `#suzukiSds` | Suzuki | the SDS all-sensors answer |
| `#triumphIso` | Triumph | ISO 9141 bursts carrying SAE mode 01 PIDs |
| `#bmwCan` | BMW Motorrad | three 11-bit broadcast frames |
| `#ducatiCan` | Ducati | three Panigale Mitsubishi frames |
| `#indianJ1939` | Indian | five J1939 PGNs, with source address |
| `#iawGuzziPanel` | Moto Guzzi | IAW image geometry and definition fit |
| `#iawApriliaPanel` | Aprilia | the same check for the Aprilia library |

## How to use any decoder panel

1. Capture the traffic first — with the diagnostics view, an adapter log or
   `candump`. The panel never captures anything itself.
2. Paste complete frames, one per line, up to 100 per decode.
3. Press **Decode locally**. Each frame produces either values with their raw
   bytes, or one `Rejected: …` line naming the reason.
4. Read the counter under the buttons: `n of m frame(s) decoded` tells you how
   much of the paste was actually interpreted. A low count is information, not
   an inconvenience.
5. Open **Identifiers and formulas this profile implements** to see exactly what
   the decoder knows. That table is generated from the decoder's own data, so it
   cannot drift away from the code.

## Kawasaki — KDS / K-Line

Source: `iKawa`, Copyright (c) 2026 Gabriele Randazzo, MIT
(`LICENSES/iKawa-MIT.txt`), the same source the live diagnostics view uses.
Python reference: `guzzionboard/protocol/kawasaki_er6n.py`. Browser decoder:
`decodeMultiResearch('kawasaki_er6n', line)` in `web/multibrand-offline.js`.

Input is the complete addressed response
`80 F1 11 <len> 61 <local id> <data> <sum>`. The frame length byte and the
summing checksum must both agree, or nothing is decoded.

Kawasaki defines its own local identifiers. They are **not** SAE PIDs, and each
one has its own length:

| Local ID | Channel | Formula |
| --- | --- | --- |
| 0x02 | switch | any non-zero byte |
| 0x04 | throttle | `((raw − 226) × 100 / 635) + 2 %` |
| 0x06 | coolant | `(a − 48) / 1.6 °C` |
| 0x07 | intake air | `(a − 48) / 1.6 °C` |
| 0x09 | engine speed | `a × 100 + b rpm` |
| 0x0A | battery | `a / 12.75 V` |
| 0x0B | gear byte | raw, interpretation unverified |
| 0x0C | road speed | `(a × 100 + b) / 2 km/h` |
| 0x44 | engine hours | `raw / 3600`, semantics unconfirmed |

Scope: one reverse-engineered source reading one 2006 ER-6n. A value here is a
candidate for that model, not a fitment claim for another Kawasaki.

## Suzuki — SDS / K-Line

Source: `SV650overlay` (BananaJoh), GPL-3.0
(`LICENSES/SV650overlay-GPL-3.0.txt`). Python reference: `decode_sv650ak7` in
`guzzionboard/protocol/aster_kline.py`, used by the `suzuki-sv650ak7-2007`
diagnostics method.

Input is the complete **57-byte** all-sensors answer (`80 F1 12 34 61 08 …`).
Anything shorter is rejected rather than decoded — a checksum byte read as data
is exactly how a plausible wrong number appears.

| Byte | Channel | Formula |
| --- | --- | --- |
| 17 | engine speed | `trunc(b17 × 6.9) × 10 rpm` — the source uses the high byte only |
| 19 | throttle | `(b19 − 58) × 0.6 %` |
| 20 | manifold pressure | `b20 × 166.7 / 255 − 20 kPa` |
| 21 | coolant | `b21 − 40 °C` |
| 22 | intake air | `b22 − 40 °C` |
| 24 | battery | `(b24 + 109) × 0.05 V` |
| 26 | gear / status | raw byte |

Published SDS implementations disagree about several of these conversions. Where
they do, the panel names the one it used instead of presenting a single number as
fact.

## Triumph — ISO 9141 / SAE mode 01

Source: `daytona-kline`, Copyright (C) 2026 Andrew Wilke, GPL-3.0-or-later
(`LICENSES/Daytona-Kline-GPL-3.0.txt`), tested by its author on one 2012 Daytona
675. Python reference: `guzzionboard/protocol/triumph_daytona.py`.

Input is one complete burst `48 6B D1 41 <pid> <data> <sum>`. The header and the
summing checksum are verified before the PID is read, and only positive `0x41`
answers are interpreted; a `0x7F` refusal is reported as a refusal.

| PID | Channel | Formula |
| --- | --- | --- |
| 0x04 | engine load | `A × 100 / 255 %` |
| 0x05 | coolant | `A − 40 °C` |
| 0x06 | short-term fuel trim | `(A − 128) × 100 / 128 %` |
| 0x0B | manifold pressure | `A kPa` |
| 0x0C | engine speed | `(A × 256 + B) / 4 rpm` |
| 0x0D | road speed | `A km/h` |
| 0x0E | timing advance | `A / 2 − 64 °` |
| 0x0F | intake air | `A − 40 °C` |
| 0x11 | throttle | `A × 100 / 255 %` |

An answer proves the PID exists on that ECU. It proves nothing about which
Triumph, or which model year, is on the other end of the cable.

## BMW Motorrad — 11-bit CAN

Source: `EasierCan`, Copyright (c) 2026 HagayBT, MIT
(`LICENSES/BMW-R1300GS-EasierCan-MIT.txt`).

Input is one frame per line, `10C#0011223344556677`. Identifiers above `0x7FF`
and payloads longer than eight bytes are refused.

| ID | Channel | Formula |
| --- | --- | --- |
| 0x10C | engine speed | `(b2 × 256 + b1) / 4 rpm` |
| 0x2D0 | high-beam flash | bit `0x10` of byte 6, active low |
| 0x2D2 | switch cluster | byte 0: left `0x04`, right `0x08`, brake `0x20` |

The source does not record the direction of these frames. A switch bit that
reads 1 says a message carried that bit, not that the switch works.

## Ducati — Panigale Mitsubishi CAN

Source: `DucatiPanigaleCanBus`, Copyright (c) 2021 Renato Bonomini, MIT
(`LICENSES/DucatiPanigaleCanBus-MIT.txt`). Python reference:
`guzzionboard/ducati_panigale_can.py`. Browser decoder:
`window.gobBrandTools.decodeDucatiFrame`.

Input is candump form, `can0 080#…` or `can0 18 [8] …`. Extended identifiers are
refused: this layout describes 11-bit frames, and a 29-bit identifier with the
same numeric value is a different message.

| ID | Channel | Formula |
| --- | --- | --- |
| 0x18 | rear wheel speed | `((b4 & 0x1F) << 4) + (b5 >> 4)` km/h |
| 0x18 | gear | `b4 / 32`, raw — the source does not map it to a gear number |
| 0x80 | throttle | `b4 / 2 %`, truncated as the source does |
| 0x80 | engine speed | `b5 × 256 + b6` rpm |
| 0x100 | coolant | `b3 − 40 °C` |
| 0x100 | battery | `b4 / 10 V` |
| 0x100 | air temperature | `b5 − 40 °C` |

## Indian — J1939

Source: `indian-thunderstroke-canbus`, Copyright (c) 2026 Nanna Agesen, MIT
(`LICENSES/Indian-Thunderstroke-CAN-MIT.txt`), one 2017 Springfield, integration
tested with synthetic frames only. Python reference:
`guzzionboard/indian_springfield_can.py` (`PGN_SOURCE`, `MASK`, `FILTER_IDS`).

Input is candump lines with 29-bit identifiers and exactly eight data bytes. The
decoder prints the PGN, the channel and the source address, so an unidentified
extended frame can at least be placed on the bus.

| PGN | Channel | Formula |
| --- | --- | --- |
| 61444 | EEC1 engine speed | `(b3 \| b4 << 8) / 8` rpm |
| 61444 | EEC1 engine demand | `b7 − 125 %` |
| 65262 | ET1 cylinder-head temperature | `b0 − 40 °C` |
| 65265 | CCVS rear speed | `(b1 \| b2 << 8) / 256` km/h |
| 65276 | DD fuel level | `b1 × 0.4 %` |
| 65215 | front wheel speed | `(b0 \| b1 << 8) / 256` km/h |

`0xFF` and `0xFFFF` mean *not available* and are printed that way, never as a
value. The profile is keyed by PGN **and source address**, because that is what
the source recorded: a frame from a PGN the profile knows but from a different
controller is reported with both addresses named, not silently decoded.

The bike is air-cooled, so PGN 65262 is cylinder-head temperature, not coolant.
Reading it as coolant misreports the engine.

## IAW image layout and definition fit

`web/iaw-layout.js`, panels `#iawGuzziPanel` and `#iawApriliaPanel`.

This one answers two questions that otherwise get guessed:

- **Where does this file sit inside the image?** You give the base offset, or
  pick the 5AM flash region, and the panel prints the address range the file
  covers.
- **Does the definition I picked describe tables that are inside it?** Every
  table in the chosen XDF is checked against the bytes you have; tables that fall
  outside are listed with the reason.

The only geometry stated as fact is the one the rest of the program already
states: **IAW 5AM flash region 0x4000–0x50000, 311,296 bytes inside a 320 KiB
image** — the same constant the catalog, the help guides and the programming gate
use. Everything else comes from the definition itself. Aprilia 7SM and MIU G3
catalog entries are identification-only, so the panel makes no claim about where
their flash starts; you supply the base.

Table sizes are `rows × columns × resolution`. A table with a non-standard stride
can be slightly larger in reality, so treat the byte count as an estimate and the
address range as the fact to check.

**What it does not mean.** A file big enough for a definition is not proof that
the definition belongs to that ECU: a definition from another family can describe
plausible tables at the wrong addresses. The panel reports addresses, never a
calibration value — it cannot tell you what a byte means, only whether it is
inside the file you have. Reading a definition is not programming authorization.

The definition list comes from the same index the Maps view and the XDF finder
use: `guzzionboard/maps.py` `library_payload()` in the desktop build, and
`web/xdf-library.json` in the hosted demo, with a fallback to the JSON file so a
statically opened page still works.

## Speedometer and driveline correction

`web/speedo-math.js`, inside the `#gearingPanel` (Workshop, General). Added as an
addition to a shipped tool rather than a new panel, because it is the same
question the gearing table answers — with the part that gets confused added.

Three questions are kept apart, and the panel labels each one:

| Question | Factor | Depends on the speed sensor? |
| --- | --- | --- |
| Speed at the same engine rpm (performance) | `(rear_front / front_from) / (rear_to / front_to) × tyre` | No |
| What the dash reads at the same true speed (indication) | tyre only — or tyre × gearing | **Yes** |
| What a corrector should be set to (correction) | `actual ÷ indicated` | No, it is measured |

- **Sensor on the wheel** (front wheel, rear ABS ring): a sprocket change does
  nothing to the reading; a bigger tyre makes it under-read, because the wheel
  turns fewer times for the same distance.
- **Sensor on the gearbox output** (most shaft-drive and many ABS-less bikes):
  the final-drive ratio is part of the calibration, so a sprocket change moves
  the reading as well. A 15 → 16 tooth front sprocket is −6.25 % at the dash on
  a gearbox sensor and 0 % on a wheel sensor, while the bike is 6.67 % faster at
  the same rpm either way.

Worked example from the panel: 15 → 16 front sprocket and 180/55-17 → 190/55-17,
gearbox sensor, 100 indicated against 92 on GPS → speed +8.53 %, dash −7.86 %,
corrector factor 0.9200 (−8.0 %), and 0.8625 × if the hardware change and the
measured error are combined into one setting.

Tyre circumference is the geometric rolling circumference from the marking
(`π × (rim × 25.4 + 2 × width × aspect/100)`), which is what the gearing panel
already uses. It is not the laden rolling radius — a loaded tyre squats, and a
measured circumference beats a nominal one.

The caution the panel carries: a corrector changes the reading, not the
motorcycle. Where a wheel-speed signal feeds ABS, traction control or a gear
indicator, changing the tyre size changes those systems too.

## Tests

- `tests/browser/brand-tools.spec.mjs` — 10 cases: every panel is filed under its
  brand, each decoder is driven through the UI and through its exported function,
  every rejection message is asserted, the frame limit is enforced, and the layout
  check is verified against hand-computed table fits.
- `tests/test_brand_tools_panels.py` — 9 cases that read both sides and compare
  the facts they share: the Indian PGN/source-address table against
  `indian_springfield_can.PGN_SOURCE` and `FILTER_IDS`, the Ducati identifier
  list and minimum lengths against `ducati_panigale_can.decode_capture`, the
  Kawasaki and Triumph reference tables against the local-ID and PID tables the
  browser decoders actually implement, every panel's control ids, the script
  order, and the 5AM geometry against `guzzionboard/catalog/ecus/5am.json`.
- The Python side is covered by the tests that already existed:
  `tests/test_kawasaki_er6n.py`, `tests/test_triumph_daytona.py`,
  `tests/test_aster_kline.py` (Suzuki) and `tests/test_canlog.py` (Ducati and
  Indian). The browser decoders mirror those modules rather than redefining the
  arithmetic, so a formula change has to happen in both places at once.
- `tests/browser/tools-brand.spec.mjs` checks that each manufacturer keeps the
  modules it documents and that the brand order in the bench, the two dropdowns
  and the help directory stays identical.

## Limits, stated plainly

- One source, usually one motorcycle, per profile. Where a source says nothing
  about model years or ECUs, the panel says nothing either.
- No panel clears faults, transmits, writes or identifies a vehicle.
- Where two published implementations disagree, the profile names the one it
  follows; it does not average them.
- The decoders are pure functions of the text you paste. They cannot validate
  that the capture itself is complete, or that the adapter did not drop a frame.
