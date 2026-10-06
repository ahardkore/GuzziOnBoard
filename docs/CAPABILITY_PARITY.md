# Capability parity with the reference-tool ecosystem

`vendor/guzzidiag/tools/` mirrors the application side of the GuzziDiag
archive byte-for-byte (hashes in `vendor/guzzidiag/MANIFEST.json`). Each one
is a single Windows binary; capabilities below are evidenced by the strings
inside those binaries, the project's wire-level grounding in
`docs/PROTOCOL_NOTES.md`, and — for GuzziOnBoard's side — what the test
suite and a scripted end-to-end session prove (`scripts/e2e_smoke.py`,
370 pytest tests).

Status legend:

- **parity+E2E** — implemented and exercised end to end in this repo
  (simulator speaks the real wire protocol; the same code runs on hardware).
- **covered** — implemented; the same capability exists, sometimes grounded
  in documentation rather than a bench capture.
- **gated** — implemented but deliberately withheld in the shipped build
  until the named condition is met.
- **out of scope** — GuzziOnBoard does not aim to replace this; noted for
  completeness.

## Diagnostic applications

| App | What it provides | GuzziOnBoard | Status |
|---|---|---|---|
| GuzziDiag V0.61 | K-Line diagnostics: ECU identification, live data, DTC read/clear, actuator tests, TPS reset, adaptation resets (strings: TPS, Lambda, Coil, RPM, MAP, ABS, pump, Dash, CAN Bus, live, EEPROM) | `get_identify` / `get_live` / `get_dtcs` / `dtcs/clear` / `actuators` / `routines`; DTC clear and actuators behind the safety gate + single-use tokens (stricter than the reference, by design) | **parity+E2E** — scripted session: identify fields (Hardware `IAW5AMHW610`, Software, Drawing), 11 live channels with raw bytes kept, a sim-injected fault decoded as `P0130 Lambda sensor circuit, bank 1`, 17 actuators catalogued; clear refused without token |
| IAWDiag V0.52 | Same diagnostic core for the injected-car side (same binary family; strings: EEPROM, Lambda, live, TPS, RPM, Coil) | Same code path as above; catalog resolves car-side Marelli variants too | **parity+E2E** (same path) |
| GuzziCanDiag V0.02 | CAN-era diagnostics | Generic CAN/ISO-TP transport, explicitly virtual rehearsal, and offline analysis of existing captures | **research tooling only** — MIU G4/11MP bitrate, identifiers, addressing, transport, and application remain unvalidated; no defaults or physical capabilities are exposed |

## Memory (flash / EEPROM) tooling

| App | What it provides | GuzziOnBoard | Status |
|---|---|---|---|
| IAW5xReader V0.28 | 5AM/59M flash dump → `.bin`, baud switch, checksum cross-check of the download (strings: "Baudrate switched", "downloading...", "Checksum over download:", "Checksum cross checked!") | `memory/read`, `memory/backup`: two reads kept only if byte-identical — the same cheap honesty the checksum cross-check provides, one level stronger | **parity+E2E** — scripted two-read verified backup of the simulated 5AM flash completes over HTTP |
| IAW5xWriter V0.24 | 5AM/59M flash write | erase/RequestDownload/TransferData/verify with read-back comparison and interrupted-write checkpoints | **parity on the simulator; gated on hardware** — the complete flash round trip (two-read backup → sidecar-provenanced validate → opt-in → token → write → read-back verify, 311 296 bytes, sha256 match) runs against the simulated ECU over the same HTTP the UI drives, so the entire writer flow is exercisable from the browser with no hardware; on a real 5AM the token is still withheld (`IAW 5AM does not declare 'memory_write'`) — the capability overlay is session-scoped and the catalogue never changes. 5am_util's sequence and its `calc_key()` are transcribed and proven against the published seed/key pairs |
| IAW15xReader/Writer, IAW7SMReader/Writer, IAWMIUReader/Writer, IAWMIUG3Reader/Writer, IAWMBC1Reader | Flash R/W for 15M/15RC, 7SM, MIU G1, MIU G3, BMW MBC1 | Same memory stack; per-family programming definitions pending wire captures | **gated** — region geometry/key algorithms for these families are not captured yet; the catalog says so honestly instead of guessing |
| IAW15xEEPROMTool, IAW5AMEEPROMTool, IAW7SMEEPROMTool, IAWMIUG3EEPROMTool | EEPROM read/save/load/write, incl. partial writes ("Writing EEPROM succesfull (only 446 bytes possible)") | EEPROM regions readable where geometry is cataloged; 15M/15RC/5AM EEPROM XDFs bundled for rendering EEPROM dumps as named values | **covered** for read+render; EEPROM **write** rides the same hardware-verification gate as flash write |
| ManaTCU V1.03 | Aprilia Mana CVT TCU flashing, EEPROM, live pulley-potentiometer tracks, shift-control actuation (closed-tool existence evidence; raw PADS frames separately establish target `0xEC` and routines `30 02 08` / `30 01 08`) | The Mana's **engine** side is the shared IAW 5AM — `Mana 850` resolves to it and its XDF ships. The separate `mana_tcu` profile records the captured addresses and routine bytes for provenance but exposes no operations: initialization, session/security sequencing, reads, and enforceable mechanical preconditions remain incomplete. | **covered (engine) / evidence-only (TCU)** — physical TCU use fails before the adapter opens; closed-tool strings do not promote a capability |

## Tuning definitions (the TunerPro role)

| App | What it provides | GuzziOnBoard | Status |
|---|---|---|---|
| TunerPro + GuzziDiag XDF archive | Render/diff ECU dumps as named fuel, ignition, limiter tables; the XDF library itself | Firmware → Maps & tables: XDF render + named diff with axis values, and **all 94 cataloged definitions bundled** (3,842 tables, 2,148 constants — every file parse-checked, SHA-256-verified against `PROVENANCE.json`, traceable to the mirrored zip) | **parity+E2E** — scripted render of the session backup through `5AM_GuzziDiag_One_Lambda_V1.41.xdf` returned 133 named tables; the library test re-checks all 94 |

## Support utilities

| App | What it provides | GuzziOnBoard | Status |
|---|---|---|---|
| AdapterTest V1.01 | USB-KKL adapter wiring/driver check, guided clamp hookup (strings: "USB KKL Adapter Test", "connect the red clamp to +12V") | Adapter pre-flight (`get_adapter`) incl. FTDI latency-timer check and 1 ms fix (`post_adapter_latency`), which now also **points Windows users at the mirrored WHQL driver bundle** when no COM port appears | **parity** — the driver part of its job is covered by the CDM row below |
| GearSpeed V1.55 | Gear-ratio / road-speed calculator with a built-in per-model ratio database | the ratio table it ships is vendored verbatim — the 63 entries the binary carries collapse to 58 unique models (five are byte-identical repeats): forty-odd Guzzis from the 1000 G5 to the V85TT plus the Aprilia RSV4, two BMWs and the MV Agusta range — and drives `/api/tools/gearing`; the 🧰 Tools view (preset dropdown, tyre + final-drive inputs, custom-ratio override, rpm range, "above the red line" rows dimmed) is its direct successor, with CSV/JSON log export alongside | **parity** |
| RPMSensorEmu V0.17 | Hardware RPM-signal generator; wheel geometry in its own config files (Guzzi/Ducati/Morini: 46+2 cam; MV Agusta: 22+2 crank), batch ramps `duration\|rpm1\|rpm2` in 100 ms quanta | `/api/tools/rpmsignal` renders the identical trigger patterns to a 16-bit WAV (preset geometry transcribed from those config files; same batch-event semantics): a bench signal through an AC-coupled buffer, safety-noted; verified by parsing the waveform back (tooth count, gap = missing+1 slot periods, ramp rate) | **parity** — the software-hardware answer; the pure-software engine simulator (`web/sim.html`) still covers ECU-less protocol work |
| ZT2CSVToLogWorksDIF V0.71 | Converts Zeitronix ZT-2 wideband CSV logs to LogWorks DIF — its own archive description admits "the timeline is incorrect by factor 4" | `/api/tools/z2dif` converts the same ZDL exports (comma/semicolon dialects, comma decimals, fuzzy channel mapping) to DIF — **with the factor-4 timeline error corrected** and `timeline_factor=1.0` reproducing the reference output exactly | **parity and one better** — the correction is the default, the reference behaviour one flag away |
| CDM v2.12.36.20 (FTDI drivers) | Windows USB-serial drivers for the KKL adapter | Still mirrored byte-for-byte — and now **surfaced where it matters**: the adapter pre-flight report carries a per-OS driver block, and its "no adapter found" fix points Windows at the bundle. Covered by tests pinning that the bundle exists | **included** |

## Non-mirrored references

`docs/PRIOR_ART.md` tracks 5am_util (not in the public archive). GuzziOnBoard
already "backends" it in the strongest sense: its 5AM write sequence and
`calc_key()` are transcribed and unit-tested against the two published
seed/key pairs, and the algorithm ships — unverified-by-honesty, armable per
session (see `docs/PROGRAMMING.md` → "Using the shipped-but-unverified key
anyway").

## What the scripted proof covers

`scripts/e2e_smoke.py` runs a complete session over the real HTTP API:
catalog → select Griso 1200 8V 2012 → connect → identify → live data →
inject and decode a DTC → safety-gate refusals → actuator catalogue → all 94
XDFs visible → operator key acceptance → two-read verified backup → render
that backup as 133 named tables → programming opt-in → check-write green
with a single-use token on the sim's proven capability set → **write the
backup back and watch the read-back verify (sim flash round trip)** →
programming disabled and the write surface red again → the four support
utilities (ZT-2→DIF, bench RPM signal, FTDI driver bundle in the adapter
report, Mana TCU cataloged) → report export → disconnect. 25/25 checks
pass; the same assertions the UI relies on.
