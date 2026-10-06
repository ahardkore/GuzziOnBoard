# GuzziOnBoard

A safety-first diagnostic workstation and evidence catalog for Moto Guzzi
motorcycles from the mid-1990s to current bikes, plus related Ducati and
Aprilia fitments. Only family-specific operations supported by recovered wire
evidence are enabled; incomplete ECU profiles are blocked before hardware is
opened.

> **Status: working software, unproven on a motorcycle.**
> The protocol stack, capability catalog, safety gate, memory/programming
> stack and UI are real and tested. The hardware transports are written but
> have **not** been validated against a bike. ECU writing is fully implemented
> against the documented 5am_util sequence and simulator-tested, and ships the
> 5AM key algorithm transcribed from that tool's source — but the key is not
> bench-confirmed on a Guzzi-fit ECU, so writing stays gated on hardware. See
> `docs/PROGRAMMING.md` and `docs/PRIOR_ART.md`.

---

## What it actually does today

| Area | State |
|---|---|
| KWP2000 / ISO 14230 application + data link layer | Implemented and unit tested |
| ISO-TP (ISO 15765-2) segmentation for CAN bikes | Implemented and unit tested |
| Simulated ECU **speaking the real wire protocol** | Implemented; drives the whole stack |
| Capability catalog: 11 cataloged controllers, 118 model variants across Moto Guzzi, Ducati and Aprilia, 1992–2026 — engine ECU families plus the Aprilia Mana CVT TCU | Implemented, data-driven |
| K-Line transport (validated fast init + validated 5-baud keyword handshake, standards-safe auto fallback, echo cancelling) | Written and unit tested, **untested on hardware** |
| CAN transport (python-can + ISO-TP) | Written; physical ECU profiles remain blocked because family-specific identifiers and application protocols were not recovered |
| ECU identification, live data, DTC read/clear | Implemented and exposed only where the family catalog declares the evidence-backed capability |
| Make / model / year vehicle selection (Moto Guzzi, Ducati, Aprilia) | Implemented; cross-brand bikes read-only by design |
| CAN request/response identifiers configurable for virtual rehearsal and capture analysis | Implemented; no generic pair is presented as a motorcycle default |
| CAN capture analysis: find the id pair from a passive sniff (candump / SavvyCAN / CRTD) | Implemented; read-only by construction |
| **Virtual CAN rehearsal**: the whole ISO-TP path (segmentation, flow control, reassembly) against the simulated ECU | Implemented (needs `.[hardware]` extra; the pair you set is the pair it speaks) |
| Remembers the garage, transport, paths and XDF choices between sessions | Implemented (browser-local) |
| Print / save any view as PDF; maps export as standalone HTML | Implemented |
| Actuator tests, TPS reset, adaptation resets | Implemented, gated by confidence + safety |
| Read-only local-identifier discovery sweep | Implemented |
| Session recording (raw frames + decoded samples) | Implemented |
| Report export (text + JSON) | Implemented |
| ECU memory **read** | Implemented; 5AM path grounded in a verified capture |
| Backup with two-read verification | Implemented |
| Firmware image validation (size, vector table, entropy, HW family) | Implemented |
| **Maps & tables**: XDF render/validation, 2D/3D editor, named diff, log overlay, and evidence-backed builder | Implemented; 94 XDFs (3842 tables) ship with the repo. Includes rectangular keyboard editing, smoothing/blending, editable embedded axes, explicitly configured live-channel/scale/offset tracing (no name/unit guessing), wideband-delay-aligned timestamp analysis with settling/rate filters, bounded AFR proposals, isolated checksum-plugin workers, and unendorsed package registries. Builds prefer the protected base map, require traceable evidence plus typed liability acknowledgement, and always create a new image with a complete manifest. Physical ECU/dyno validation remains pending evidence. |
| ECU memory **write / erase / program / verify** | Full flow **runs against the simulated ECU** (backup → validate → token → write → read-back verify, honestly labelled); the `hardware-family` gate check refuses any cross-family image before a frame moves (app and demo); gated on hardware pending a bench-confirmed key |
| Interrupted-write checkpoints and recovery guidance | Implemented |
| SecurityAccess seed/key plumbing + key-provider plugins | Implemented; the shipped 5AM key is unverified — armable per session via explicit, audited opt-in |
| Adapter pre-flight incl. FTDI latency timer and the vendored WHQL driver bundle in its fix guidance | Implemented |
| Gearing / road-speed calculator with the reference tool's full 58-model ratio table (Tools view presets, tyre/final-drive/custom ratios + API), CSV + JSON log export | Implemented |
| Zeitronix ZT-2 CSV → LogWorks DIF conversion — the reference tool's documented factor-4 timeline error corrected, its exact output one toggle away (paste/convert/download in the Tools view + API) | Implemented |
| Bench RPM trigger-signal generator — crank/cam WAV, wheel geometry transcribed from the reference tool's own config files; presets, custom wheels and `.rbt`-style batch ramps in the Tools view + API | Implemented |
| Fault read with workstation-observed context ("what was live when we looked") | Implemented; honestly *not* an ECU freeze frame |
| Session comparison (two recordings, channel by channel) | Implemented |
| Standalone browser engine simulator (`web/sim.html`) | Implemented; single self-contained page |
| **Hosted workstation demo** — the real UI with a virtual motorcycle and ECU running in the browser (`web/demo-api.js` + `web/demo-lab.js`) | Implemented; every view works with labelled in-browser fixtures, including a virtual connector/adapter, memory, maps, sessions, reports, guided tests and tools. The demo's write path runs the same hardware-family gate as the installed app and keeps a wrong-family fixture on its virtual bench so the refusal can be watched. Real-bike transport choices are omitted entirely; only the installed app exposes hardware |

More than 500 tests cover framing, checksums, scaling, DTC decoding, handshake negotiation, the safety gate,
image validation, XDF parsing/render/diff, the full read/backup/write/verify
round trip (including the hardware-family brick gate, in the app and in the
browser demo), fault injection, session comparison, the packaging entry point,
the reference-tool inclusions (log conversion, bench signal, driver bundle,
Mana TCU) and complete simulated sessions — plus `scripts/e2e_smoke.py`, a
30-check full-capability sweep over the live HTTP API and Playwright tests that
exercise the map editor through a real Chromium DOM.

## Run it

Only Python 3.11+ is needed for simulator mode.

```bash
python3 run_server.py              # same as: guzzionboard
```

`pip install -e .` installs a `guzzionboard` command with a proper
`--help` (`--host`, `--port`, `--no-record`, `--version`).

Pick a motorcycle in **Garage** (try `Griso 1200 8V` / `2012`), connect in
simulator mode, and the rest of the workstation comes alive.

### Without installing anything

The project site hosts two demos, both static:

* **<https://ahardkore.github.io/GuzziOnBoard/web/index.html>** — the
  workstation UI itself, with the simulated ECU running in the page. Two
  scripts stand in for the Python backend:
  * `web/demo-api.js` answers the conversational half of `/api` — garage,
    connect, identify, live data, fault codes, service actions, discovery,
    the simulated bike — from a catalog exported by
    `scripts/build_demo_data.py` plus ports of the engine model and the
    safety gate.
  * `web/demo-lab.js` simulates the half that needs files, a dump or a long
    job: ECU memory (read, backup, validate, write, verify against an image
    synthesised in the tab), maps and tables (the bundled TunerPro XDFs,
    parsed by a port of `maps.py` that the test suite proves byte-identical
    to the Python one), session recording/replay/export/comparison, the
    report, guided tests, and the workshop tools (gearing, Zeitronix→DIF,
    the bench RPM WAV, CAN and K-Line capture analysis).

  Everything simulated says so, in the payload and on the page, and the two
  compressions are stated wherever they apply: a twenty-minute flash read
  takes about three seconds, and a ten-second observation window in a guided
  test takes about one. The hosted page offers no real-bike transport choice;
  connector and adapter steps use labelled virtual fixtures, while browser
  permissions for serial, USB, CAN, and local files are never requested. When
  *this* server serves the page, both demo scripts stand down and the complete
  hardware UI returns: `run_server.py` marks the body `data-backend="live"`.
* **<https://ahardkore.github.io/GuzziOnBoard/web/sim.html>** — a
  self-contained page with just the engine model: start it, rev it, inject
  faults, watch the safety gate refuse.

Regenerate the demo catalog after any catalog change:

```bash
python3 scripts/build_demo_data.py          # writes web/demo-data.json
python3 scripts/build_demo_data.py --check  # CI-style staleness check
```

For real hardware:

```bash
pip install -e '.[hardware]'       # pyserial + python-can
python3 run_server.py
```

### Named maps from a dump

The **Firmware → Maps & tables** panel renders a dump as named fuel and
ignition tables using TunerPro XDF definitions — the same files the GuzziDiag
ecosystem uses. 94 of these ship under `guzzionboard/xdfs/` (3842 tables
across Moto Guzzi, Ducati, Aprilia, Piaggio, Morini, Gilera, GasGas, BMW,
Husqvarna, Malaguti and Scomadi) so common families work with nothing to
download; see `docs/XDF_LIBRARY.md` for what's included, its third-party
provenance, and how to vendor more with `scripts/import_xdfs.py`. The
original archive zips are mirrored unmodified in `vendor/guzzidiag/`. Anything not yet bundled can still be dropped in by
hand, exactly as before:

```bash
mkdir -p ~/.guzzionboard/xdfs && cp ~/Downloads/*5AM*.xdf ~/.guzzionboard/xdfs/
```

A file you drop in here overrides a bundled one of the same filename, so you
can correct or update a definition without touching the repo.

The chooser is grouped **by motorcycle**, not by the title the definition's
author happened to type: definitions for the ECU family on the bench are
listed first, everything else appears under the bikes it was actually
published for and is marked as not matching (with a confirmation before it is
rendered). Picking a map from the wrong family does not give slightly wrong
numbers — it reads a different calibration layout at the same addresses.

Then point the panel at an image (a previous read lands in
`~/.guzzionboard/images/`) and render, or diff it against a second image —
every changed cell is reported by table name and axis value, not raw offset.
A region read of a full-device XDF is handled automatically (address base
0x4000, detected and reported). Rendering and comparison are strictly
read-only.

### Evidence-backed map builds

The same panel has an intentionally separate **Advanced** builder. Prefer
**Load protected base map**: this opens the immutable, re-hashed vault copy
already required by the programming gate. Click only the cells or constants
covered by a recommendation, then attach the recommendation's title, HTTP(S)
source, applicability rationale, and (optionally) its exact excerpt. The app
ships no generic “stage 1” numbers—fuel, ignition, lambda, idle and limiter
changes are motorcycle- and configuration-specific, so an unattributed value
is not a recommendation.

Every build requires typing:

```
I understand modified maps can damage the engine and accept responsibility
```

The editor provides heat-mapped tables, rectangular Shift-selection, keyboard
navigation, set/add/percentage transforms, row/column interpolation, weighted
surface smoothing, bilinear blending, TSV copy/paste, 50-level undo/redo, and
portable `.tune.json` projects. Every table has dynamically refreshed SVG 2D
row profiles and a projected 3D surface. Image-backed embedded axes are editable
with the same raw-value lock; static XDF labels are not. Live tracing never
infers a channel from an axis name or unit: each table stores explicit X/Y
channel keys plus scale and offset (`axis = channel × scale + offset`) in browser
preferences and portable projects. A nearest cell is highlighted read-only only
when both mapped, validated channels are polled and both transformed values are
inside the declared axes; up to four surrounding cells expose bilinear
interpolation weights in the diagnostics. Out-of-range values do not falsely pin
an edge cell.

Projects are plans, not images: import verifies the source SHA-256, XDF filename
and every expected raw cell. Before the liability confirmation, the server
quantizes the complete plan and returns the exact stored values and named diff
without writing a file. The accepted preview gets its own SHA-256, and the build
is refused if that reviewed plan changes.

The offline log tool imports CSV, requires separate measured- and target-AFR
columns, bins only samples inside numeric table axes, requires a configurable
sample count, rejects cells whose measured or target AFR variation exceeds the
configured population-standard-deviation limit, and caps fuel proposals at 15%
or less. With an explicit timestamp column it evaluates each measured AFR at
`t` against linearly interpolated X/Y/target state at `t − configured wideband
delay`; seconds and milliseconds are supported. It rejects excessive timeline
gaps, state that did not remain in the same cell for the configured settling
window, and optional X/Y rate-limit violations, and reports each skip category.
Without timestamps it explicitly reports row-synchronous analysis and cannot
claim delay/transient alignment. It only creates a review overlay/proposal;
staging and building still go through source locks, evidence, preview, and
liability review. Mathematical AFR correction is not treated as proof that a
chosen table controls fuel in those operating conditions.

A build never modifies its source and never enables ECU programming. It writes
a new `.bin` plus sidecar under `~/.guzzionboard/images/`; the sidecar records
the source and output SHA-256, exact XDF hash, evidence, acknowledgement,
address base, each engineering/raw before-and-after value, and each byte
offset. `expected_raw` acts as an optimistic lock, so edits rendered from one
map cannot be silently applied to a different one. A non-base source needs a
second explicit acknowledgement and a mismatched XDF can be viewed but cannot
build.

No calibration-checksum algorithm is invented or bundled. An XDF that declares
a checksum is refused unless the operator explicitly selects a compatible local
plugin from `~/.guzzionboard/checksums/`. Plugins name the exact XDF checksum
titles they support, update deterministically, verify their output, and have
their version, source SHA-256, isolation mode, output hash, and exact changed byte
ranges folded into the reviewed plan. Inspection and calculation run in fresh
resource-limited, audit-guarded subprocesses with filesystem/network/process
restrictions and independent-repeat checks. This is containment, not a perfect
kernel sandbox; plugin self-verification is not core endorsement or physical-ECU
proof.

Likewise, `~/.guzzionboard/recommendations/` is a validated registry for
source/XDF/raw-locked, evidence-carrying third-party recommendation packages.
Preview and build re-load the selected package, require exact package/XDF hashes,
motorcycle and hardware fitment, evidence, change count, raw locks and target
values, then fold that provenance into the plan hash and sidecar. Manual edits
break the package lock until it is restaged or detached. The app bundles zero
tune packages or values and labels loaded packages user-supplied and unendorsed.
See `docs/PHYSICAL_VALIDATION.md` for the real-ECU
and dyno evidence protocol and machine-readable manifest schema. The repository
currently bundles no physical-validation record. Validate and review the named
diff before considering the ordinary, separately gated write workflow.

Run the tests with:

```bash
pip install -e '.[dev]' && pytest

# Real-browser map-editor suite
npm install
npm run test:browser
# macOS/Windows only, if Chromium is not already installed:
# npx playwright install chromium
```

The Playwright suite loads the static hosted workstation and drives the actual
DOM: protected-base rendering, rectangular and keyboard selection, arithmetic,
interpolation/smoothing/blending, clipboard paste/copy, axes, undo/redo, project
round-trips, explicit live tracing, and timestamp-aligned log analysis.

## Coverage

ECU families in the catalog, with the confidence level that governs what the
workstation will let you do:

| Family | Years | Bus | Confidence | Representative models |
|---|---|---|---|---|
| IAW P8 | 1993–1997 | K-Line | inferred / blocked | Daytona 1000, Quota 1000, California III i.e. |
| IAW 16M | 1996–2001 | legacy K-Line | documented / read-only | Sport 1100, V10 Centauro, Daytona RS |
| IAW 15M | 1997–2002 | K-Line | inferred / blocked | California EV/Jackal/Stone, Quota 1100 ES, V11 Sport |
| IAW 15RC | 2002–2012 | K-Line | inferred / blocked | V7 Classic, Nevada 750, Breva 750, California Vintage, Bellagio |
| **IAW 5AM / 5AM2** | 2005–2016 | K-Line | **verified-capture** | All CARC: Griso, Norge, Breva 850–1200, Stelvio, 1200 Sport |
| IAW 7SM | 2013–2021 | K-Line | inferred / identification only | California 1400, Audace, Eldorado, MGX-21, early V85 TT |
| MIU G3 | 2012–2016 | K-Line | inferred / blocked | V7 (single throttle body), V7 II, V9 |
| MIU G4 | 2017–2021 | CAN | unknown / blocked | V7 III, V7 850 |
| Marelli 11MP | 2019–2026 | CAN | unknown / blocked | Later V85 TT, V100 Mandello |
| Aprilia Mana CVT TCU | 2007–2016 | K-Line | inferred / blocked | Exact captured routine bytes are documented but not executable; the engine side is 5AM |

**Confidence is enforced, not decorative.** A capability is available only
when its family-specific wire definition supports it. Incomplete physical
protocols fail before the adapter port opens; a generic K-Line, KWP, CAN, or
ISO-TP resemblance is not enough.

### The same ECUs in other makes — Ducati and Aprilia

Ducati and Aprilia bought the same Magneti Marelli ECUs, and the GuzziDiag
ecosystem has always tuned them all. The catalog now resolves those bikes to
the shared families, with one deliberate limit:

| Make | Families | Examples |
|---|---|---|
| Ducati | P8, 15M, 16M, 59M, 5AM | 748, 916, 996, 999, 749, Monster 620–1000, Multistrada, 848/1098/1198, ST2/ST3/ST4 |
| Aprilia | 16M, 5AM, 7SM | RSV Mille, Tuono 1000, Falco, Caponord, Futura, Mana 850, RSV4 Factory |

Every cross-brand entry ships as `inferred`: a documented model→ECU mapping
does not prove that another make uses the same diagnostic identifiers or
controls. The stricter vehicle/family boundary applies automatically. The
workstation does not ask an owner to validate those assumptions on a customer
motorcycle.

The IAW 5AM is the fully mapped family. Legacy 16M now has evidence-bounded
read-only identification, live registers, and raw fault flags. 7SM exposes only
the identification exchange established by its published session log. The
remaining families stay unavailable where the deep evidence search did not
recover a complete transport and application definition; see
[`docs/PROTOCOL_NOTES.md`](docs/PROTOCOL_NOTES.md).

## Safety model

Three independent layers, in order:

1. **Capability + confidence.** A family must declare the capability *and*
   carry a trustworthy definition. An incomplete physical protocol is blocked
   before opening the adapter; inferred control operations are unavailable.
2. **The safety gate** (`guzzionboard/safety.py`). Every control action is
   evaluated against named preconditions — ECU identified, engine state
   *observed* (not assumed), battery voltage within range, checklist accepted
   — and a refusal tells you exactly which checks failed. Passing mints a
   single-use, operation-bound, expiring token. On the write path the gate
   also runs the **`hardware-family` check** on the concrete candidate image:
   the family digit of the ECU's own `IAW..HWnnn` answer must match both the
   provenance identity captured with the image and any hardware strings
   embedded in its bytes. Flashing across hardware families — an HW1xx image
   into an HW3xx ECU, the brick the 7SM documentation warns about in bold —
   is refused before a single frame is transmitted, in the installed app and
   in the hosted demo alike, and a confirmation token minted without the
   image cannot smuggle a cross-family file through.
3. **The frame guard.** The gate is installed as the KWP2000 session's
   `write_guard`, so an unarmed state-changing service never reaches the
   transport. You cannot bypass it by calling a service method directly.

Additional properties:

- **The UI guides physical state changes.** Modal, keyboard-accessible steps
  tell the operator when to stop the engine with the kill switch, leave the key
  on, start and idle the motorcycle, end the diagnostic session, turn the key
  off, and connect stable power. The gate then re-reads RPM/battery where the
  family supports those channels; clicking a prompt never bypasses a check.
- **Actuator outputs are owned by this software.** IAW ECUs have no output
  timer: once energised, an output stays on until something turns it off. Every
  pulse has a catalog-clamped deadline, and outputs are released on expiry, on
  disconnect, and when the session tears down.
- **Nothing is inferred optimistically.** An unobserved engine state blocks an
  engine-off operation; it is not treated as "probably stopped".
- **Raw bytes are always kept** next to every decoded value, in the UI and in
  the session log. If a scaling is wrong you can prove it.
- **Programming is a gate, not a wall.** Writing an ECU is your right and the
  code is complete, but it is opt-in: the operator must type an exact
  acknowledgement, the catalog must declare a *verified* programming
  definition for that family, and a two-read-verified backup must exist. A
  **base map** must also be on file for that exact ECU and still hash to what
  was recorded when it was saved — the original calibration, kept in
  `~/.guzzionboard/basemaps/`, filed automatically by the first verified
  backup and never overwritten by later ones. The
  frame guard still refuses RequestDownload and WriteMemoryByAddress until all
  of that holds. Flash *reads* are exempt from the opt-in, because the IAW
  families read memory with TransferData and reading breaks nothing.
- **A write that cannot be verified is a failed write.** The image is read
  back and compared; a mismatch is reported as a failure even if the ECU
  claimed success, and a checkpoint records how to recover.

## Handshake research

The K-Line and CAN-era alternatives were surveyed against ISO 14230 guidance,
open implementations and published IAW session logs. The result is implemented,
not just documented: complete fast/5-baud response validation, ISO 9141 keyword
detection, a standards-safe 2.6-second automatic fallback, no duplicate
StartCommunication, raw init-frame logging, and a Garage override for bench
work. The evidence matrix — including why KWP1281, proprietary Honda wake-ups,
UDS-over-CAN and DoIP are not silently treated as Marelli KWP2000 — is in
[`docs/HANDSHAKE_PROTOCOLS.md`](docs/HANDSHAKE_PROTOCOLS.md).

## Architecture

```text
web/                     UI (no framework, no build step)
  └── guzzionboard/server.py        local JSON API + static files
      └── workstation.py            selection, session, report
          └── diagnostics.py        identify / live / DTC / actuators / discovery
              ├── safety.py         preconditions, tokens, audit log
              ├── catalog/          data-driven ECU + vehicle definitions
              ├── protocol/         kwp2000.py, isotp.py
              └── transports/       simulator.py, kline.py, can.py
```

The simulator is a *transport*, not a mock of the application layer: it accepts
encoded frames, validates checksums, answers the catalog's identifiers, returns
real negative response codes, and can inject dropped frames, corrupted
checksums and `responsePending`. Simulated and real sessions therefore run
identical code. Inside a simulated session the *write* capability is what the
simulator has actually demonstrated — the whole flash cycle, including
read-back verification — and is shown as such; hardware sessions still read
the same red capability check the catalogue declares.

## Protocol evidence policy

Protocol confirmation is a project responsibility, not a setup step delegated
to a customer. Discovery is exposed only on a family where the request service
and scanned range are already established as non-mutating. Unknown ECUs are not
probed. New support requires a primary definition, licensed open-source
implementation, OEM technical document, or existing raw capture that fixes the
transport, payload, response layout, and relevant safety conditions before the
capability is enabled.

## Documentation

- `docs/ARCHITECTURE.md` — layer boundaries and the rules each layer obeys.
- `docs/PROTOCOL_NOTES.md` — wire-level reference and provenance for every
  claim in the catalog.
- `docs/PROGRAMMING.md` — reading, backing up and writing ECU memory: the
  verified 5AM sequence, image validation, the SecurityAccess gap and how to
  supply a key provider, and the recovery model.
- `docs/PRIOR_ART.md` — the other diagnostic programs worth studying, and
  which one closes each open gap (key algorithm, CAN IDs, per-family
  identifiers, transport validation).
- `docs/USER_WORKFLOWS.md` — guided connect, live-data, TPS and actuator flows.
- `docs/7SM_WORKFLOW.md` — ride-by-wire identification and learning workflow.

## Credits and disclaimer

This project stands on the reverse-engineering work of the GuzziDiag / IAWDiag
authors, the Guzzitek archive, and published IAW 5AM bus captures. It is not
affiliated with Piaggio, Moto Guzzi, Magneti Marelli, or the GuzziDiag author.

ECU diagnostics can injure you and ECU programming can brick an ECU or create
an unsafe motorcycle. Nothing here has been validated against a real bike. If
you connect it to your Guzzi, you are the test.

MIT licensed.

ECU diagnostics can injure you and ECU programming can brick an ECU or create
an unsafe motorcycle. Nothing here has been validated against a real bike. If
you connect it to your Guzzi, you are the test.

MIT licensed.
