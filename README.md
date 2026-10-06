# GuzziOnBoard

A safety-first diagnostic workstation for Moto Guzzi motorcycles, covering the
Magneti Marelli ECU families fitted from the mid-1990s to the current bikes —
plus the same Marelli ECUs as Ducati and Aprilia fitted to their bikes of the
same era, read-only until their identifier tables are confirmed.

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
| K-Line transport (fast init + 5-baud init, echo cancelling) | Written, **untested on hardware** |
| CAN transport (python-can + ISO-TP) | Written, **identifiers unconfirmed** |
| ECU identification, live data, DTC read/clear | Implemented |
| Make / model / year vehicle selection (Moto Guzzi, Ducati, Aprilia) | Implemented; cross-brand bikes read-only by design |
| CAN request/response identifiers configurable per session | Implemented (the pair is unconfirmed on CAN bikes) |
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
| **Maps & tables**: TunerPro XDF render + named diff of dumps | Implemented; 94 XDFs (3842 tables) ship with the repo, more can be added |
| ECU memory **write / erase / program / verify** | Full flow **runs against the simulated ECU** (backup → validate → token → write → read-back verify, honestly labelled); gated on hardware pending a bench-confirmed key |
| Interrupted-write checkpoints and recovery guidance | Implemented |
| SecurityAccess seed/key plumbing + key-provider plugins | Implemented; the shipped 5AM key is unverified — armable per session via explicit, audited opt-in |
| Adapter pre-flight incl. FTDI latency timer and the vendored WHQL driver bundle in its fix guidance | Implemented |
| Gearing / road-speed calculator with the reference tool's full 58-model ratio table (Tools view presets, tyre/final-drive/custom ratios + API), CSV + JSON log export | Implemented |
| Zeitronix ZT-2 CSV → LogWorks DIF conversion — the reference tool's documented factor-4 timeline error corrected, its exact output one toggle away (paste/convert/download in the Tools view + API) | Implemented |
| Bench RPM trigger-signal generator — crank/cam WAV, wheel geometry transcribed from the reference tool's own config files; presets, custom wheels and `.rbt`-style batch ramps in the Tools view + API | Implemented |
| Fault read with workstation-observed context ("what was live when we looked") | Implemented; honestly *not* an ECU freeze frame |
| Session comparison (two recordings, channel by channel) | Implemented |
| Standalone browser engine simulator (`web/sim.html`) | Implemented; single self-contained page |
| **Hosted workstation demo** — the real UI with the simulated ECU running in the browser (`web/demo-api.js` + `web/demo-lab.js`) | Implemented; every view works against the simulated bike, including memory, maps, sessions, reports, guided tests and the tools. Simulated and time-compressed processes are labelled as such. Only hardware transports (serial, CAN) are refused rather than faked |

415 tests cover framing, checksums, scaling, DTC decoding, the safety gate,
image validation, XDF parsing/render/diff, the full read/backup/write/verify
round trip, fault injection, session comparison, the packaging entry point,
the reference-tool inclusions (log conversion, bench signal, driver bundle,
Mana TCU) and complete simulated sessions — plus `scripts/e2e_smoke.py`, a
25-check full-capability sweep over the live HTTP API.

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
  test takes about one. Hardware is the one thing not faked — a web page
  cannot open a serial port or a CAN interface, so those are refused rather
  than invented. When *this* server is the one serving the page, both scripts
  stand down: `run_server.py` marks the body `data-backend="live"`.
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

A file you drop in here overrides a bundled one of the same title, so you can
correct or update a definition without touching the repo.

Then point the panel at an image (a previous read lands in
`~/.guzzionboard/images/`) and render, or diff it against a second image —
every changed cell is reported by table name and axis value, not raw offset.
A region read of a full-device XDF is handled automatically (address base
0x4000, detected and reported). Strictly read-only.

Run the tests with:

```bash
pip install -e '.[dev]' && pytest
```

## Coverage

ECU families in the catalog, with the confidence level that governs what the
workstation will let you do:

| Family | Years | Bus | Confidence | Representative models |
|---|---|---|---|---|
| IAW P8 | 1993–1997 | K-Line | inferred | Daytona 1000, Quota 1000, California III i.e. |
| IAW 16M | 1996–2001 | K-Line | documented | Sport 1100, V10 Centauro, Daytona RS |
| IAW 15M | 1997–2002 | K-Line | documented | California EV/Jackal/Stone, Quota 1100 ES, V11 Sport |
| IAW 15RC | 2002–2012 | K-Line | documented | V7 Classic, Nevada 750, Breva 750, California Vintage, Bellagio |
| **IAW 5AM / 5AM2** | 2005–2016 | K-Line | **verified-capture** | All CARC: Griso, Norge, Breva 850–1200, Stelvio, 1200 Sport |
| IAW 7SM | 2013–2021 | K-Line | documented | California 1400, Audace, Eldorado, MGX-21, early V85 TT |
| MIU G3 | 2012–2016 | K-Line | documented | V7 (single throttle body), V7 II, V9 |
| MIU G4 | 2017–2021 | CAN | inferred | V7 III, V7 850 |
| Marelli 11MP | 2019–2026 | CAN | inferred | Later V85 TT, V100 Mandello |
| Aprilia Mana CVT TCU | 2007–2016 | K-Line | unknown | Transmission controller; identification + discovery only — flashing stays with ManaTCU; the Mana's engine side is the 5AM above |

**Confidence is enforced, not decorative.** Anything below `documented`
degrades to identification, fault codes and the read-only discovery sweep —
the workstation will not command an ECU it does not genuinely understand.

### The same ECUs in other makes — Ducati and Aprilia

Ducati and Aprilia bought the same Magneti Marelli ECUs, and the GuzziDiag
ecosystem has always tuned them all. The catalog now resolves those bikes to
the shared families, with one deliberate limit:

| Make | Families | Examples |
|---|---|---|
| Ducati | P8, 15M, 16M, 59M, 5AM | 748, 916, 996, 999, 749, Monster 620–1000, Multistrada, 848/1098/1198, ST2/ST3/ST4 |
| Aprilia | 16M, 5AM, 7SM | RSV Mille, Tuono 1000, Falco, Caponord, Futura, Mana 850, RSV4 Factory |

Every cross-brand entry ships as `inferred`: the model→ECU mapping is
documented (GuzziTek master list, Ducati.ms ECU list, TuneECU), but this
project's identifier tables were all captured in a Moto Guzzi context — so the
workstation selects the stricter confidence level and keeps those bikes at
identification, fault codes and the read-only discovery sweep until someone
records a session on the real machine. One capture promotes the whole family.
The Ducati-only IAW 59M (999/749 and the injected air-cooled Monsters) is
modelled as its own family at `unknown` for the same reason.

The IAW 5AM is the fully mapped family: 41 live identifiers with scalings
decoded from a real bus capture, 17 actuators, TPS reset and self-adaptation
reset. For the others, see "Contributing a capture" below.

## Safety model

Three independent layers, in order:

1. **Capability + confidence.** A family must declare the capability *and*
   carry a trustworthy definition. `inferred` families are read-only, full stop.
2. **The safety gate** (`guzzionboard/safety.py`). Every control action is
   evaluated against named preconditions — ECU identified, engine state
   *observed* (not assumed), battery voltage within range, checklist accepted
   — and a refusal tells you exactly which checks failed. Passing mints a
   single-use, operation-bound, expiring token.
3. **The frame guard.** The gate is installed as the KWP2000 session's
   `write_guard`, so an unarmed state-changing service never reaches the
   transport. You cannot bypass it by calling a service method directly.

Additional properties:

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
  definition for that family, and a two-read-verified backup must exist. The
  frame guard still refuses RequestDownload and WriteMemoryByAddress until all
  of that holds. Flash *reads* are exempt from the opt-in, because the IAW
  families read memory with TransferData and reading breaks nothing.
- **A write that cannot be verified is a failed write.** The image is read
  back and compared; a mismatch is reported as a failure even if the ECU
  claimed success, and a checkpoint records how to recover.

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

## Contributing a capture

The bottleneck is wire-level data, not code. Every family except the 5AM needs
its local identifiers characterised, and the workstation has a tool for exactly
this:

1. Connect read-only, go to **Discovery**, sweep `0x30`–`0x7F` with the engine
   off, and press **Keep as baseline**.
2. Start the engine, sweep again. Identifiers that moved are live channels;
   ones that did not are usually shared zero slots.
3. **Export JSON** and open an issue with it, plus the ECU label from your bike.

That turns directly into a catalog entry under
`guzzionboard/catalog/ecus/`. Adding a motorcycle is a data change, not a code
change.

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
