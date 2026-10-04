# Protocol notes and provenance

Every wire-level claim this project makes, and where it came from. The rule is
simple: **an unknown byte is never silently interpreted as a value.** If the
provenance for something is weak, it is marked `inferred` in the catalog and
the workstation refuses to use it for anything but observation.

## Confidence vocabulary

Used in `guzzionboard/catalog/ecus/*.json` and enforced by
`guzzionboard.catalog.meets()`.

| Level | Meaning | Control actions? |
|---|---|---|
| `verified-bench` | Exercised against this ECU on a bench or a bike | yes |
| `verified-capture` | Decoded from a real K-Line / CAN capture | yes |
| `documented` | From a service manual or a mature open-source tool | yes |
| `inferred` | Pattern-matched from a sibling ECU, unproven | **no** |
| `unknown` | Placeholder | **no** |

---

## 1. Physical layer

### K-Line (IAW P8 … 7SM, MIU G3)

- KWP2000 / ISO 14230 over a single bidirectional wire, **10400 baud, 8N1**.
- Half duplex: **everything the tester sends is echoed back on RX before the
  ECU replies.** The echo must be read and discarded. This is the single most
  common reason a hand-rolled K-Line tool "sees no response", and it is handled
  in `KLineConnection._consume_echo`.
- The cable must contain an **L9637D-class transceiver**; an FTDI TXD pin does
  not drive K-Line directly.
- Some IAW ECUs drop bytes sent back-to-back by a fast USB UART, so the
  transport paces requests with a per-byte delay (P4min, default 5 ms).

### CAN (MIU G4, 11MP)

- KWP2000/UDS payloads inside ISO-TP (ISO 15765-2) at 500 kbit/s.
- Request/response identifiers default to the ISO 15765-4 pair **0x7E0 / 0x7E8**.
  **This is unconfirmed on Piaggio-group motorcycles.** Verify with a passive
  sniff before trusting it; the catalog marks both CAN families `inferred` for
  exactly this reason.

---

## 2. Frame format

Addressed frame, both directions:

```
[FMT] [TGT] [SRC] [DATA ...] [CS]

FMT = 0x80 | len      len = number of DATA bytes, 1..63
TGT = 0x10 (ECU)      SRC = 0xF1 (tester)      request:  .. 10 F1 ..
CS  = sum(preceding bytes) & 0xFF              response: .. F1 10 ..
```

When `len` exceeds 63 the low bits of FMT are zero and an explicit length byte
follows SRC. A short frame (`FMT` high bits `00`) carries no addresses. The
IAW 5AM answers both framings for reads; this project uses addressed frames.

Implemented in `guzzionboard/protocol/kwp2000.py`:
`encode_request`, `decode_frame`, `frame_length`.

---

## 3. Initialisation

### Fast init (default, IAW 15x and later)

Pull K-Line low **25 ms** (serial BREAK), release **25 ms**, then send
StartCommunication:

```
-> C1 33 F1 81 <cs>
<- C1 EA 8F ...          positive + key bytes
```

### 5-baud slow init (P8, 16M, and as a fallback)

Bit-bang the address byte at 5 baud (200 ms per bit: idle high, start bit low,
8 data bits LSB first, stop bit high). The ECU replies at 10400 baud with
`0x55` (sync), `KW1`, `KW2`. The tester sends the **inverted KW2**; the ECU
answers the **inverted address**. Slow init establishes the session by itself —
no StartCommunication follows.

The implementation schedules bit edges against an absolute clock rather than
chaining `sleep()` calls, because accumulated drift breaks the 200 ms budget.

---

## 4. Session bring-up (IAW 5AM, verified)

```
-> 81                       StartCommunication        (fast init only)
-> 83 03 00 FF 00 FF 00     AccessTimingParameter, subfn 03 (set values)
-> 10 81                    StartDiagnosticSession, session 0x81
   ... poll loop ...
-> 3E                       TesterPresent, when idle
-> 20                       StopDiagnosticSession
-> 82                       StopCommunication
```

**Session 0x81, not 0x85.** The IAW 5AM rejects `10 85` with NRC `0x22`
(conditionsNotCorrect) outside the programming flow. The simulator reproduces
this rejection so the error path is actually tested.

Widening the timing window via `83` makes polling tolerant of a slow USB serial
stack. The 5AM accepts it and then ignores the reply.

`21 <rli>` works in the default session anyway, so the diagnostic session is
armed lazily, immediately before the first control command.

Negative responses are `7F <SID> <NRC>`. `NRC 0x78` (responsePending) is
retried transparently by `KWP2000Session.request`.

---

## 5. Live data — service 0x21

Each measurement is its **own** request; there is no block read.

```
-> 21 <rli>
<- 61 <rli> <value ...>      big-endian, length taken from the frame
```

The IAW 5AM answers every identifier in `0x30`–`0x7F`. **38 of those 79 are
served from three shared zero slots** and carry no variable at all — they are
marked `dead` in the catalog and excluded from polling.

Verified channels and formulas (source: live capture of an IAW 5AM HW610 on a
Moto Guzzi, cross-checked against GuzziDiag changelog corrections):

| RLI | Channel | Formula | Unit |
|---|---|---|---|
| 0x30 | Engine speed | raw | rpm |
| 0x32 | Intake air temperature | raw − 40 | °C |
| 0x33 | Head/oil temperature | raw − 40 | °C |
| 0x34 | Throttle angle | raw / 10 | ° |
| 0x35 | Ignition advance (latched) | raw / 10 | ° |
| 0x37 | Ignition advance (live) | raw / 10 | ° |
| 0x39 | Injection time | raw / 1000 | ms |
| 0x3A | Idle target | raw | rpm |
| 0x3C | Battery voltage | raw / 10 | V |
| 0x45 / 0x46 | Lambda front / rear | raw | mV |
| 0x47 / 0x48 | Lambda integrator front / rear | raw / 10, **signed 16-bit** | % |
| 0x49 | Lambda loop | 0 open, 2 closed | — |
| 0x4B | Lambda phase front | 1 frozen, 2 cold, 3/4 open loop, 5 closed leaning, 7 closed enriching | — |
| 0x53 | Road speed | raw | km/h |
| 0x6B / 0x6C / 0x6D | Idle stepper base / position / trim | raw | steps |
| 0x58 | Engine state bitfield | 0x01 closed throttle, 0x02 after-start over, 0x04 turning | — |
| 0x57 | Stop state | 4 running, 8 stopped, 16 transition | — |
| 0x61 / 0x76 / 0x78 | Neutral / side stand / clutch | enum | — |
| 0x79 / 0x7A | Kill switch STOP / RUN (strictly inverse) | enum | — |

Cylinders are **front / rear**, per the Guzzi V-twin layout.

---

## 6. Fault codes

```
Read   -> 18 00 FF 00        ReadDTCByStatus
       <- 58 <count> [hi lo status] x count
Clear  -> 14 FF 00           ClearDiagnosticInformation
```

Each DTC is a 2-byte SAE J2012 code plus a status byte:

- `status & 0x0F` — fault kind (1/2/4/8 on IAW ECUs)
- `status & 0x20` — **stored** (clear = current/new); this is the bit that
  decides, the coarser `status & 0x60` also files a warning as stored
- `status & 0x40` — warning indicator (lamp)

The decoder deliberately tolerates a truncated tail: it reports the records
that actually arrived rather than inventing the rest.

Descriptions come from `guzzionboard/catalog/dtc_sae.json` (70 codes, SAE J2012
plus the Marelli-specific interpretations), merged into every family and
overridable per family.

---

## 7. Identification

`1A 80` (ReadEcuIdentification) returns a fixed-layout block sliced by
per-family offsets in the catalog:

- **IAW 5AM**: Drawing (0:11), Hardware (11:22), Omologation (22:33),
  Software (33:44), Tester (44:55).
- **IAW 7SM**: the same, plus Serial, confirmed by a published session log
  showing `Drawing: CM281703`, `Hardware: IAW7SMHW320`, `Software: 7614LA20`,
  `Omologation: 7SM2EC`, `Serial: E6MNBGS4T`, `Tester: D30073`, followed by a
  baud-rate switch.

---

## 8. Adaptations and actuator tests

### Routines (IAW 5AM, verified)

| Function | Request | Positive response | Service |
|---|---|---|---|
| TPS reset | `31 21` | `71 21` | StartRoutineByLocalId |
| Self-adaptation reset | `30 7E 04` | `70 7E` | InputOutputControlByLocalId |

PF1C and PF2C throttle bodies support the electronic TPS reset. **PF3C is
non-linear and must be set manually with a voltmeter** — the catalog carries
that warning on every PF3C model.

Other families differ and are **not** verified at the wire level:
15RC uses a proprietary byte (0x89); 7SM uses `31 23` plus a timer and requires
handle self-learning *immediately* followed by throttle self-learning;
MIU G3 uses `31 21` on a different transport. These are marked `inferred`.

`33 <localid>` (RequestRoutineResults) is probed best-effort after a routine.
Most IAW families do not implement it; a negative response there is expected
and is not treated as a failure.

### Actuators — service 0x30

```
-> 30 <localid> 07        activate
-> 30 <localid> 00        deactivate
<- 70 <localid> ...        positive
```

| ID | Actuator | ID | Actuator |
|---|---|---|---|
| 1 | A/C compressor relay | 10 | Injector cyl 3 |
| 2 | Coil, front cylinder | 11 | Injector cyl 4 |
| 3 | Coil, rear cylinder | 12 | Fan relay 1 |
| 4 | Idle stepper | 13 | Fan relay 2 |
| 5 | Fuel pump relay | 14 | Lambda heater 1 |
| 6 | Tachometer | 15 | Lambda heater 2 |
| 8 | Injector, front cylinder | 16 | Canister purge |
| 9 | Injector, rear cylinder | 17 / 18 | Warning / temp lamp |

Separately confirmed on the 5AM: fuel pump = 5, coil rear = 3, injector rear = 9,
tachometer = 6. A two-cylinder Guzzi only has some of these; the rest return a
negative response, which the workstation surfaces rather than hiding.

**There is no ECU-side timer.** An energised output stays on until something
turns it off. The deadline is therefore owned by this software — see
`DiagnosticsService.pulse_actuator`.

---

## 9. Memory

Read uses `23 <addr24> <size>` (ReadMemoryByAddress). The IAW 5AM image is
exactly **327680 bytes (0x50000)**; a read takes roughly 20 minutes.

The programming path on real tooling is
`10 85` → `27` SecurityAccess (seed/key) → baud switch → `34`/`36` block
transfer + checksum.

**This project does not implement it.** There are no protocol fixtures, no
bench-tested recovery path, no power-loss handling, and no verified seed/key.
Writing is refused by the catalog (`write_supported: false` everywhere), by the
safety gate (`programming-enabled` check), and by the frame guard, which blocks
`0x34`, `0x36`, `0x37` and `0x3D` unconditionally in this build.

A note from the field worth repeating: never run a 7SM write through a virtual
machine — USB timing jitter has bricked ECUs.

---

## Sources

- Prior-art survey of diagnostic programs and what each one closes —
  [docs/PRIOR_ART.md](PRIOR_ART.md), including the 5am_util source analysis
  (working 5AM SecurityAccess algorithm, full write sequence, firmware
  encoder).
- Live K-Line capture and decode of an IAW 5AM HW610 on a Moto Guzzi —
  [Vasiy/onboard-logger `docs/PROTOCOL.md`](https://github.com/Vasiy/onboard-logger)
- GuzziDiag / IAWDiag changelogs and ECU list —
  [von-der-salierburg.de](https://www.von-der-salierburg.de/download/GuzziDiag/)
- Guzzitek ECU master list and *La Guzzithèque* injection bible —
  [guzzitek.org](https://guzzitek.org/)
- guzzifan.com ECU and error-code reference
- Published 7SM session log (ApriliaForum) — init, identity block, baud switch
- GuzziDiag beginner tutorials (thisoldtractor.com, wildguzzi.com) — TPS target
  values and per-model reset rules
- ISO 14230-1/-2/-3 (KWP2000), ISO 9141-2, ISO 15765-2 (ISO-TP), SAE J2012
