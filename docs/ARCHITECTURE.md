# Architecture and safety boundary

## Core domains

### Transport

A transport moves framed bytes and knows nothing about screens or motorcycle semantics.

```text
Transport.open() -> Connection
Connection.request(frame, timeout) -> response
Connection.close()
```

Initial implementations:

1. `SimulatorTransport` — deterministic values, faults, and failure injection.
2. `SerialKLineTransport` — FTDI/USB serial, after capture fixtures exist.
3. `CanTransport` — SocketCAN and supported USB CAN adapters.

### ECU protocol

Each ECU family is a versioned adapter with explicit capabilities:

- identification;
- live-data polling and decoding;
- DTC read/clear;
- actuator tests;
- adaptations/service routines;
- memory read/write (disabled unless the adapter declares every safety precondition).

Raw frames, decoded values, units, scaling, and provenance should be retained in a session log. Never silently interpret an unknown byte as a value.

### Capability catalog

Vehicle definitions should be data-driven and versioned. A definition includes connector/transport, ECU family, supported operations, request/response fixtures, value decoders, DTC descriptions, and required preconditions. Unknown ECU software versions must fall back to read-only identification.

## Safety rules for write operations

The UI is not allowed to call a transport write directly. A write must pass a safety gate that:

1. confirms motorcycle and ECU identification;
2. confirms stable external power and an approved adapter;
3. reads the target region and verifies a user-saved backup;
4. validates the image/checksum and exact ECU compatibility;
5. requires an explicit typed confirmation;
6. records operator, time, adapter, ECU identity, checksums, and every frame;
7. verifies the written contents and reports recovery instructions on interruption.

Until those rules are implemented and tested with hardware, programming is a visible roadmap item only—not a feature.

## Testing strategy

- unit tests for every decoder using golden request/response fixtures;
- property tests for frame checksums and bounds handling;
- simulator failure modes: timeout, malformed frame, low voltage, wrong ECU;
- replay tests from recorded sessions;
- hardware-in-the-loop tests on a bench ECU with current-limited power;
- UI tests that assert destructive actions are unavailable in simulator/read-only mode.

## Proposed milestones

1. **Prototype (current):** simulator dashboard and safe interaction model.
2. **Core:** typed protocol/transport packages, session storage, fixtures, report export.
3. **Read-only hardware:** port detection, adapter diagnostics, ECU identity, live values, DTCs.
4. **Service:** actuator tests and resets, each gated by ECU-specific preconditions.
5. **Programming:** only after backup, checksum, recovery, and bench validation are complete.
