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
| `CanTransport` | `can.py` | Written, identifiers unconfirmed |

`pyserial` and `python-can` are imported lazily, so the simulator and the tests
run on a machine with no drivers installed. A missing driver raises
`TransportUnavailable` with the install command in the message.

`read_frame` uses the KWP2000 length field rather than a timeout heuristic, so
a frame is consumed exactly, not guessed at.

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
   battery voltage, and checklist acceptance. An allowed decision mints a
   single-use token bound to that operation and expiring after 120 s.
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
