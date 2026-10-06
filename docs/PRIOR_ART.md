# Prior art — diagnostic programs that de-risk this package

What "successful" means for GuzziOnBoard, in terms of the four open gaps in
`docs/PROTOCOL_NOTES.md`, is simple: a verified SecurityAccess key, confirmed
CAN identifiers for the CAN-era families, per-family local-identifier tables
beyond the 5AM, and transports that have actually talked to a bike. Every one
of those gaps has already been solved by someone else's software. This
document is the map: which program closes which gap, what to take from it, and
what "done" looks like.

Confidence vocabulary is the same as everywhere else in this project
(`docs/PROTOCOL_NOTES.md`). Nothing here promotes a family's catalog entry by
itself; that happens when the data lands in `guzzionboard/catalog/`.

---

## 1. `5am_util` — the headline find

<https://github.com/denandz/5am_util> (C, single-purpose; Codeberg mirror at
<https://codeberg.org/DoI/5am_util>)

A firmware reader/writer for Marelli IAW 5AM ECUs (Ducati 848/1098/1198
factory fit; the same family is on Moto Guzzi CARC models). KWP2000 over a
plain USB KKL 409.1 adapter, no special hardware.

Until now this project only had the *transcript* from the 5am_util README —
two seed/key pairs, the read sequence, the region geometry. **The source code
contains the entire write path and the working key algorithm.** Everything
below is extracted from `main.c` and cross-checked.

### 1.1 SecurityAccess key algorithm (verified)

`calc_key()` in `main.c`, ported to Python. Reproduces **both** published
pairs exactly:

```python
def iaw5am_key(seed: bytes) -> bytes:
    """IAW 5AM SecurityAccess. seed = 4 big-endian bytes from service 27 01.

    The C original builds challenge = b0<<24|b1<<16|b2<<8|b3, then reads it
    as two little-endian uint16s:  q0 = b3 | b2<<8,  q1 = b1 | b0<<8.
    """
    b0, b1, b2, b3 = seed
    q0 = b3 | (b2 << 8)
    q1 = b1 | (b0 << 8)
    w = ((q0 >> 8) | (q0 << 8)) & 0xFFFF     # byteswap
    k1 = (w // 0xA1) & 0xFF                  # div 161
    k2 = (q1 % 0xC8) & 0xFF                  # mod 200
    return bytes([k1, k2, 0x69, 0x27])
```

| Seed | Key (algorithm) | Key (published) |
|---|---|---|
| `27 88 27 89` | `DA 78 69 27` | `DA 78 69 27` |
| `3C A9 3C AA` | `0E 81 69 27` | `0E 81 69 27` |

In seed terms (seed = 16-bit `X` followed by `X+1`):
`key = (bswap16(X+1) div 161) << 24 | (bswap16(X) mod 200) << 16 | 0x6927`.

This retires the `iaw5am-affine-hypothesis` in `guzzionboard/security.py` —
the real function is not affine, so the fitted line agrees with the two
samples and diverges everywhere else. Honest confidence level: **documented**
(mature open-source tool, reproduced against both its own published pairs) —
not `verified-bench` until someone feeds a real Guzzi 5AM a seed and this
function's answer unlocks it. The algorithm is expected to be shared by the
59M (IAW5xWriter covers both), and is *not* assumed to hold for 7SM, MIU G3 or
the CAN families.

### 1.2 The write path (complete, from source)

The catalog's 5AM write spec is `inferred` today ("the transcript only covers
reads"). The source supplies the full sequence, byte for byte:

```
10 85                     start diagnostic session (10400 baud)
-- switch to 38400 --
83 03 1E 02 0A 14 00      access timing parameters (P2/P3/P4)
27 01 / 27 02 <key>       SecurityAccess (see 1.1)
-- MANDATORY or RequestDownload fails: --
10 F1 3B 98 20            write "writer" identification (GuzziDiag sends
                          its TesterCode, e.g. WLoad1039T — cross-checks the
                          note already in docs/PROGRAMMING.md)
10 F1 3B 99 20 <date>     write reflash date (5am_util sends 20180101)
10 F1 31 02 00 40 00 04 FF FF   call erase routine (0x02)
10 F1 33 02               execute erase  (then ~10 s wait, responses drained)
10 F1 34 00 40 00 33 04 C0 00   RequestDownload (region 0x4000, 0x4C000)
10 F1 36 <len+1> <data>   TransferData, 254-byte payload chunks
10 F1 37                  RequestTransferExit
10 F1 31 01 00 40 00 04 FF FF <cksum16>   call program routine (0x01)
10 F1 33 01               execute program
```

All of this from source address `0x01` (after `10 85`), consistent with what
the transcript showed for reads.

### 1.3 The firmware "encryption"

The uploaded image is not the plain dump. `encrypt_blob()` in `main.c`:

- payload = image bytes `0x4000..0x4C008` (311 296 bytes — matches the flash
  region in our catalog);
- prepend the 8-byte magic `C2 07 16 33 6F EB B0 1D`;
- then per-byte transform with an 8-byte period (index `i = offset mod 8`):

| i | add | rotate | invert |
|---|---|---|---|
| 0 | +0x88 | ror 1 | yes |
| 1 | +0xC7 | ror 1 | — |
| 2 | +0x26 | ror 3 | yes |
| 3 | +0xA5 | ror 5 | yes |
| 4 | +0x6C | ror 2 | — |
| 5 | +0xEB | ror 6 | — |
| 6 | +0x0A | ror 6 | yes |
| 7 | 0x66−b | ror 4 | — |

The program routine's argument is a `checksum16` (sum of bytes) over
`image[0x4000 : 0x4000+0x4BFFE]`. **`guzzionboard/firmware.py` currently only
*detects* encrypted containers; it has no encoder. A write feature for the 5AM
needs this.**

### 1.4 Read-path details worth keeping

- Read runs at **64200 baud** after login (write at 38400) — arbitrary baud is
  done with `termios2`/`BOTHER`; pyserial accepts these rates on Linux.
- Login (27) happens before download on the read path too.
- 20 blocks × 16 KiB = 320 KiB file; blocks 2–5 are *not requested* and are
  filled with `0xFF` (5am_util behaviour on Ducati-fit ECUs — whether Guzzi
  5AMs serve those blocks is untested; our catalog's region data comes from a
  real HW610 dump and disagrees, so treat the 0xFF fill as tool behaviour,
  not ECU geometry).
- Block setup `36 11 00 FE 02 01 <block>`, then `36 21 <off16> 00 20` reads
  32 bytes at a time.

### 1.5 What to do with it

1. ~~Register the key provider (1.1) as `iaw5am-kwp-divmod`, `verified=False`,
   source `5am_util main.c`; retire the affine hypothesis.~~ **Done** —
   `guzzionboard/security.py`.
2. ~~Upgrade the catalog write spec from `inferred` using 1.2.~~ **Done** —
   `guzzionboard/catalog/ecus/5am.json` now carries the whole documented
   sequence as data (write session, records, erase arm/trigger, download,
   254-byte chunks, program arm/trigger with checksum), confidence
   `documented`, with `write_supported: false` still enforced against
   hardware.
3. ~~Add the encoder (1.3) to `firmware.py` with round-trip tests against a
   reference blob.~~ **Done** — `firmware.iaw5am_upload_blob` and friends,
   with known-answer tests generated by compiling the *original C* (see
   `tests/test_firmware.py`), and the simulator ECU enforcing the documented
   sequence end to end (`tests/test_programming.py`).

What remains is hardware: feed the key a real Guzzi-fit 5AM seed, then the
bench write of item 5 in section 7.

---

## 2. The GuzziDiag / IAWDiag suite — the reference implementation

<https://www.von-der-salierburg.de/download/GuzziDiag/> (free, closed source;
MD5s published per download; changelogs are public documentation)

This is the toolchain that has read and written these ECUs for a decade. It
covers every K-Line family in our catalog and one CAN-era tool exists
(`GuzziCanDiag` V0.02, using **OBDLink SX or Vgate vLinker FS** — STN-class
adapters; ELM327 "maybe, diag only" — a signal about what a CAN tool needs
beyond a bare ELM327).

| Tool | Version | Families |
|---|---|---|
| GuzziDiag | 0.60/0.61 | live data, TPS reset (K-Line era) |
| IAWDiag | 0.52 | generic: P7, P8, 16M, 15M, 15RC, 15P, 59M, 5AM, 5SM, 5DM, MIU1, 7SM, MIUG3 |
| IAW15xReader/Writer/EEPROMTool | 0.68 / 0.27 / 0.04 | 15M, 15P, 15RC |
| IAW5xReader/Writer, 5AM EEPROMTool | 0.28 / 0.24 / 0.04 | 5AM, 59M |
| IAWMIUG3Reader/Writer/EEPROMTool | 0.05 / 0.06 / 0.02 | MIU G3 |
| IAW7SMReader/Writer/EEPROMTool | 0.03 / 0.08 / 0.01 | 7SM |
| GuzziCanDiag | 0.02 | CAN-era diag (MIU G4 / 11MP era) |
| IAWMIUReader/Writer | 0.01 | MIU1 (tested on a Vespa GTS 300) |
| IAWMBC1Reader | 0.01 | MBC1 (BMW C600) |
| ManaTCU | 1.03 | Mana gearbox TCU |

What to take from the suite:

- **Existence proofs.** Reader+Writer exists for every K-Line family we
  catalog. So the read *and* write protocols for 15M/15RC/5AM/59M/MIU G3/7SM
  are all learnable by capture; nothing about these ECUs is fundamentally
  locked.
- **Operational constraints** already mirrored in our docs and worth keeping
  in sync with the changelogs: 7SM read ≈ 30 minutes, FTDI latency timer
  **1 ms is essential**, never flash HW1xx images into HW3xx ECUs (instant
  brick), no VMs, battery charger / headlight fuse for long operations.
  The download page adds: reduce FTDI USB transfer sizes 4096→2048 when
  connections drop; disable screensavers and virus scanners.
- **Model→ECU mapping** via the XDF library (below): V7/V7 II/V7 III/V9 →
  MIU G3; V85TT → 7SM; California 1400 → 7SM; CARC models → 5AM. Direct
  validation data for `catalog/models`.
- **Capture methodology.** The tools are closed, but the wire is not: run a
  Reader against a bench ECU with a serial tap between adapter and PC (a
  second USB-UART in listen mode on the K-Line, or a `socat`/pty interposer
  on Linux logging both directions). Every captured frame is a
  `verified-capture` data point for the catalog. Note from the field: use
  IAW5xReader **V0.26** for captures — V0.27/V0.28 have a known connection
  bug.

---

## 3. TunerPro + XDF files — map layouts for every family

TunerPro (<https://www.tunerpro.com/>) is the bin editor the GuzziDiag
ecosystem standardised on, and von-der-salierburg hosts XDF (map definition)
files for **P7, P8, 16M, 15M, 15RC, 5AM (one- and two-lambda), MIU G3 (V7, V7
II, V7 III, V9), 7SM (V85TT, California 1400, MGX21)**, plus Aprilia, BMW,
Ducati, Morini and others.

Each XDF names every table in the bin — fuel and ignition maps, lambda
targets, throttle maps, corrections — with addresses and scaling. For us that
is: ground truth for `firmware.py`'s future map-diff view, and a per-family
sanity check that a dump is the right image for the right bike. The XDFs are
plain XML; a parser is an afternoon, not a project.

**Parser notes (captured from a real TunerPro v5 file, `XDFFORMAT 1.60`,
because the Guzzi XDF zip could not be downloaded from the sandbox):**

- The MATH `equation` is an *attribute* of `<MATH>`, e.g.
  `<MATH equation="X/45.5">`. Only value-only equations (a bare `X` plus
  arithmetic) are interpreted; per-cell or address-linked `<VAR
  type="address">` equations are reported unsupported, never guessed.
- `EMBEDDEDDATA mmedtypeflags & 0x1` marks signed data, overriding
  `DEFAULTS signed`; `DEFAULTS lsbfirst` sets endianness (absent/0 =
  big-endian). `mmedcolcount` may be omitted for 2D tables; the axis
  `indexcount` wins. Strides are in *bits*; zero means contiguous.
- `BASEOFFSET`: bin offset = address + offset, or address − offset when
  `subtract="1"`. Separately, the 5AM XDFs address the full 0x50000 device
  while a flash read returns the 0x4C000 region from device 0x4000 —
  `maps.py` auto-detects that shift and reports the base it used.
- `CATEGORY index` is hex, `CATEGORYMEM category` is decimal (0xA ↔ 10).
- XDF checksum plugins are GM-specific GUID records; informational only.

---

## 4. Open-source protocol stacks to mine for the transports

Our KWP2000/ISO-TP layers are unit-tested but have never met a vehicle. These
projects have met vehicles:

| Project | What it is | What we take |
|---|---|---|
| [`aster94/Keyword-Protocol-2000`](https://github.com/aster94/Keyword-Protocol-2000) | Arduino KWP2000 client, tested on Suzuki/Kawasaki/Yamaha/Honda | real-bike K-Line init timing, 5-baud slow init edge cases, pacing constants; diff against our `kline.py` before first contact |
| [`python-udsoncan`](https://github.com/pylessard/python-udsoncan) + [`python-isotp`](https://github.com/pylessard/python-isotp) | the canonical Python UDS + ISO-TP stack | oracle for our `protocol/isotp.py`: run both against the same frames in CI; UDS semantics (NRC handling, `responsePending`) for the CAN families |
| [`slava-fm/moto-service-tool`](https://github.com/slava-fm/moto-service-tool) | Swift, ELM327-based UDS/KWP tool for a modern Ducati (Panigale V2), incl. service reset | the closest published analogue to our MIU G4 / 11MP problem: modern CAN motorcycle, ELM327-class adapter, UDS over ISO-TP — see its adapter quirks and service-reset sequences |
| [`rnd-ash/OpenVehicleDiag`](https://github.com/rnd-ash/OpenVehicleDiag) | Rust diagnostic platform, J2534 + SocketCAN, UDS/KWP2000 | architecture reference (server/job/UI separation mirrors ours); their session handling for UDS over CAN |
| [`cedricp/ddt4all`](https://github.com/cedricp/ddt4all) | Renault/Nissan DDT tool, huge ECU parameter databases | the "everything is data" pattern our catalog follows, at scale; their JSON parameter format is a good template if our identifier tables grow request semantics |
| [`collin82/SavvyCAN`](https://github.com/collin82/SavvyCAN) | CAN capture/replay | the instrument for gap #2 below |

Not everything J2534-adjacent matters to us (jakka351/OpenJ2534 is only
relevant if pass-thru hardware support is ever wanted).

---

## 5. Neighbouring closed tools worth watching

- **TuneECU** (<https://www.tuneecu.com>) — supports 5AM HW610 among others
  (Aprilia/Ducati/Guzzi world); its published ECU and PID lists are a second
  source to cross-check our 5AM identifier table, and its newer CAN support
  is a hint about what the CAN-era protocols look like on sibling brands.
- **jpdiag / M3C / Melcodiag** (Ducati.ms community, same lineage as
  IAWDiag) — Siemens M3C and Mitsubishi Melco ECUs; useful mainly because
  the [Ducati.ms IAWDiag thread](https://www.ducati.ms/threads/magneti-marelli-ecu-access-with-iawdiag-and-using-tunerpro.745787/)
  is the best English-language documentation hub for the whole toolchain
  family, including which reader versions work.
- **Piaggio PADS + MDI-3** (dealer tooling) — the official path for the CAN
  era. Public material proves feature existence but does not disclose the
  identifier or application layer. Recovering that evidence is a project-side
  archival or controlled-bench task; the workstation does not ask a customer
  to probe an unknown ECU and keeps these physical profiles blocked.

---

## 6. Bench and validation utilities (same source as §2)

- **RPMSensorEmu V0.17** — emulates the phonic wheel so an ECU "runs" on the
  desk. This is the missing half of our test story: SimulatorTransport
  exercises our code, an RPMSensorEmu-fed bench ECU exercises our transports
  against real silicon without a motorcycle.
- **AdapterTest V1.01** — interface pre-flight; a direct functional
  comparison target for our `adapter.py` (FTDI latency, permissions, echo
  test).
- **GearSpeed V1.55** — gearing/speed calculator; parity target for
  `tools.py`'s gearing math (same inputs, same answers).

---

## 7. The plan this implies

| # | Gap (from PROTOCOL_NOTES) | Program | Action | Done when |
|---|---|---|---|---|
| 1 | No verified SecurityAccess key | 5am_util (§1.1) | register `iaw5am-kwp-divmod`, retire affine hypothesis | provider ships, one bench unlock on a real 5AM promotes it to `verified` |
| 2 | MIU G4 / 11MP CAN transport and application are unpublished | Service/commercial records, GuzziCanDiag + SavvyCAN (§2, §4) | Continue project-owned archive research or controlled maintainer bench capture; do not probe a customer bike | A reproducible family-specific capture or primary definition establishes bitrate, IDs, addressing, transport, session, and payloads. Until then the profiles have no CAN defaults or capabilities and fail before transport construction. The offline capture analyser remains available for existing research logs. |
| 3 | Most non-5AM application identifiers remain incomplete | OEM MIU G3 tables, IAW Scan 2, ScanST, GuzziDiag/IAWDiag records | Preserve only values established by a primary definition, source, or reproducible session; keep the rest unavailable | 16M now has evidence-bounded read-only support and 7SM has captured identity only. MIU G3's OEM RLI names remain non-executable raw research metadata; 15M, 15RC, 59M, P8 and the remaining families expose no guessed operations. |
| 4 | Physical transports have not met project-controlled hardware | aster94 lib, RPMSensorEmu, AdapterTest (§4, §6) | Diff timing against prior art, then use maintainer-owned bench ECUs and a wheel emulator | One full evidence-preserving session per enabled family on controlled hardware. `cansim` validates generic ISO-TP mechanics only and makes no claim about a Piaggio CAN application. |
| 5 | Write path unproven (5AM) | 5am_util (§1.2, §1.3) | adopt write sequence + encoder into firmware/programming, simulator-tested first | a sacrificial 5AM is read, written with its own dump, read back equal |
| 6 | No map-level view of dumps | XDF library (§3) | ~~XDF parser + map diff in firmware.py~~ **Done** — shipped as the standalone `guzzionboard/maps.py` (parser, render, named diff; `GET /api/maps`, `/api/maps/render`, `/api/maps/diff`; "Maps & tables" panel in the UI) | a 5AM dump renders named fuel/ignition tables |

Items 1 and 6 are pure software and can land without hardware. Remaining
bench work belongs to the project's maintainers: one controlled ECU per family
of interest, an appropriate adapter, and ideally the phonic-wheel emulator.
No unsupported profile is turned into a customer protocol experiment.
Item 6 landed: the parser is grounded on a real TunerPro v5 XDF (§3), and the
repository now includes a provenance-tracked XDF library while still allowing
local overrides from `~/.guzzionboard/xdfs/`.
Cross-brand fitments (Ducati P8/15M/16M/59M/5AM, Aprilia 16M/5AM/7SM) remain
`inferred`/`unknown`: model-to-ECU compatibility does not promote application
bytes established on another make. Known but deliberately unmodelled for now:
Aprilia 5DM (Shiver/Dorsoduro 750) and 5SM (RSV4 R), and Ducati's Siemens era
(696/796/1100).

---

## 8. The other families: what can be found, and what can only be captured

Asked whether the identifier tables for 15M, 15RC, 16M, 59M, 7SM, MIU G3,
MIU G4, P8 and 11MP can be found "the same way we did 5AM", the honest
answer has two halves.

**They cannot be found, because the 5AM table was not found either.** §5 of
`PROTOCOL_NOTES.md` is a record of a wire tap: 0x30–0x7F read off a live bus
while a tool talked to a bike, with the 38 slots that answered with zeroes
marked dead. No public document publishes a per-family local-identifier
table for any of these ECUs. The tables exist in two places only — compiled
into the closed GuzziDiag/IAWDiag binaries, and on the K-Line of a running
motorcycle. Searching produced no third place. Anything written into a
catalog from a forum post or an analogy with 5AM would be an assertion
wearing a measurement's clothes, which is exactly what this project refuses
to do.

**What the published changelogs do settle** is a layer above the
identifiers: which values each family has at all, how they behave, and which
of them the closed tool had to correct. That is real, citable, and it tells
a capture what to look for. From the GuzziDiag (V0.61) and IAWDiag (V0.52)
changelogs:

| Family | Established from the changelogs |
| --- | --- |
| 5AM | Fast init only — slow init was removed as unsupported. Service reset is done from the dashboard, not the tool. TPS-Reset does not apply with the PF3C throttle body. The stepper test requires the engine running. Has dwell, lambda-2 state, lambda status, corrected injection timing, integrator and lambda mV. Injectors 3 and 4 exist as actuators. |
| 15M | The only family with a usable CO-Trim, and only above 80 °C coolant (the threshold was raised twice). |
| 15RC | Lambda is reported in mV. "Partial load", "idle speed" and "rich multiplier" are **signed**. CO-Trim is only meaningful with lambda control off. PF3C shows raw throttle only; PF1C shows corrected throttle only. |
| 16M | CO-Trim is impossible on the original firmware. Error "unknown 03" is the right injector. The two injector actuators were swapped in the tool for years. |
| 59M | Has CO-Trim. Shares the tip-over sensor state encoding with 5AM (both were corrected together). |
| P7 / P8 | **No stored faults at all** — nothing to read, nothing to clear. P8's "unknown 12" and "unknown 13" are one 16-bit integer (observed 16000–49536); "unknown 14" is a flag byte; "unknown 0B" is the CO trimmer. P7 reports rpm at half scale. |
| 7SM | Front-wheel speed, throttle self-learning, exhaust-valve zero and self-learn, track-counter reset. |
| MIU G3 | TPS-reset, stepper test, corrected injection time, front-wheel speed. |
| MIU G4, 11MP | **Not covered by GuzziDiag or IAWDiag at all.** There is no closed tool session to tap on these; they are CAN-era and belong to the CAN discovery path in §7, not this one. |

These facts belong in catalog `notes`, not in parameter definitions — they
constrain and sanity-check a capture, they do not substitute for one.

**So the method is the deliverable.** `guzzionboard/klinelog.py` is the 5AM
procedure made repeatable by anyone with a bike and the closed tool:

1. Tap the K-Line while GuzziDiag/IAWDiag runs a live-data session.
2. Have that tool write its own CSV log over the same minutes.
3. `POST /api/tools/klinelog` (or the K-Line panel in Discovery) pairs every
   `21 <rli>` with its answer, reports what each identifier did, and solves
   each named CSV column against the raw series by least squares — including
   the signed reading, which is how 15RC's signed values will be settled.
4. A channel whose straight line fits to r² ≥ 0.999 comes out as
   `verified-capture` with its scale, bias and the fit that earned it.
   Everything else comes out as `unknown` or as a dead slot. Nothing is
   written to the catalog automatically.

A capture that never revs the engine solves nothing, and the tool says so
rather than fitting a constant.

---

## 9. Is GuzziDiag open source? (GitHub survey, 2026-10)

Asked directly, and searched directly. **No.** GuzziDiag, IAWDiag and
GuzziCanDiag are freeware binaries from von-der-salierburg.de; no source has
ever been published. A GitHub-wide search for the tools returns exactly one
repository, `MerrimanInd/guzzidiag-nix` — a Nix flake that *packages the
closed binary*, nothing more. So §8 stands: the per-family identifier tables
are not reachable by reading somebody's source.

The search was still worth doing, because the neighbours are real:

| Repository | Licence | What it is worth |
| --- | --- | --- |
| [`Vasiy/onboard-logger`](https://github.com/Vasiy/onboard-logger) | MIT | **Already the source of our 5AM table.** A NanoPi K-Line logger for an IAW 5AM HW610 with a `config/params.json` map, an actuator list, status maps and — most usefully — a *full `0x00`–`0xFF` identifier scan* with event markers (flip the side stand, mark the log, see which rli moved). That is the same method `klinelog.py` automates, from the other end: it sweeps the bike, we decode a tap of someone else's tool. Re-synced this session (see below). |
| [`intilinux-eng/iaw-scan-3`](https://github.com/intilinux-eng/iaw-scan-3) | NOASSERTION | A maintained .NET/Avalonia fork of IAW Scan 2, the Fiat/Lancia/Alfa Marelli IAW tool, with ECU definitions in source. Car IAW families, not the bike ones, but it is an open implementation of the same vendor's diagnostic dialect — useful for session handling and actuator framing, not for our identifier tables. Unclear licence: read, do not copy. |
| [`trainer400/IAW5AF_EEPROM`](https://github.com/trainer400/IAW5AF_EEPROM), [`lozziboy/IAW_4AF_keylock_remover`](https://github.com/lozziboy/IAW_4AF_keylock_remover) | — | IAW EEPROM access on car ECUs; background for the memory path. |
| [`andreibaw/Honda_K-Line_KWP2000`](https://github.com/andreibaw/Honda_K-Line_KWP2000) | — | An independent motorcycle KWP2000 implementation worth comparing init timings against. |

### What the re-sync changed

Our 5AM table was transcribed from `onboard-logger` some time ago and had
drifted. Reconciled against its current map: 33 scalings agree exactly, and

- `0x60` barometric pressure (mbar) added — upstream `known`, so
  `verified-capture`;
- `0x3D` CO trim, `0x74` and `0x77` added as `inferred` — upstream `check`,
  meaning named but not proven on a bike. The GuzziDiag changelog says CO
  trim is not usable on 5AM, so that reading is carried as a stored number,
  not an adjustment;
- `0x4A` / `0x4C` promoted out of `dead` to `inferred` rear-bank lambda flags,
  with the disagreement recorded (see `PROTOCOL_NOTES.md` §5);
- the dead-slot count corrected from 38 to 40, now listed slot by slot
  instead of counted.

The lesson for the catalog is the one this project keeps relearning: there is
one upstream capture behind the only characterised family we have, so
"corroborated by two sources" has to be checked, not assumed — these two were
the same source.

---

## Sources

- `5am_util` source, `main.c` / `util.c` —
  <https://github.com/denandz/5am_util> (fetched and transcribed 2026-10;
  key algorithm and write path verified against the README transcript pairs)
- GuzziDiag / IAWDiag / GuzziCanDiag download page and changelogs —
  <https://www.von-der-salierburg.de/download/GuzziDiag/>; the per-family
  facts in §8 are from
  <https://www.von-der-salierburg.de/download/GuzziDiag/GuzziDiag_Changelog.txt>
  (V0.61, 2026.06.07) and
  <https://www.von-der-salierburg.de/download/GuzziDiag/IAWDiag_Changelog.txt>
  (V0.52, 2023.05.30), both fetched 2026-10
- IAWDiag ecosystem overview —
  <https://www.ducati.ms/threads/magneti-marelli-ecu-access-with-iawdiag-and-using-tunerpro.745787/>
- GuzziDiag beginner tutorial —
  <https://www.thisoldtractor.com/moto_guzzi_quota_guzzidiag_howto_-_a_tutorial_for_beginners.html>
- GitHub survey of the IAW/Guzzi ecosystem (§9) — Vasiy/onboard-logger,
  intilinux-eng/iaw-scan-3, MerrimanInd/guzzidiag-nix, trainer400/IAW5AF_EEPROM,
  andreibaw/Honda_K-Line_KWP2000 (searched 2026-10)
- aster94/Keyword-Protocol-2000, python-udsoncan, python-isotp,
  slava-fm/moto-service-tool, rnd-ash/OpenVehicleDiag, cedricp/ddt4all,
  collin82/SavvyCAN — see §4 links
