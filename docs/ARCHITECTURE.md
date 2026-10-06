# Architecture

Each layer has one job and one rule it is not allowed to break. This document
describes what is implemented, not what is planned.

```text
web/                               UI — no framework, no build step
  │  fetch() JSON
  ▼
guzzionboard/server.py             local HTTP API + static files
  ▼
guzzionboard/workstation.py        selection, session lifecycle, reports
  ▼
guzzionboard/diagnostics.py        identify / live / DTC / actuators / discovery
  ├── safety.py                    preconditions, tokens, audit
  ├── catalog/                     ECU + vehicle definitions (JSON)
  ├── protocol/kwp2000.py          framing, services, NRC, session
  ├── protocol/isotp.py            ISO 15765-2 segmentation
  └── transports/                  simulator.py | kline.py | can.py
```

---

## Transports

**Rule: a transport moves framed bytes and knows nothing about motorcycles.**

```python
Transport.open() -> Connection
Transport.initialize(connection, method=...) -> InitResult
Connection.write(bytes)
Connection.read_frame(timeout) -> bytes     # b"" on timeout
Connection.close()
```

Three implementations:

| | File | State |
|---|---|---|
| `SimulatorTransport` | `simulator.py` | Complete, drives the test suite |
| `KLineTransport` | `kline.py` | Written, untested on hardware |
| `CanTransport` | `can.py` | Generic ISO-TP mechanics written; no physical ECU profile is enabled without validated bitrate, identifiers, addressing, and application protocol |

`pyserial` and `python-can` are imported lazily, so the simulator and the tests
run on a machine with no drivers installed. A missing driver raises
`TransportUnavailable` with the install command in the message.

`read_frame` uses the KWP2000 length field rather than a timeout heuristic, so
a frame is consumed exactly, not guessed at. `InitResult` says whether the
transport already completed the handshake and retains any pre-session request
and response bytes. This matters on K-Line: fast init includes a validated
StartCommunication exchange, while the simulator leaves that frame to
`KWP2000Session`. The explicit flag prevents a duplicate hardware `0x81` and
lets the early exchange enter the same raw-frame log. See
[`HANDSHAKE_PROTOCOLS.md`](HANDSHAKE_PROTOCOLS.md).

### The simulator is a transport, not a mock

This is the most important design decision in the project. `SimulatedEcu`
accepts **encoded frames**, validates their checksums, dispatches on the real
service IDs, answers the catalog's local identifiers through a small physical
engine model, and returns genuine negative response codes — including
reproducing the IAW 5AM's rejection of session `0x85`.

It can also inject failures: dropped responses, corrupted checksums, injected
`responsePending`, and added latency. The error paths are therefore tested, not
hoped for.

Consequence: simulated and real sessions run **identical** code from
`KWP2000Session` upwards.

---

## Protocol

**Rule: never silently interpret an unknown byte as a value.**

`protocol/kwp2000.py` owns framing, checksums, the service enum, negative
response codes, DTC decoding and the stateful session. It is transport
agnostic and has no imports from the layers above.

`KWP2000Session` handles request/response correlation, verifies that a response
answers the request that was sent, retries `responsePending`, and raises rather
than returning a plausible-looking wrong number. Every frame is handed to an
`on_frame` callback in both directions for the session log.

`protocol/isotp.py` implements ISO 15765-2 segmentation and reassembly with no
CAN library import, so it is unit testable on its own.

---

## Capability catalog

**Rule: adding a motorcycle is a data change, not a code change.**

`catalog/ecus/*.json` — one versioned document per ECU family holding the
transport parameters, session bring-up, identification layout, live parameters
(local id, offset, length, endianness, sign, scale, bias, state enums), the
actuator map, routines, memory limits, declared capabilities and **sources**.

`catalog/vehicles.json` — 81 model variants mapped to families with year
windows, displacement, TPS type and per-model warnings. Guzzi changed ECUs as
running changes, so overlapping entries are expected; `Catalog.resolve` prefers
the narrower window and `Catalog.ambiguous` lets the UI say so out loud.

`catalog/dtc_sae.json` — shared SAE J2012 table merged into every family and
overridable per family.

Nothing in the protocol or UI layers may hardcode a local identifier, a scaling
factor or an actuator number. Tests enforce uniqueness of identifiers, presence
of provenance, presence of warnings on dangerous actuators, and that no family
enables memory writing.

### Confidence gating

Every definition carries a confidence level. `EcuProfile.supports()` returns
`False` for control capabilities below `documented`, so an `inferred` family
degrades to identification, DTCs and the read-only discovery sweep. This is
asserted in `tests/test_catalog.py`, not merely documented.

---

## Safety

**Rule: refusing has to be the easy path.**

Three independent layers:

1. **Capability + confidence** in the catalog (above).
2. **`SafetyGate.evaluate()`** returns a `Decision` listing every named check
   with pass/fail and a human-readable reason. Checks include mode, declared
   capability, definition confidence, ECU identified, engine state *observed*,
   battery voltage, checklist acceptance and — for writes, evaluated on the
   concrete candidate image — `hardware-family`, which refuses any image whose
   captured provenance or embedded `IAW..HWnnn` strings belong to a different
   hardware family than the identified ECU (flashing across families bricks
   the ECU; the 7SM documentation says so in exactly those words). An allowed
   decision mints a single-use token bound to that operation and expiring
   after 120 s.
3. **`SafetyGate.session_guard()`** is installed as the KWP2000 session's
   `write_guard`. A state-changing service that is not explicitly armed for the
   current operation never reaches the transport — calling a service method
   directly does not bypass it. Programming services are blocked even when
   armed, unless `allow_programming` is set at the build level.

Supporting properties:

- Engine state is only ever set from an observed value
  (`DiagnosticsService._update_inferred_state`). Unknown is not "probably off".
- Actuator deadlines are owned by this software, clamped by the catalog, and
  released on expiry, on disconnect and on teardown, because IAW ECUs have no
  output timer.
- Every control decision, allowed or refused, is appended to an audit log that
  ships in the exported report.

---

## Session recording

**Rule: a decoded value is only trustworthy if the bytes behind it were kept.**

Newline-delimited JSON, one file per session, holding `frame` (raw hex, both
directions), `sample` (key, local id, raw bytes, decoded value, unit),
`action`, `safety` and `error` events. Recordings are the input for fixing a
decoder without owning the bike that produced the fault, and for contributing
new catalog entries.

Session files are gitignored. They can contain a VIN-adjacent ECU serial.

---

## What is deliberately absent

- **ECU writing / flashing.** No fixtures, no bench-tested recovery, no
  power-loss handling. Blocked in the catalog, the gate and the frame guard.
- **Automatic ECU detection by probing.** Guessing a protocol by writing to an
  unknown bus is how things go wrong; the operator picks, and the catalog warns
  when a model/year is ambiguous.
- **A desktop shell.** The HTTP API is the seam a Tauri shell would sit on, but
  shipping a browser-based tool first keeps the dependency surface at zero.


## The memory and programming layer

Added after the project's scope widened from "diagnostics only" to full
parity with the GuzziDiag toolchain, including its readers, writers and
EEPROM tools.

```
guzzionboard/firmware.py      image container, checksums, structural
                              validation, hardware-compatibility, diffing.
                              Pure data. Never touches a transport.

guzzionboard/maps.py          XDF render/diff/structural audit plus bounded
                              table, constant and embedded-axis encoding.
                              Changes carry expected raw values, so they cannot
                              drift onto a different source image.

guzzionboard/map_analysis.py  pure offline AFR-log binning and bounded,
                              review-only fuel proposals. Never writes images.

guzzionboard/tuning.py        non-destructive map previews/builds: quantised
                              plans, source/XDF/output/plan hashes,
                              recommendation evidence, liability opt-in and a
                              complete exact-change manifest. No tune values.

guzzionboard/checksums.py     explicit local checksum-plugin contract. Exact
                              supported XDF titles, deterministic update,
                              verification, plugin hash and byte-range audit;
                              no bundled calibration checksum algorithm.

guzzionboard/recommendations.py
                              strict local third-party recommendation package
                              registry with fitment/XDF/raw/evidence locks. No
                              bundled package and no community endorsement.

guzzionboard/physical_validation.py
                              operator evidence-manifest registry with local
                              artifact hash checks. An evidence index is never
                              promoted to core certification.

guzzionboard/security.py      SecurityAccess key providers: an interface, a
                              registry, a file-based plugin loader. Ships no
                              working algorithm for any Guzzi ECU.

guzzionboard/programming.py   the state machine: session -> unlock -> read /
                              erase -> transfer -> program -> verify, with
                              progress reporting and on-disk checkpoints.

guzzionboard/adapter.py       pre-flight checks on the interface itself,
                              including the FTDI latency timer.

guzzionboard/tools.py         standalone calculators and log exporters.
```

Three rules keep this layer honest.

**Validation is pure.** `firmware.py` imports nothing from the transport or
diagnostics layers, so an image can be checked without a motorcycle, and the
checks are trivially unit testable.

**Geometry comes from the catalog, never from a guess.** A region with an
uncaptured size refuses to be read and says so. The alternative — reading some
plausible default length — produces a file that looks like a backup and is
not one.

**Reading and writing are separated at the frame guard.** The IAW families
read flash with TransferData (0x36), which is nominally a mutating service.
`SafetyGate.session_guard(..., purpose="read")` permits that specific use
without the programming opt-in, while still refusing RequestDownload (0x34)
and WriteMemoryByAddress (0x3D). Without that split, either reads would
require the write ceremony or writes would inherit the read's permissions.

### Long operations and the HTTP seam

A flash read is twenty to thirty minutes, and a verified backup is two of
those. `server.JobRunner` runs one memory operation at a time on a background
thread; the UI polls `/api/memory/progress` for phase, byte counts and an ETA.
One job at a time is a deliberate constraint: concurrent flash operations on a
single ECU are never what anybody meant.

## The hosted demo (a second implementation of the API seam)

The UI in `web/` is a plain page talking to `/api` over `fetch`. That seam has
two implementations:

| | `guzzionboard/server.py` | `web/demo-api.js` + `web/demo-lab.js` |
|---|---|---|
| Runs in | a local Python process | the browser tab |
| Speaks | the real KWP2000/ISO-TP stack through a transport | the catalog, the engine model and the safety gate, ported |
| Raw bytes | encoded, checksummed, sent, received | reconstructed from the catalog scaling (labelled as a demo) |
| ECU memory | read over the wire, ~20 minutes a pass | a synthesised image in a virtual filesystem, ~3 seconds a pass, labelled time-compressed |
| Maps & tables | TunerPro XDFs parsed by `maps.py` | the same bundled XDFs parsed by a port of `maps.py`, proven identical by the test suite |
| Sessions | JSONL files under `~/.guzzionboard/sessions` | in-tab recordings plus two pre-recorded ones, same replay/export/compare code paths |
| Guided tests | real observation windows | the same steps and verdicts, windows compressed ~8x against the engine model |
| Tools | read and write files | the same arithmetic over pasted text and browser downloads |
| Connector / adapter setup | physical serial and CAN hardware | labelled in-tab connector and adapter fixtures; no real-bike transport option or browser hardware permission |

Why a second implementation exists: GitHub Pages has no process to run, and a
diagnostic tool nobody can try is a diagnostic tool nobody adopts. Why it is
not allowed to drift:

* **The catalog is exported, never retyped.** `scripts/build_demo_data.py`
  dumps the same `as_dict()` payloads the Python API returns into
  `web/demo-data.json`. `tests/test_demo_mode.py` regenerates it and fails on
  any difference, so adding an ECU updates the demo or breaks the build.
* **The gate is ported with its vocabulary intact.** The browser evaluates the
  same named checks (`mode`, `capability`, `definition-confidence`,
  `identified`, `engine-off`/`engine-running`), mints the same single-use
  confirmation token and keeps the same audit list. A refusal in the demo
  reads exactly like a refusal from the real tool, because it is the same
  policy.
* **Every stand-in is announced.** `demo-lab.js` simulates a flash read, map
  render, guided test, connector, and adapter; every payload carries
  `simulated: true` with a note saying what was invented and by how much time
  was compressed. The hosted page omits physical transports entirely and
  never requests Web Serial, WebUSB, CAN, or local-filesystem access. The
  installed application keeps the real controls.
* **The ports are checked against the originals, not eyeballed.** The XDF
  parser, the gearing arithmetic, the DIF conversion, the hashes and the WAV
  renderer are ports; `tests/test_demo_mode.py` renders three bundled
  definitions with both implementations and fails on any difference, down to
  Python's `%g` rounding.
* **One switch, no guessing.** `server.mark_live_backend()` rewrites the
  served page's `<body>` to `data-backend="live"`; the shim returns
  immediately when it sees that. Hostnames, ports and protocol sniffing play
  no part, so running the real workstation on a LAN address cannot
  accidentally land you in the demo.

`tests/demo_browser_check.mjs` drives both scripts through a whole session
under Node (resolve → select → connect → identify → live → DTC read/clear
with tokens → blocked and unblocked actuator → fault seeding → discovery
sweep → key-provider opt-in → backup, validate, arm programming, write and
verify → render and diff maps → replay, export and compare sessions →
report → a guided test to its verdict → every tool → the comms sliders
spoiling the simulated wire → virtual connector and adapter pre-flight), and
`tests/demo_xdf_parity.mjs` renders a definition the browser's way so the
Python side can compare. `tests/test_demo_mode.py` runs both when Node is
available.

That script-level harness is complemented by `tests/browser/map-editor.spec.mjs`.
Playwright runs the static workstation in Chromium and exercises real focus,
keyboard, pointer, modal, file, download, clipboard, local-storage, SVG and
class-state behavior. It covers the protected-base editor, transforms and
project round-trips, explicit live-channel mappings, and time-aware log
analysis; `npm run test:browser` is therefore the browser-level editor gate,
not a synonym for the Node API harness.
