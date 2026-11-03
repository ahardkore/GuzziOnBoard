# Checksums and decoders: what the evidence actually says

Research pass, 2026-11-03. This document exists to answer one question honestly:
**for each checksum we might implement and each decoder we might add, what is
written down, where, and how strong is it?**

It is not a feature list. Every entry below states the source, the commit that
was read, the licence, whether the algorithm is *confirmed* against a known-good
file or a second tool, and what would be left unverified. Where nothing public
exists, that is recorded as a gap rather than filled with a guess.

The rule that governs all of it, unchanged from the rest of the program: **a
checksum that matches is evidence that a file is internally consistent, not
evidence that the file is safe to flash.** A decoder that produces a plausible
number has told you the arithmetic, not the truth about the motorcycle.

## How this was gathered

| Source read | Pin | Licence |
| --- | --- | --- |
| `NetworkDir/moto-ecu-checksum` | `43ccc5f3663e` (2026-10-24) | README declares MIT, **no LICENSE file** — facts reimplemented, code not copied |
| `gobftald/CCM450-diag` | `43104d2cfca9` (2026-08-06) | **no licence file** (GitHub reports none); KMSK16 job tables and KWP framing, used as facts, reimplemented — see [KMSK16 on K-Line](KMSK16_KLINE.md) |
| `fpoussin/MotoLink` | `7879a8567dd4` | GPL-3.0 |
| This repository | `HEAD` | AGPL-3.0-only |

Nothing here is copied code. Where a source is GPL-3.0 and this project is
AGPL-3.0-only, the *facts* (an offset, a polynomial, a sum) are reused and the
implementation is written here; that is the same treatment the project already
applies to `KDS2Bluetooth` and `daytona-kline`.

## 1. What is already implemented in this repository

Worth stating first, because three different things are all called "checksum"
and confusing them is the usual bug.

| Kind | Where | What it is |
| --- | --- | --- |
| **Frame checksum** | `guzzionboard/protocol/kwp2000.py` `checksum()` | 8-bit sum of the frame, `sum(data) & 0xFF`. KWP2000 / ISO 14230. |
| **Frame CRC** | `guzzionboard/protocol/harley_j1850.py` `_crc()` | J1850 VPW CRC-8, poly `0x1D`, init `0xFF`, final XOR `0xFF`. |
| **Upload encoding** | `guzzionboard/firmware.py` | IAW 5AM transfer blob: 8-byte magic `C2 07 16 33 6F EB B0 1D`, then per-byte add/rotate/invert with an 8-byte period, transcribed from `5am_util` `encrypt_blob()` and known-answer tested. |
| **Whole-image coherence test** | `guzzionboard/protocol/honda_cbr600rr.py` | Honda research read: the image's 8-bit sum is zero, which is a *candidate* test observed in source examples, not a guaranteed checksum. |
| **Research checksum offsets** | `honda_cbr600rr.py` `HONDA_RESEARCH_CHECKSUM_OFFSETS` | Offsets only where a pinned fork's table lists a non-zero location (`0x3FFF8`, `0x7FFF8`, `0xFFFF8`). Absent locations are **not** guessed. |
| **Generic sums** | `guzzionboard/firmware.py` | `sum16`, `sum32`, `word_sum16` (big/little) for recording an image's identity. |
| **Calibration checksum providers** | `guzzionboard/checksums.py` | Deliberately bundles **no** algorithm: a provider is a user plugin, named by id, process-isolated, fingerprinted into the tuning plan. |

So the gap the [tool expansion](TOOL_EXPANSION_RESEARCH.md) describes is real:
the program can verify a few *specific* things, but it cannot answer "what
checksum does this unknown image use, and where".

## 2. Checksum evidence, family by family

All of the parameters below are from `NetworkDir/moto-ecu-checksum`, whose README
also states the confirmation method for each one. "Confirmed" there means one of
two things, and the README is explicit about which: the factory image verifies
`OK`, or a repaired modified image is **byte-identical (MD5) to a commercial
flash tool's output** for the same file.

### 2.1 Bosch MSE6.0 — CFMoto and others (1.5 MB / `0x180000`)

**Confirmed:** CFMoto NK250 2024 (`F01R00DG1Z_X10A04B228`) — the development
reference; CFMoto 450SR 2023 (`F01R00DKAI_X10G04A120`) — repaired output MD5-
identical to a commercial tool's, flashed and running. Same layout checked on
`X10G04A121`.

The checksum is a **16-byte big-endian record stored inside the region it
protects**:

```
[start:u32][end:u32][checksum:u32][~checksum:u32]
checksum = sum of 16-bit big-endian words over [start, end] inclusive, truncated to 32 bits
```

No seed, no CRC, no polynomial. On the reference ECU there are three records
(`0x140030` covering `0x140000`–`0x157FFB`, `0x140144` covering the first half,
`0x140154` the second).

Two details make this implementable without hardcoded offsets, and both are
worth stealing:

1. **The records are structurally discoverable.** Because a checksum sits next
   to its own one's complement, `cs_hi + ~cs_hi = 0xFFFF` and the same for the
   low half, so each record always contributes exactly `0x1FFFE` to its own
   region sum. The sum is invariant under checksum writes — repair is a single
   pass with no fixed-point iteration — and `find_records()` can locate records
   by scanning the header for quadruples where `cs ^ ~cs == 0xFFFFFFFF`.
2. **Factory images are not always "valid".** Both 450SR factory reads fail the
   two records whose regions include `0x140000`–`0x14FFFF`, and the bike runs on
   them. That is the single most important fact in this whole document for
   anyone building a verifier: *"the factory file fails"* does not mean your
   implementation is wrong, and *"my file passes"* does not mean the ECU will
   accept it.

### 2.2 Bosch MSE8.0 / E186 (256 KiB calibration block)

**Confirmed:** RKS RZ125S 2024 (`F01RB0D2G0_XD105A1A25`) — repaired output
MD5-identical to a commercial tool's.

```
block: 0x40000 bytes, located by footer signature 12 34 56 78 12 34 10 08 at block + 0x3FFE0
checksum = CRC-32 (zlib) of block[0 .. 0x3FFF8) XOR 0xA18AFC77, stored big-endian at block + 0x3FFF8
```

### 2.3 Bosch MG1 / MG1CA094 (Bajaj, KTM, TVS)

**Confirmed on 11 images:** Bajaj Pulsar NS200 2018-22 (`BAK08IN1606005`,
factory + 4 modified), Bajaj NS125 and RS200 (3 calibrations, two layouts), KTM
Duke 390 2017 (3 images including one patched by a flash tool). All blocks
verify; three repaired images are MD5-identical to a commercial tool.

```
block starts with DEADBEEF on a 256 KiB boundary (code at 0x40000 and 0xC0000, calibration at 0x80000)
block ends with a 0x15C-byte 12345678 fill followed by a big-endian CRC
CRC = reflected CRC-32, poly 0xEDB88320, init 0xACC08E37, xorout 0xFFFFFFFF
    == zlib.crc32(block, 0x533F71C8) over [block start .. end of fill]
calibration block length varies: CRC at 0x87F18, 0x87238, 0x88938, 0x8AF38 or 0xBFFF8
```

Two repair modes exist because flash tools use both: rewrite the CRC (`update`),
or keep the original CRC and adjust the free word before the block's `FA FA`
signature marker (`keep`). The second mode is only possible when that word is
free — it holds data on the Duke 390.

**Critical limit:** MG1 calibrations also carry a signature block that this
algorithm does not touch. "The ECU only accepts a modified file if your flash
tool has patched it." Fixing CRCs is not fixing the signature.

### 2.4 Yamaha MT series

**Confirmed:** MT-25 2019 (`BS81_128C8000`), MT-07 2014-16 (`MT07A04E`),
MT-07 2020 (`B342_120C4580`), MT-07 2021 (`BAT1_12464001`), MT-09 SP 2019
(`MT09045A`).

```
sum of all big-endian 16-bit words of the image, checksum included, == 0x5AA5 (1 MiB images)
                                                                     == 0xE81F (896 KiB MT-07 2020 only)
checksum word at end - 8, right after an 8-character software ID
```

The 896 KiB target is confirmed on one image. Anything else would be a guess.

### 2.5 Honda (Keihin) — X-ADV 750, ADV350

**Confirmed:** X-ADV 750 2019 (`MKHF204`), ADV350 2024 (`KN62804B`, two factory
images).

```
one byte at end - 8 (surrounded by 0xFF) makes a byte sum 0 modulo 256:
  X-ADV 750  512 KiB: whole image
  ADV350     768 KiB: 0x10000 to end (KN6xxxxx ID at end - 0x80)
```

This is the same shape as the candidate test already in `honda_cbr600rr.py`,
which is a useful cross-check: two independent sources describe the same family
as a zero-sum modulo 256.

### 2.6 Dell'Orto ECM — Bajaj RS200 2024

**Confirmed:** `JL351458010651`, three calibrations.

```
calibration block at 0x80000 (starts with "JL"), 0xC0000 image
checksum = one's complement of the byte sum of 0x80000..0x921FD
stored big-endian 16-bit at 0x921FE
```

The project already has Dell'Orto *research* in `docs/`; this is the first
checksum statement for that family with a stated confirmation.

### 2.7 QH250

**Confirmed:** `E2400-05`.

```
32 KiB data block at 0x0000 (starts AA AA, ends 55 54 AA 45), 0x140000 image
big-endian 16-bit word sum of 0x0000..0x7FEF, checksum excluded, == 0
checksum at 0x7FEE
```

### 2.8 Italjet / Suzuki-type

**Confirmed:** Italjet Dragstar 200 2023 (`5710BL01` / `33950-03K00`).

```
marker AA 55 CC 33 + part-number string, then checksum and its complement
16-bit little-endian checksum = byte sum of 0x20000..end (value and complement
add to 0x1FE, so they do not disturb the sum), 0x80000 image
```

### 2.9 What this evidence does **not** cover

- **Royal Enfield Hunter 350** (`CAAJ1990`): explicitly unsupported. The 32 KiB
  calibration carries a 219-byte header that "changes completely on every edit
  and contains no plain hash" — a keyed signature or encryption. That cannot be
  derived from examples, and the honest answer is that it stays unimplemented.
  The 650 twins' OBD-II path (already in the OBD explorer) is unrelated to this.
- **Cryptographically signed images** (RSA/ECDSA) and **keyed MACs**: out of
  scope on every ECU, for everyone, without the key.
- **MG1 signature block**: the CRCs are documented; the signature is not.
- **Marelli IAW 7SM, MIU G3, 15M/15P calibration checksums**: no public
  parameter set was found in this pass. The repository has 24 Moto Guzzi and 18
  Aprilia definitions that *declare* checksum titles; that tells us a checksum
  exists and what it is called, not how to compute it.

## 3. How to derive a checksum you have no documentation for

The MSE6.0 write-up is the best template available and it generalises:

1. **Find the region from the image, not from a table.** Look for stored values
   that sit next to their own complement (`cs ^ ~cs == 0xFFFFFFFF`) or next to a
   plausible `[start][end]` pair. That invariant is what makes the checksum
   insensitive to its own value and therefore repairable in one pass.
2. **Try the cheap families first, in this order:** 8/16/32-bit byte sum, 16-bit
   word sum (both endiannesses), one's complement of each, then XOR, then the
   CRC catalogues (CRC-16/CCITT-FALSE, XMODEM, ARC, CRC-32/zlib, with the
   `init`/`xorout` variants). Every one of the eight families above is a sum or a
   CRC-32 with a documented init and xorout; nothing in this family tree is
   exotic.
3. **Confirm with a second artefact, never with one file.** Either the factory
   image verifies, or a file repaired by your code is byte-identical to one
   repaired by a known tool. The MSE6.0 450SR case shows why a factory image
   alone is insufficient.
4. **Expect the length to vary.** MG1 calibration blocks end at five different
   offsets depending on the calibration; a hardcoded offset is a bug waiting for
   the next model year.

## 4. Decoder evidence

### 4.1 Keihin KMSK16 (KTM, Husqvarna 449/511, CCM 450 Adventure)

Source: `gobftald/CCM450-diag` @ `43104d2` — a reverse-engineered, working
diagnostic stack for a bike with no factory tool, plus an EDIABAS-style job
description (`docs/KMSK16_jobs.txt`) recovered alongside it.

What is written down:

- **Transport:** K-Line through an L9637D, **10,400 baud**, KWP2000 framing.
- **Frame format** (`studies/cyd/src/protocol/kwp2000.rs`): format byte
  `0x80 + len + 1`, target, source, service id, parameters, then an **8-bit sum
  checksum** of everything before it — exactly the `checksum()` this project
  already uses in `kwp2000.py`. A response is rejected unless the sum matches.
- **Service ids used:** `0x11` ECU reset, `0x14` clear DTCs, `0x18` read DTCs by
  status, `0x22` read data by common id, `0x27` security access, `0x31`/`0x32`
  start/stop routine, `0x3E` tester present, `0x81` start communication.
- **Data ids**, with the author's own names and formulas — this is the decoder
  table, and it is unusually complete: `0x0100` engine rpm as a 2-byte
  high/low value (NE), `0x0102` short-term fuel trim, `0x0107` calculated load
  `CLV = (PM1M / 10103 mbar) × 100 %`, `0x0110` injector on-time, `0x0120`
  ignition timing, `0x0130` dwell, `0x0140`–`0x0149` lambda heater references,
  `0x0170` second-throttle position
  `(STHAD − STHADL) / (STHADH − STHADL) × 100 %`, `0x0171`–`0x0174` second-throttle
  target/ADLL/ADHH/step, `0x0185` purge duty, `0x0500`–`0x0510` high-rev counters.
- **Routines:** `0x0102` "CheckCodingChecksum — Program" and `0x0104`
  "CheckCodingChecksum — Data". That is the ECU's *own* view of its checksums,
  reachable over K-Line: a read-only way to ask whether a calibration is
  internally consistent without touching it.
- **Access:** the security-access code was obtained by brute force and is a
  separate, supplier-specific secret. Reading data needs it on some paths; this
  project would not ship it, and would not need it for the read-only decoders.

**What that means for us:** the decoder side of KMSK16 is well-evidenced (frame
format, service set, a 20-entry data-id table with formulas). The *programming*
side is not, and the read path may need security access. A KMSK16 panel is a
realistic Batch-5 candidate **as a K-Line capture decoder only**, using the same
"paste a frame, get a candidate" shape as the Kawasaki and Triumph panels.

**Shipped** as `#ktmKmsk16` and `#husqvarnaKmsk16`, with the full table worked up
from the job description itself: 51 identifiers, four places where that source
contradicts itself, and no derived number where it does. The detail lives in
[KMSK16 on K-Line](KMSK16_KLINE.md); two corrections to the summary above:

- `0x0140`–`0x0149` are **not** "lambda heater references". `0x0140` is the
  throttle flap angle reference (THREF); only `0x0142`, `0x0143` and `0x0149` are
  lambda adaptions.
- the table is 51 entries, not 20, and the over-rev counters run `0x0502`–`0x0509`
  and then jump to `0x0510` — a computed range would have invented six
  identifiers that do not exist.

### 4.2 Decoders already shipped, and the evidence behind them

| Decoder | Evidence | Status |
| --- | --- | --- |
| Kawasaki KDS (ER-6n) | `iKawa` (MIT), pinned in `LICENSES/` | shipped, [brand tools](BRAND_TOOLS.md) |
| Suzuki SDS (SV650AK7) | `SV650overlay` (GPL-3.0) | shipped; source uses one byte for rpm |
| Triumph ISO 9141 | `daytona-kline` (GPL-3.0-or-later) | shipped; one author, one bike |
| BMW 11-bit CAN | `EasierCan` (MIT) | shipped; direction not recorded in source |
| Ducati Panigale CAN | `DucatiPanigaleCanBus` (MIT) | shipped |
| Indian J1939 | `indian-thunderstroke-canbus` (MIT) | shipped; PGN + source address keyed |
| Honda PGM-FI / CBR600RR | pinned forks + `HONDA_RESEARCH_*` tables | shipped, research-only |
| KTM / Husqvarna KMSK16 | `gobftald/CCM450-diag` @ `43104d2` (no licence; facts reimplemented) | shipped, capture-only, [KMSK16 on K-Line](KMSK16_KLINE.md) |
| Harley J1850 / Delphi CAN | `HarleyDroid`, `vpw-sniffer` | shipped |

### 4.3 Gaps, with what is missing for each

| Decoder | What exists | What is missing |
| --- | --- | --- |
| Zero / Energica EV | Zero SR/S DBC defines `SoC_Percentage` on `0x253` with remaining-charge time; the repo has **no licence** | Re-derive from a user-supplied DBC (the DBC importer already reads one) rather than bundling theirs |
| CFMoto MSE6/MSE8 | Record structure and CRC parameters (above) | Which live-data identifiers the ECU answers; the checksum work is the solid half |
| KTM/Husqvarna KMSK16 | Frame format, service set, data-id table (4.1) | Programming sequence, and whether security access is required for `0x22` on every model year |
| Royal Enfield 650 | OBD-II PID reading list (already in the OBD explorer) | The Hunter 350 keyed checksum: no public derivation, treat as blocked |
| IAW 7SM / MIU G3 | XDF titles that declare checksums; region sizes in the catalog | The algorithm, and any confirmed region geometry for 7SM/MIU |
| Energica | Frames referenced in third-party DBCs | Licence and confirmation |

## 5. What we would build from this, and in what order

1. **Checksum workbench — verification first** (`#1` in the research list). The
   eight confirmed families above are sums and CRC-32s with stated init/xorout,
   and MSE6.0 shows how to find records without hardcoding offsets. A read-only
   "verify, don't repair" version is honest and useful: load an image, get *which
   family recognises it* and *which records disagree*. Repair stays behind the
   existing backup-attestation flow, and the panel says what MSE6.0 taught us —
   a factory file can fail.
2. **KMSK16 capture decoder** — *shipped, see
   [KMSK16 on K-Line](KMSK16_KLINE.md)*. A brand panel in the Batch-3 shape:
   K-Line frames in, named data ids out, with the "candidate" language the other
   brand panels use, plus an explicit stated/inferred split and the source's own
   contradictions kept visible.
3. **Structure finder** for unknown images (the MSE6 record-scan idea
   generalised: complement pairs, `[start][end]` pairs, repeated rows).

Everything else stays where it is until someone finds evidence: a keyed
checksum that cannot be derived is not a feature waiting for an implementation,
it is a wall.

## 6. Sources, with what each one is trusted for

| Source | Pin | Licence | Trusted for |
| --- | --- | --- | --- |
| `NetworkDir/moto-ecu-checksum` | `43ccc5f3663e` | MIT declared in README, no LICENSE file | The eight checksum parameter sets, their confirmation status, and the MSE6 record-discovery reasoning |
| `gobftald/CCM450-diag` | `43104d2cfca9` | see repo LICENSE | KMSK16 KWP framing, 10,400 baud, service ids, data-id table, routine ids, the EDIABAS job text |
| `fpoussin/MotoLink` | `7879a8567dd4` | GPL-3.0 | The MotoLink tune-file XML structure now parsed by the tune diff |
| This repository | `HEAD` | AGPL-3.0-only | Frame checksums, IAW upload encoding, Honda research offsets, the plugin policy |

Two cautions about these sources, stated plainly:

- `moto-ecu-checksum` has **no licence file**. Its README says MIT; until that
  is confirmed by the author, treat everything taken from it as *facts to
  reimplement with attribution*, not code to copy. That is what this document
  records.
- Every confirmation in it is either "the factory image verifies" or "matches a
  commercial tool byte for byte". Both are strong, and neither proves the ECU
  will accept a modified file — the 450SR case is the counter-example.

## 7. Tests and where this document is checked

Nothing here ships code, so there is nothing to unit-test; what *is* checked is
that the claims this document makes about the repository stay true:

- `tests/test_help_module.py` — every panel mentioned here exists and has a help
  entry.
- `tests/test_brand_tools_panels.py` — the Indian PGN/source-address table and
  the Ducati identifier list still match their Python modules.
- `tests/test_bench_calculators.py` — the constants the calculators document are
  the constants the code uses.

When a family from §2 is implemented, it gets a known-answer test built from a
synthetic image constructed to satisfy that family, plus — where a real factory
image can be obtained lawfully — a verification-only test against it.
