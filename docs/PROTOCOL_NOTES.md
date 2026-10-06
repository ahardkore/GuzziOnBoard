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

## Non-5AM validation audit (2026-10-06)

The table below is the result of a source, document, capture, archive, and
binary-evidence search. A compatibility list proves only that somebody has a
working implementation; it does not disclose enough of that implementation to
send bytes from this project. Guessed operations were therefore removed from
the public capability list. Profiles may retain inferred fields for fixture
replay and future comparison, but `session.physical_supported: false` prevents
a physical port from even being opened.

| Family | Primary or closest evidence recovered | Established | Still unavailable / runtime boundary |
|---|---|---|---|
| **P8** | Vendored IAW Scan 2 `iaw04k.cs` at commit `a5995e…`; automotive IAW-04K implementation | A related controller uses direct 7680-baud one-byte query/reply | No Moto Guzzi P8 definition or capture ties P8 to that map. No physical connection and no capabilities. |
| **16M / 1.6M** | Marelli 3.00600/16F technical definition; published 1.6M open implementation; ScanST Guzzi application record | Six-byte 1200-baud key-on code, delayed `0F AA CC`, switch to 7680 baud, one-byte requests/replies, part-number bytes, live formulas, raw fault registers | Read-only. Fault bits stay raw because a Guzzi-specific bit interpretation was not recovered. No routine, actuator, clear, memory, or write claim. |
| **15M** | ScanST and GuzziDiag/IAWDiag family records; inspected IAW15x reader binary | Tooling and motorcycle applicability exist. The reader binary separately exposes its programming bootstrap, but that is not a diagnostic-session definition | No trustworthy diagnostic initialization, frame, live-ID, DTC, routine, or actuator definition was recovered. No physical connection and no capabilities. |
| **15RC** | GuzziDiag/IAWDiag family/changelog records; inspected IAW15x reader binary | Tooling and motorcycle applicability exist | Same unresolved diagnostic wire details as 15M. No physical connection and no capabilities. |
| **59M** | GuzziDiag/IAWDiag and user documentation | Tooling and slow-init selection exist as compatibility evidence | No primary family transcript or payload table. Unknown placeholder; no physical connection and no capabilities. |
| **7SM** | Published real session log with ECU identity and baud switch; commercial compatibility material | K-Line session, `1A 80` identity layout, and the observed switch are grounded in a session record | Only identification is exposed. Live IDs/scaling, DTC requests, routines, actuators, and memory remain unavailable; inferred catalog entries are not capabilities. |
| **MIU G3** | Official Moto Guzzi/Piaggio MIU G3 training presentation | RLI identifiers `31,32,35,37,3A,45–4C,61,62,6B,6C,78`; IOLI `7E`; RELI `21` TPS-zero and `24` are OEM-defined | Training pages omit transport initialization, response widths/scaling, and complete IOLI/RELI payload semantics. RLIs are retained as raw research definitions, but physical connection and all capabilities are blocked. |
| **MIU G4** | Moto Guzzi service material and commercial-tool documentation | ECU fitment and CAN diagnostics exist | No CAN IDs, addressing mode, application protocol, DIDs/RLIs, scaling, DTC, or routine frames. ISO-TP alone is not UDS. No physical connection or capabilities. |
| **11MP** | Commercial Piaggio diagnostic coverage | CAN diagnostics exist | Same missing CAN/application evidence as MIU G4. No physical connection or capabilities. |
| **Mana TCU** | Raw PADS traffic in the ApriliaForum archive and Mana workshop procedure | Physical KWP addressing uses ECU `0xEC`, tester `0xF1`; exact captured routines are `30 02 08` (belt replacement) and `30 01 08` (potentiometer reset) | No controls are exposed. Security access and all mechanical conditions cannot be enforced; initialization, safe session sequencing, identity, DTC, live-data, and memory definitions are incomplete, so physical connection is blocked. |

This is intentionally conservative: customers are not asked to probe the
unknown families to validate this project's assumptions. Physical sessions for
P8, 15M, 15RC, 59M, MIU G3, MIU G4, 11MP, and Mana TCU fail before opening
the adapter. 16M is enabled read-only from the recovered family definition;
7SM exposes only the captured identification operation. Mana's exact routine
bytes are recorded for provenance but are neither connected nor executable.

### Vendored source evidence

`vendor/ies2/` is a source-only, byte-for-byte snapshot of the relevant IAW
Scan 2 files. `PROVENANCE.md` records upstream commit
`a5995eab86e82be60386e99b2eecc9c14810ec85`, `LICENSE.txt` carries the BSD
3-Clause terms, and `SHA256SUMS` fixes every retained upstream file. This is
valuable primary implementation evidence for automotive IAW-04K and 16F; its
scope is not silently extended to a motorcycle P8 or later Marelli families.

---

## 1. Physical layer

### K-Line families

K-Line is only an electrical layer; it does not imply KWP2000. The recovered
families use at least two incompatible applications:

- IAW 5AM and the captured 7SM session use addressed KWP2000 / ISO 14230 at
  10400 baud.
- 16M uses a legacy 1200-baud key-on/initialization exchange and then raw
  one-byte requests and responses near 7.8 kbaud. It has no KWP frame.
- Mana uses KWP physical addressing `EC=TCU`, `F1=tester`, but its complete
  initialization/session has not been recovered.
- The P8, 15M, 15RC, 59M, and MIU G3 physical applications are not treated as
  established merely because all of them use a K-Line pin.

On the usual half-duplex USB K-Line adapter, everything sent by the tester is
echoed on RX before the ECU replies. The echo must be consumed. The cable must
contain an L9637D-class transceiver; an FTDI TXD pin does not drive K-Line
directly.

### CAN (MIU G4, 11MP)

The available evidence establishes only that these are diagnosed over CAN.
The former assumptions of 500 kbit/s, ISO-TP carrying KWP, and generic
`0x7E0/0x7E8` identifiers have been withdrawn: none was supported by a
Piaggio-family capture or primary definition. The catalog deliberately has no
CAN identifiers or diagnostic capabilities, and a physical connection is
refused before the adapter is opened. ISO-TP is a transport, not proof of a UDS
or KWP application.

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

Both paths now observe the ISO 14230 W5 idle interval (**at least 300 ms**) and
validate the complete handshake. See [HANDSHAKE_PROTOCOLS.md](HANDSHAKE_PROTOCOLS.md)
for the standards comparison and the protocols deliberately not conflated with
KWP2000.

### Fast init (default, IAW 15x and later)

Pull K-Line low at 0 ms, release it at **25 ms**, and send the first bit of
StartCommunication at the **50 ms** mark:

```
-> C1 33 F1 81 66
<- 83 F1 10 C1 EA 8F <cs>   positive + key bytes (representative)
```

The response counts only when its KWP length and checksum are valid, its target
is this tester, its service is positive StartCommunication `C1`, and two key
bytes are present. The physical transport has then completed StartCommunication;
the session layer must not send `81` a second time.

### Legacy 16M key-on initialization

This is separate from KWP slow initialization:

1. At key-on, listen at 1200 baud for the six-byte ECU code and require leading
   sync byte `55`.
2. Wait at least 500 ms after the code.
3. Send `0F`, `AA`, `CC` at 1200 baud with the documented approximately
   110/110/150 ms timing. There is no acknowledgement.
4. Switch to 7680 baud (the practical UART divisor used for the nominal
   7812.5-baud link), then exchange one request byte for one response byte.

The direct legacy initializer used by the P8 research profile skips the key-on
sequence, but physical use of that profile is blocked because the recovered
implementation is automotive IAW-04K rather than a Guzzi P8 capture.

### KWP 5-baud slow init implementation boundary

The transport can bit-bang an ISO 14230 address byte at 5 baud and validate
sync, keyword inversion, and inverted-address acknowledgement. It schedules
bit edges against an absolute clock and distinguishes ISO 9141 keywords
`08 08` / `94 94` from KWP. That standards-correct implementation is not,
however, evidence that any particular ECU family uses it. No currently blocked
family is enabled merely by selecting the slow-init option.

A KWP automatic fast-to-slow fallback waits 2.6 seconds so a failed fast pulse
cannot corrupt the next five-baud address window. This is transport behaviour,
not a family validation claim.

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

The IAW 5AM answers every identifier in `0x30`–`0x7F`. **40 of those 79 are
served from three shared zero slots** and carry no variable at all — they are
marked `dead` in the catalog and excluded from polling. (Re-synchronised
2026-10 with the upstream map this table came from; it was 38 when first
transcribed, and all 40 dead slots are now listed individually rather than
counted.)

Two slots moved the other way. `0x4A` and `0x4C` were recorded here as dead
because they read as constant zero during the capture; upstream now names
them as the rear-bank twins of the lambda loop (`0x49`) and lambda phase
(`0x4B`) flags, unproven. They are carried as `inferred` with that
disagreement written into their `source_note` — a slot that reads zero on a
single-lambda session and a slot with no variable behind it look identical
from the outside, and nothing here will pretend to know which it is.

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

### Legacy 16M registers

The legacy protocol reads one byte per request. Two-byte values are assembled
in request order before decoding.

| Request byte(s) | Channel | Formula | Unit |
|---|---|---|---|
| `01 02` | Engine speed | `15,000,000 / raw16` | rpm |
| `03 04` | Injection duration | `raw16 × 0.002` | ms |
| `05` | Ignition advance | `raw × 0.5` | degrees |
| `06` | Manifold pressure | `raw × 3` | mmHg |
| `07`, `08`, `09` | Air temp, engine temp, throttle | raw only | count |
| `0A` | Battery voltage | `raw × 0.0625` | V |
| `22` | Fuel trim | raw only | count |

The source set contains conflicting temperature conversion formulae, so the
temperature channels deliberately remain raw rather than selecting a plausible
curve.

### MIU G3 OEM application identifiers (not physically enabled)

The official training table names these ReadLocalIdentifier entries:

| RLI | Meaning | RLI | Meaning |
|---|---|---|---|
| `31` | manifold pressure | `32` | air temperature |
| `35` | base ignition advance | `37` | applied ignition advance |
| `3A` | target engine speed | `45` / `46` | oxygen sensor 1 / 2 voltage |
| `47` / `48` | oxygen correction 1 / 2 | `49` / `4A` | mixture-control state 1 / 2 |
| `4B` / `4C` | OBDI sensor state 1 / 2 | `61` / `78` | gear/clutch state entries |
| `62` | stepper state | `6B` | base stepper opening |
| `6C` | closed-loop stepper opening | | |

The same OEM pages name IOLI `7E` and RELI `21` (TPS zero-position setting) and
`24`, but do not publish enough payload semantics to execute them. The RLI
entries are stored as raw-width research metadata only: the document supplies
neither response sizes nor conversion formulae, and it does not define the
physical/session layer. Consequently the MIU G3 profile exposes no physical
capability.

---

## 6. Fault codes

### KWP records (verified 5AM)

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
plus the Marelli-specific interpretations), merged as a lookup table. Presence
of that table does not claim that an unvalidated family supports this KWP
request.

### Legacy 16M fault registers

The 16M definition reads request bytes `10`, `11`, `12`, `14`, `15`, `16`,
and `2B` through `30`. Responses are bitfields, not SAE/KWP DTC records. Until a
Moto Guzzi-specific interpretation is sourced, the API and UI show each raw
register value and set bit (`REG-xx-BIT-y`) without assigning a component or
fault description.

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

The legacy 16M does not send `1A 80`. Its six key-on bytes are retained as the
ISO code, and request bytes `17` through `21` are concatenated as the ECU part
number. Unsupported families do not inherit either identification scheme.

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

The former 15RC and 7SM routine guesses were removed. MIU G3's OEM-named TPS
zero-position operation is retained only as non-executable research metadata.
Changelogs can establish that a function exists, but not its complete request,
response, session, security, timing, and mechanical conditions. These
operations are absent from the effective capability set; profile and
operation-level confidence independently block the retained MIU G3 record.

The Mana capture is stronger on payload identity: full PADS frames
`80 EC F1 03 30 02 08 9A` and `80 EC F1 03 30 01 08 99` establish the belt
replacement and potentiometer reset requests. They still are not executable.
The workshop procedure requires ordered adaptation steps and physical
conditions (including wheel clearance/mechanical state) that this application
cannot verify, and the required security/session sequence is incomplete.

`33 <localid>` (RequestRoutineResults) is probed best-effort after a supported routine.
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

For the verified 5AM path, memory operations follow the dedicated programming
transcript described by the catalog and programming state machine. No generic
`23 <addr24> <size>` assumption is extended to a non-5AM family. Unvalidated
memory-read capabilities have been removed from 15M, 15RC, 7SM, and MIU G3.

The programming path on real tooling is
`10 85` → `27` SecurityAccess (seed/key) → baud switch → `34`/`36` block
transfer + checksum.

The 5AM read path and documented programming state machine are implemented and
simulator-tested. Physical writing remains disabled because the key algorithm,
recovery path, and power-loss behaviour have not been bench-verified on a
Guzzi-fitted ECU. Every non-5AM family declares both memory read and write
unsupported unless separate family evidence exists; none is inferred from
KWP service numbers shared by 5AM.

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
- IAW Scan 2 source, BSD-3-Clause, fixed at the vendored commit and hashes —
  [TzOk83/IES2](https://github.com/TzOk83/IES2), `vendor/ies2/`
- Marelli 3.00600 / 16F technical information and the published 1.6M
  implementation discussion — legacy initialization, registers, and formulas
- Official Moto Guzzi/Piaggio MIU G3 training presentation — OEM RLI/IOLI/RELI
  tables (the tables do not define widths, scaling, or the transport)
- Raw Aprilia PADS frames and reverse-engineering record for the Mana TCU —
  [ApriliaForum archive](https://www.apriliaforum.com/forums/archive/index.php/t-264978.html)
- GuzziDiag / IAWDiag changelogs and ECU list —
  [von-der-salierburg.de](https://www.von-der-salierburg.de/download/GuzziDiag/)
  (feature-existence evidence only, not a payload definition)
- Guzzitek ECU master list and *La Guzzithèque* injection bible —
  [guzzitek.org](https://guzzitek.org/)
- guzzifan.com ECU and error-code reference
- Published 7SM session log (ApriliaForum) — init, identity block, baud switch
- GuzziDiag beginner tutorials (thisoldtractor.com, wildguzzi.com) — TPS target
  values and per-model reset rules
- ISO 14230-1/-2/-3 (KWP2000), ISO 9141-2, ISO 15765-2 (ISO-TP), SAE J2012
