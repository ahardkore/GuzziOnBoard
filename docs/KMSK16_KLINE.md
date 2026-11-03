# Keihin KMSK16 on K-Line: what the evidence supports

The KMSK16 is the ECU in the KTM 450/500 four-stroke generation, the Husqvarna
449 and 511, and the CCM 450 Adventure. It speaks ordinary KWP2000 at 10,400
baud over a single K-Line wire. What is unusual is that its live data is
addressed with **Keihin's own data identifiers**, not SAE PIDs, so decoding a
capture needs a table rather than a PID list.

This document records what that table is, where each entry comes from, which
numbers are stated and which are inferred, and what is deliberately absent. It
is the evidence behind [`guzzionboard/protocol/kmsk16.py`](../guzzionboard/protocol/kmsk16.py),
[`web/kmsk16.js`](../web/kmsk16.js) and the KTM and Husqvarna panels.

## 1. Source and its licence position

Everything below comes from **`gobftald/CCM450-diag`**, pinned at commit
`43104d2cfca93368b3eac2f396e65754e1493728` (2026-08-06). It is one owner's
reverse-engineered diagnostic stack for a motorcycle with no factory tool,
including an EDIABAS-style job description recovered alongside it.

**The repository has no licence file.** GitHub reports no licence, the README
claims none, and nothing in the tree grants redistribution. So nothing here is
copied:

- the frame layout, the addresses, the service set, the identifiers, the ranges
  and the enumerations are **facts**, reimplemented in this project's own code
  with attribution;
- no source file from that repository is vendored, translated or paraphrased;
- the identifier table is re-expressed in this project's vocabulary — the
  channel names, units, rules and conflict notes below are written here, not
  lifted;
- the **security-access key is not reproduced**, here or in the code. It was
  obtained by brute force and is supplier-specific.

This is the same policy already applied to `NetworkDir/moto-ecu-checksum`,
which likewise declares a licence in its README but ships no licence file: take
facts, not code, and say so.

## 2. Transport and framing

| Property | Value | Where it comes from |
| --- | --- | --- |
| Line | K-Line, one bidirectional 12 V wire | `studies/cyd/src/adapter/l9637.rs` (L9637D transceiver) |
| Speed | **10,400 baud** (`KWP2000_BAUDRATE`) | same file |
| Fast init | 25,000 µs half period (`FAST_INIT_HALF_PERIOD`), then StartCommunication | `studies/cyd/src/ecu/ccm450.rs` |
| Format byte | `0x80` — physical addressing | same file (`FORMAT_BYTE`) |
| Target | `0x12` (ECU) | same file (`TARGET_ADDR`) |
| Source | `0xF1` (tester) | same file (`SOURCE_ADDR`) |
| Checksum | one-byte sum of every preceding byte | `studies/cyd/src/protocol/kwp2000.rs` |

The framing those constants produce is **the framing this repository already
implements**. The source writes `buf[0] = format + plen + 1` where `plen` counts
the parameters *after* the service identifier; this repository writes
`FMT = 0x80 | len` where `len` counts the service identifier too. Add the
service byte to one and subtract it from the other and they are the same
number, with the same address bytes in the same order:

```
80 F1 12 62 01 00 0B B8 AE
^  ^  ^  ^  ^^^^^ ^^^^^ ^^
│  │  │  │  └─────┴─────┴─ checksum: sum of all preceding bytes, & 0xFF
│  │  │  └── service 0x62 = positive response to ReadDataByCommonIdentifier
│  │  └── source (ECU 0x12 answering tester 0xF1)
│  └── target
└── format byte 0x85 = 0x80 | 5, five payload bytes
```

So the panel needed no new codec: `tests/test_kmsk16.py` builds its vectors with
this repository's own `kwp2000.encode_request`, and a checksum change breaks a
test rather than a motorcycle.

## 3. Services

Named in the job description, with the positive response each expects:

| Service | Name | Positive |
| --- | --- | --- |
| `0x10` | StartDiagnosticSession | `0x50` |
| `0x11` | EcuReset | `0x51` |
| `0x14` | ClearDiagnosticInformation | `0x54` |
| `0x17` | ReadStatusOfDiagnosticTroubleCodes | `0x57` |
| `0x18` | ReadDiagnosticTroubleCodesByStatus | `0x58` |
| `0x1A` | ReadEcuIdentification | `0x5A` |
| `0x20` | StopDiagnosticSession | `0x60` |
| `0x22` | **ReadDataByCommonIdentifier** | `0x62` |
| `0x23` | ReadMemoryByAddress | `0x63` |
| `0x27` | SecurityAccess | `0x67` |
| `0x31` / `0x32` | Start / StopRoutineByLocalIdentifier | `0x71` / `0x72` |
| `0x34`–`0x37` | download, upload, transfer, exit | `0x74`–`0x77` |
| `0x3B` / `0x3D` | write data / write memory | `0x7B` / `0x7D` |
| `0x3E` | TesterPresent | `0x7E` |
| `0x81` / `0x82` | Start / StopCommunication | `0xC1` / `0xC2` |

`0x22` is the only service this project decodes into values. The rest are named
so a capture is readable, and the negative response `7F <service> <code>` is
translated with the same NRC table the IAW profiles use
(`guzzionboard/protocol/kwp2000.py`), so the two cannot disagree about why a
read was refused.

## 4. Data identifiers

51 identifiers, as published. `Value rule` is what the code applies; **stated**
means the source gives the scaling or formula, **inferred** means it was worked
out from the declared range or from an example capture the source recorded, and
is labelled as such in the panel. Identifiers with nothing derivable are shown
as raw bytes.

| Identifier | Channel | Unit | Declared range | Value rule | Evidence |
| --- | --- | --- | --- | --- | --- |
| `0x0000` | Throttle position sensor voltage (THAD) | V | 0–5 | 5/1023 per count | inferred (10-bit ADC, `0x03FF` example) |
| `0x0001` | Throttle position (THM) | deg | 0–80 | 1 °/count, % = THM/80×100 | inferred + stated formula |
| `0x0002` | Manifold pressure voltage (PM1) | V | 0–5 | 5/1023 per count | inferred (`0x03FA` example) |
| `0x0003` | Manifold absolute pressure (PM1) | mbar | 0–65535 | 1 mbar/count | inferred |
| `0x0006` | Battery voltage at the A/D converter | V | 0–5 *(conflict)* | 0.1 V/count | inferred from `0x0075` → 11.7 V |
| `0x0007` | Battery voltage, scaled channel | V | 0–5 *(conflict)* | 0.1 V/count | inferred from `0x0070` |
| `0x0008` | Coolant sensor voltage | V | 0–5 | 5/1023 per count | inferred (`0x03FF`) |
| `0x0009` | Engine coolant temperature (TW) | °C | −40–215 | 1 °C/count, offset −40 | inferred |
| `0x0010` | Intake air sensor voltage | V | 0–5 | 5/1023 per count | inferred (`0x03FF`) |
| `0x0011` | Intake air temperature (TA) | °C | −40–215 | 1 °C/count, offset −40 | inferred |
| `0x0012` | Lambda sensor voltage (VHG1) | V | 0–5 | 5/1023 per count | inferred (`0x03F6`) |
| `0x0018` | Second throttle actuator voltage | V | 0–5 | 5/1023 per count | inferred |
| `0x0040` | Neutral switch | — | — | enum | stated |
| `0x0053` | Sport switch input (MAPCHG) | — | — | enum | stated |
| `0x0060` | Fuel pump relay (FLPR) | — | — | enum | stated |
| `0x0064` | Lambda heater (HG1HT) | — | — | enum | stated |
| `0x0100` | Engine speed (NE) | rpm | 0–16384 | 0.25 rpm/count | inferred (16384 × 4 = 65536) |
| `0x0102` | Short-term fuel trim (MHG1) | ratio | 0–2 | 2/65536 per count | inferred |
| `0x0107` | Calculated load (CLV) | % | 0–100 | **formula only** | stated, not applied |
| `0x0110` | Injector on-time (TIOUT1) | µs | 0–65535 | 1 µs/count | inferred |
| `0x0120` | Ignition timing (IGAB1) | deg | −64–64 | 0.5 °/count, offset −64 | inferred (`0x0080` → 0°) |
| `0x0130` | Ignition coil dwell (IGDWELL) | µs | 0–65535 | 1 µs/count | inferred |
| `0x0140` | Throttle flap angle reference (THREF) | deg | ±3276.8 | 0.1 °/count | inferred |
| `0x0142` | Lambda adaption, part load (MREFHG1) | ratio | 0–2 | 2/65536 per count | inferred |
| `0x0143` | Lambda adaption, idle (MREFHG1ID) | ratio | 0–2 | 2/65536 per count | inferred |
| `0x0149` | Lambda adaption, displayed (MRFH1DEC) | ratio | 0–2 | 2/65536 per count | inferred |
| `0x0170` | Second throttle actual angle (STHAD) | deg | 0–80 | **formula only** | stated, cross-frame |
| `0x0171` | Second throttle target angle (STHTRG) | deg | 0–80 | 1 °/count | inferred |
| `0x0172` | Second throttle reference, low (STHADLL) | V | 0–5 | 5/1023 per count | inferred |
| `0x0173` | Second throttle reference, high (STDHADHH) | V | 0–5 | 5/1023 per count | inferred |
| `0x0174` | Second throttle actuator steps, max (STHSTEPH) | steps | 0–32767 | 1 step/count | inferred |
| `0x0185` | Purge valve duty cycle | % | 0–100 | raw | stated range only |
| `0x0500` | Sport switch memory (RaceMAP) | — | — | enum | stated |
| `0x0501` | Over-rev counter, total | min | 0–196605 | 3 min/count | inferred (196605 = 65535 × 3) |
| `0x0502`–`0x0509`, `0x0510` | Over-rev counter, areas 1–9 | s | *(conflict)* | raw | two ranges, see §5 |
| `0x1000` | Test stamp | — | — | raw bytes | programming stamp |
| `0x1001` | DTC environmental condition: engine speed | — | — | raw bytes | inside a fault record |
| `0x2500`–`0x2506` | programming references, flash geometry | — | — | raw bytes / ASCII | programming only |

Enumerations are `0x0000` / `0x00FF` pairs, exactly as the job description
writes them — neutral/engaged, standard/sport, off/on — and any other value is
reported as not one of the declared states rather than mapped to a nearest
match.

## 5. Where the source disagrees with itself

Four places, recorded rather than resolved. They are the reason the panel
derives no number for these identifiers:

1. **Over-rev counters, areas 1–9.** The job entries declare `0–6553.5 s`
   (0.1 s/count); the identifier summary at the end of the same file declares
   `0–196605 min` (3 min/count). A factor of 1800 apart.
2. **Battery voltage.** `0x0006` declares `0–5 V` and prints its own example as
   `0x0075 - 117 - 11.7V`. Both cannot be true; the example wins in the panel,
   and the conflict is printed beside the value.
3. **Second throttle percentage.** The source writes
   `(STHAD-STHADL)/(STHADH/STHADL)*100%` — dividing by a *ratio* of two A/D
   values, which does not produce a fraction of span. The dimensionally
   consistent reading is `(STHAD − STHADL) / (STHADH − STHADL) × 100 %`. The
   panel prints the source text and, when all three frames are pasted, shows the
   rewritten version labelled as rewritten.
4. **Area numbering.** The identifiers run `0x0502`–`0x0509` and then **jump to
   `0x0510`** for area 9; `0x050A`–`0x050F` are unused. A computed range would
   have invented six identifiers that do not exist.

Also worth naming: this document's earlier summary of the same source (in
[`CHECKSUM_AND_DECODER_EVIDENCE.md`](CHECKSUM_AND_DECODER_EVIDENCE.md) §4.1)
described `0x0140`–`0x0149` as "lambda heater references". That was wrong:
`0x0140` is the throttle flap angle reference, and only `0x0142`, `0x0143` and
`0x0149` are lambda adaptions. The table above replaces it.

## 6. Routines

| Routine | Name | What it does | Status here |
| --- | --- | --- | --- |
| `0x0102` | CheckCodingChecksum — application code | asks the ECU whether its own program block is internally consistent | decoded only, read-only |
| `0x0104` | CheckCodingChecksum — calibration data | same, for the calibration block | decoded only, read-only |
| `0x0A00` | CheckProgrammingStatus | programming state | decoded only |
| `0xA600` | Purge control valve ON/OFF test | actuator test | name only |
| `0x9000` | FLASH_DELETE_K16 | erase | name only, **not implemented** |

The two `CheckCodingChecksum` routines are the interesting ones: they are the
only read-only way this ECU offers to ask whether a calibration is internally
consistent, without reading flash and without the supplier's tool. They are the
KMSK16 answer to the question the checksum workbench asks of an image file, and
they are implemented here only as decoders for the routine *response* — nothing
in this project starts a routine.

## 7. What is absent, deliberately

- **Security access.** `0x27` is recognised in a capture and named. The key is
  not in this project: it was brute-forced in the source, is supplier-specific,
  and shipping it would turn a decoder into a way into an ECU. Some model years
  may require it even for `0x22` reads, which is one reason the panel only reads
  captures.
- **Any programming sequence.** The job set names erase, download, transfer,
  write-data and write-memory services and gives a 22-byte buffer layout for the
  erase argument. A name and a layout are not a verified sequence, and none of
  them is implemented for this ECU.
- **Any physical validation.** The entire table comes from one reverse-engineered
  CCM 450 Adventure. That the Husqvarna 449/511 share the ECU is the source
  author's report, not a measurement made here, and no KTM was involved at all.
- **A checksum algorithm.** The `CheckCodingChecksum` routine tells you the
  ECU's opinion; it does not tell you how the checksum is computed. See
  [`CHECKSUM_AND_DECODER_EVIDENCE.md`](CHECKSUM_AND_DECODER_EVIDENCE.md) §2 for
  the families whose algorithms *are* known — KMSK16 is not one of them.

## 8. Where this is implemented

| Layer | File | What it does |
| --- | --- | --- |
| Python | `guzzionboard/protocol/kmsk16.py` | table, frame decode, capture decode, cross-frame derivation |
| Browser | `web/kmsk16.js` | the same table and rules, driving the two panels |
| Panels | `web/index.html` (`#ktmKmsk16`, `#husqvarnaKmsk16`) | paste, decode, reference table rendered from the decoder's own data |
| Help | `web/help-content.js` (`ktm-kmsk16-decoder`, `husqvarna-kmsk16-decoder`, protocol `kmsk16`) | how to use it and what it cannot tell you |

## 9. Tests

`tests/test_kmsk16.py` covers:

- framing: the source's `fmt = 0x80 + len + 1` is this repository's
  `FMT = 0x80 | len`, proven by building every vector with
  `kwp2000.encode_request`;
- checksum rejection, strict tokenising (a `ZZ` token or a candump line is
  refused rather than trimmed into a frame), and the five-byte minimum;
- one decoding test per identifier family: scalar with an inferred scale, an
  enumeration, an ASCII identifier, a negative response, a routine response, an
  unknown identifier, an unknown service;
- that a decimal-free run of hex digits is still a frame;
- the four source conflicts above: each must be *reported*, not resolved, and
  the over-rev counters must derive no value;
- the cross-frame second-throttle percentage, the missing-identifier message and
  the empty-span case;
- that the JavaScript table and the Python table are identical, field by field,
  and that both decoders produce byte-identical output for the same frame;
- that the security key does not appear in either source file;
- the panels, their brands, the script order and the help articles.

`tests/browser/kmsk16.spec.mjs` drives the panels the way an operator does.
