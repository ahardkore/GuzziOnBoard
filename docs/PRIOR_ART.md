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
  era. Not obtainable for us, but any workshop capture of a PADS session on a
  V7 850 / V85 would settle the CAN identifier question instantly; worth
  asking around the forums for exactly that capture.

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
| 2 | CAN IDs 0x7E0/0x7E8 unconfirmed | GuzziCanDiag + SavvyCAN (§2, §4) | passive-sniff a GuzziCanDiag↔V7 850/V85 session; also test 29-bit `0x18DA10F1`/`0x18DAF110` | catalog `can_ids` flips from `inferred`; simulator speaks the same IDs. **Software half landed:** the pair is now a per-session setting (catalog default ← vehicle override ← operator), 29-bit accepted, exposed in the Garage UI; only the capture remains. **Capture analyser landed** (`guzzionboard/canlog.py`, Discovery view): paste or point it at a candump / SavvyCAN CSV / CRTD sniff of a GuzziCanDiag session and it reports the pair with its evidence — flow-control answering a first frame, service ids, tester-present cadence, padding — and whether it is either standard pair |
| 3 | Only 5AM has characterised identifiers | GuzziDiag + IAWDiag captures (§2), TuneECU (§5) | serial-tap the closed tools against bench ECUs, decode into catalog | 15RC / MIU G3 / 7SM identifier tables at `documented`+ |
| 4 | Transports never met a bike | aster94 lib, RPMSensorEmu, AdapterTest (§4, §6) | diff timing against aster94; bench ECU + wheel emulator; port-permission preflight vs AdapterTest | one full identify + live-data session per transport on real hardware. **Software half for CAN landed:** the `cansim` transport runs the full ISO-TP path (segmentation, flow control, reassembly, the `CanConnection` code itself) against the simulated ECU over a python-can virtual bus, with the catalog/vehicle/operator id overrides in force. Open until a capture settles it: this project carries KWP K-Line-framed messages inside ISO-TP, while the ISO 15765-3 convention strips the framing — the first real CAN capture decides, and the §7-item-2 analyser already expects the stripped convention |
| 5 | Write path unproven (5AM) | 5am_util (§1.2, §1.3) | adopt write sequence + encoder into firmware/programming, simulator-tested first | a sacrificial 5AM is read, written with its own dump, read back equal |
| 6 | No map-level view of dumps | XDF library (§3) | ~~XDF parser + map diff in firmware.py~~ **Done** — shipped as the standalone `guzzionboard/maps.py` (parser, render, named diff; `GET /api/maps`, `/api/maps/render`, `/api/maps/diff`; "Maps & tables" panel in the UI) | a 5AM dump renders named fuel/ignition tables |

Items 1 and 6 are pure software and can land without hardware. Items 2–5
need a bench: one ECU per family of interest, a KKL adapter, an STN or
ELM327-class CAN adapter, and ideally the phonic-wheel emulator.
Item 6 landed: the parser is grounded on a real TunerPro v5 XDF (§3), and
XDFs are user-supplied at runtime from `~/.guzzionboard/xdfs/` because none
of the Guzzi files may be redistributed with this repo.
Item 2's software half landed with it (see the table). Cross-brand coverage
(Ducati P8/15M/16M/59M/5AM, Aprilia 16M/5AM/7SM) is in the catalog at
`inferred`/`unknown` — model→ECU mappings from the GuzziTek master list
(guzzitek.org/documents/injection/ECU_MasterList_2011.pdf), the Ducati.ms
model/ECU list and tuneecu.net; identifier captures on those bikes are the
promotion path. Known but deliberately unmodelled for now: Aprilia 5DM
(Shiver/Dorsoduro 750) and 5SM (RSV4 R), and Ducati's Siemens era
(696/796/1100).

---

## Sources

- `5am_util` source, `main.c` / `util.c` —
  <https://github.com/denandz/5am_util> (fetched and transcribed 2026-10;
  key algorithm and write path verified against the README transcript pairs)
- GuzziDiag / IAWDiag / GuzziCanDiag download page and changelogs —
  <https://www.von-der-salierburg.de/download/GuzziDiag/>
- IAWDiag ecosystem overview —
  <https://www.ducati.ms/threads/magneti-marelli-ecu-access-with-iawdiag-and-using-tunerpro.745787/>
- GuzziDiag beginner tutorial —
  <https://www.thisoldtractor.com/moto_guzzi_quota_guzzidiag_howto_-_a_tutorial_for_beginners.html>
- aster94/Keyword-Protocol-2000, python-udsoncan, python-isotp,
  slava-fm/moto-service-tool, rnd-ash/OpenVehicleDiag, cedricp/ddt4all,
  collin82/SavvyCAN — see §4 links
