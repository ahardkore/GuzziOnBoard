# Reading and writing ECU memory

This document covers what GuzziOnBoard does when it touches ECU memory, what
it refuses to do, and exactly which missing piece of information causes each
refusal. Nothing here is aspirational: if the code cannot do something, the
reason is named.

## The short version

| Operation | State |
|---|---|
| Read flash, IAW 5AM | Implemented against a verified wire capture. Needs a SecurityAccess key provider. |
| Read flash, 7SM / 15M / 15RC / MIU G3 | Generic memory framework exists, but these family profiles expose no read capability because session, security, and/or region geometry are incomplete. |
| Read flash, P8 / 16M | Not exposed: no validated in-circuit read sequence is available here. P8 maps commonly live on a socketed EPROM that can be preserved with a programmer. |
| Read EEPROM, non-5AM families | Generic framework only; no incomplete family profile declares a hardware capability. |
| Backup with verification | Fully working. |
| Image validation | Fully working. |
| Write / erase / program | Fully implemented against the documented 5am_util sequence and simulator-tested. Disabled against hardware pending a bench-confirmed key and physical-layer validation. |
| Write verification by read-back | Fully working. |
| Interrupted-write recovery | Fully working. |

## Why writing is gated rather than absent

An earlier version of this project refused to write at three separate layers
and described that as a safety feature. That was the wrong call: it is your
motorcycle, the GuzziDiag toolchain has been writing these ECUs for over a
decade, and a tool that cannot restore a backup it took is not a safe tool,
it is an incomplete one.

Writing is now a capability with preconditions rather than a prohibition. The
preconditions are:

1. The catalog declares a `verified-*` programming definition for the family —
   **or the session runs against the built-in simulator**, whose capability set
   is proven in the test suite and flagged as simulated wherever it surfaces
   (the catalogue profile itself is never loosened; a hardware session still
   finds check one red).
2. The ECU has been identified.
3. A backup exists **and was verified by reading it twice**.
4. The image passes every structural check.
5. Battery voltage is observed above 11.5 V.
6. The hardware checklist was accepted.
7. The operator typed the acknowledgement string exactly.
8. The image belongs to the **same hardware family** as the identified ECU —
   the `hardware-family` gate check compares the family digit of the ECU's own
   `IAW..HWnnn` answer against both the provenance identity captured with the
   image *and* the hardware strings embedded in its bytes. Flashing across
   families — an HW1xx image into an HW3xx ECU, or any other mix — bricks the
   ECU, and a file whose family cannot be established is refused rather than
   assumed fine. This check runs on the concrete image inside
   `write_region()`, so it cannot be bypassed by minting the confirmation
   token first, and it is part of the decision the UI renders before the
   confirmation dialog.

Eight green lights and the write proceeds. Seven and it does not. The remaining
red light on every Guzzi family today is the first one, and that is an
evidence problem, not a policy one. For the 5AM the evidence is now one bench
session away: the key algorithm and the full write sequence are transcribed
and simulator-tested (`docs/PRIOR_ART.md` 1.1-1.5); what is missing is a real
ECU saying yes.

## Rehearsing the whole thing on the simulator

Because the simulator speaks the real wire protocol and implements the
complete flash cycle — unlock, RequestDownload, TransferData, TransferExit,
read-back — the web UI's entire write flow is exercisable with zero hardware:
check the adapter report, take the two-read backup (the session's own
`.json` sidecar keeps the provenance, and `FirmwareImage.from_file` reads it
back so a file backed up by this tool is flashable back), validate it, type
the acknowledgement, get the token, write, watch the read-back verify. Inside
such a session the capabilities panel says *Write supported: yes (simulated)*
and explains that on real iron the same view stays refused, with reasons.
Two seams make this honest rather than loose: enabling programming moves the
session into programming mode (restored on disable), and the simulated
capability overlay exists only while the simulator session exists —
`tests/test_simulated_flash.py` locks every one of those facts.

## The 5AM read sequence

Taken from a published `5am_util` transcript, byte for byte:

```
->  81                          StartCommunication
<-  C1 EF 8F                    keybytes
->  10 85                       StartDiagnosticSession, programming
<-  50 85
->  1A 80                       ReadEcuIdentification
<-  5A 80 ...  "96518407B  IAW5AMHW610 ... 2235SF01 ... 5AMQS"
->  10 0C 0C 09                 session + baud switch
<-  50                          tester address is now 0x01, not 0xF1
->  27 01                       SecurityAccess, requestSeed
<-  67 01 27 88 27 89           seed
->  27 02 DA 78 69 27           sendKey
<-  67 02
->  36 11 00 FE 02 01 00        TransferData, setup
<-  76 11 02
->  36 21 00 40 00 20           read 0x20 bytes at 0x004000
<-  76 21 40 00 00 20 FA 00 00 02 FA 00 04 40 ...
```

Two things are worth noticing.

**`10 85` is accepted here but refused during live diagnostics.** The same
request returns NRC 0x22 once an ordinary `10 81` session is running. Both
behaviours are real; the ECU state is what differs. The simulator models
exactly this, and `test_programming_session_is_refused_once_diagnostics_are_running`
pins it down.

**Flash reads use TransferData, a nominally mutating service.** That forced a
change to the frame guard: `session_guard(..., purpose="read")` permits 0x36
without the programming opt-in, while still refusing RequestDownload (0x34)
and WriteMemoryByAddress (0x3D). Reading is not destructive and should not
require the same ceremony as writing.

## The 5AM write sequence

Transcribed from `write_firmware()` in 5am_util's `main.c` (the transcript
only covered reads, which is why the write sub-function used to be marked
`inferred`). The catalog carries every frame as data:

```
->  10 85 03                    programming session; line moves to 38400
<-  50 85
->  83 03 1E 02 0A 14 00        AccessTimingParameter (P2/P3/P4)
<-  C3 03 ...                   tester address stays 0xF1 ...
->  27 01                       ... except here, sent from 0x01
<-  67 01 <seed>
->  27 02 <key>                 the iaw5am-kwp-divmod answer
<-  67 02
->  3B 98 20                    writer record   - MANDATORY
->  3B 99 20 18 01 01           reflash date record
->  31 02 00 40 00 04 FF FF     arm the erase for 0x4000..0x4FFFF
->  33 02                       run the erase  (ECU streams status; wait)
->  34 00 40 00 33 04 C0 00     RequestDownload
->  36 <254 bytes>              TransferData of the ENCODED blob
    ... 1226 chunks, no sub-function ...
->  37                          RequestTransferExit
->  31 01 00 40 00 04 FF FF <sum16>   arm programming with the checksum
->  33 01                       program
```

Three details that are easy to get wrong:

**The upload is not the dump.** The wire payload is
`firmware.iaw5am_upload_blob(image)` — the eight magic bytes `C2 07 16 33 6F
EB B0 1D` followed by every flash byte transformed by an add/rotate/invert
pattern with an 8-byte period. The encoder is byte-verified against a
compiled copy of the original C, and its inverse decodes what the ECU holds
for the read-back verification. The program routine's argument is the plain
`sum16` of the flash payload minus its last two bytes — the ECU decodes
before it checks.

**The records are not optional.** 5am_util's comment is explicit: leave out
the `3B 98 20` writer record and the `3B 99 20` date record, and
RequestDownload fails. The simulator enforces this, and
`test_the_ecu_refuses_a_download_without_the_writer_records` pins it.

**The write session is not the read session.** No `10 0C 0C 09`, no switch
to tester address `0x01`: the session frame `10 85 03` itself moves the line
to 38400, and the tester address stays `0xF1` — except the `27` exchange,
which 5am_util sends from `0x01`. The catalog records all of this; the
simulator reproduces it.

### Region geometry

The readable region runs `0x4000` to `0x50000`, which is 311,296 bytes. The
often-quoted figure of 327,680 bytes (`0x50000`) is the whole device including
the bootloader below `0x4000`, and that part is not reachable over K-Line.
A read takes about 20 minutes at 32 bytes per block.

## The SecurityAccess key

Service `0x27` is a seed/key challenge. The ECU sends four bytes, the tester
must answer with the right four bytes, and the algorithm is proprietary.

**GuzziOnBoard ships one key algorithm: `iaw5am-kwp-divmod`, transcribed from
`calc_key()` in 5am_util's source** (see `docs/PRIOR_ART.md` 1.1). It
reproduces both pairs published in that tool's transcript exactly:

```
seed 0x27882789 -> key 0xDA786927
seed 0x3CA93CAA -> key 0x0E816927
```

In seed terms (the seed is a 16-bit `X` followed by `X+1`):

```
key = (bswap16(X+1) div 161) << 24 | (bswap16(X) mod 200) << 16 | 0x6927
```

It is registered `verified=False` and never selected automatically. "Working"
means it provably matches the published pairs and is the algorithm a tool
that really flashed IAW 5AM ECUs shipped; **not verified** means nobody has
fed it a seed from a Guzzi-fitted 5AM and confirmed the unlock. The 59M is
expected to share it (one family in the GuzziDiag tooling); no claim is made
for the 15x, 7SM or MIU families.

A wrong key is cheap once and expensive repeatedly: most ECUs lock the
security gate after a few failures, some with a timed penalty. So the tool
will not spray guesses at your ECU.

### Using the shipped-but-unverified key anyway

Reads and writes that need SecurityAccess refuse until the operator
explicitly accepts the unverified-key risk for the session. Any one of these
grants it, and every grant is recorded in the safety audit log:

- the **Accept unverified key providers for this session** checkbox under
  **ECU memory → SecurityAccess key providers** in the UI,
- `POST /api/security/unverified` with `{"accept": true}` (or
  `{"accept": false}` to withdraw it),
- the `allow_unverified_keys` flag on `POST /api/programming/enable` when
  opting into programming,
- `gate.accept_unverified_key_risk(True)` or the `allow_unverified_key=True`
  argument when driving the library in-process.

The acceptance is session-scoped and never persisted. Refusals keep saying
exactly how to grant it; nothing retries a rejected key for you.

### Supplying a key provider

If you have legitimately obtained the algorithm for your own ECU, drop a file
into `~/.guzzionboard/keys/`:

```python
ECU_ID = "5am"
NAME = "my-5am-key"
VERIFIED = True          # only if you have tested it on a real ECU
NOTE = "where this came from"

def key(seed: bytes) -> bytes:
    ...
```

It is loaded at startup and appears under **ECU memory → SecurityAccess key
providers**. Providers marked `VERIFIED = False` are never chosen
automatically.

## Image validation

Every check runs before a byte is transmitted.

| Check | Fatal when |
|---|---|
| size | Does not match the declared region exactly. |
| blank | Image is entirely `0x00` or `0xFF`. |
| vector table | No `FA 00 xx xx` interrupt table at offset 0. |
| entropy | Above 7.8 bits/byte **and** no vector table. |
| hardware | Embedded `IAWxxHWnnn` string disagrees with the ECU's. |

The vector-table test is the same idea GuzziDiag's writer uses to reject
encrypted `.ddg` files: a plain image begins with a recognisable jump table,
an encrypted container does not. Entropy alone is only a warning, because a
densely packed image can be legitimately high.

The hardware check is the one that matters most. The 7SM documentation is
blunt: *"Don't flash HW1xx versions in a HW3xx ECU and vice versa. You will
brick your ECU!"* GuzziOnBoard extracts the hardware string from both the ECU
and the image, compares the family digit, and refuses on mismatch. On the write
path this stops being a validator finding and becomes the gate's named
`hardware-family` check (precondition 8 above): it compares against the
provenance identity captured with the image as well as the embedded strings,
either disagreeing is fatal, and the refusal happens before the erase sequence
begins. The hosted demo carries a wrong-family fixture on its virtual bench
(the *wrong-family-demo* image a read leaves behind) so the refusal can be
watched at work: validate it, or aim the write at it — both refuse.

## Backups

A backup is **two full reads that agree byte for byte**. One read over a noisy
K-Line connection is not evidence of anything. If the two reads differ, the
backup is not saved and the error names the likely causes — adapter, ground,
battery — because a link that cannot read reliably must never be used to
write.

Each backup is saved with a JSON sidecar recording the ECU identity, all five
checksum forms, the hardware strings found inside, and the timestamp.

## Writing, step by step

```
check preconditions        gate evaluation, single-use token
hardware-family gate       ECU vs image family, on the concrete file
validate image             fatal findings abort
require verified backup    second, independent check
checkpoint: starting
enter programming session  10 85, then the baud switch
unlock                     27 seed/key
checkpoint: erased         34 RequestDownload, or the family's erase sequence
transfer                   36 blocks
checkpoint: transferred
finalise                   37 RequestTransferExit
read back and compare      full re-read
checkpoint: complete
```

If the read-back does not match, the write is reported as **failed** even
though the ECU said it succeeded, and the error tells you not to power the ECU
down. A checkpoint file in `~/.guzzionboard/images/` records the phase reached,
the backup path, and phase-specific recovery instructions, which the UI shows
on the next connection.

## Hardware notes that actually matter

**Set the FTDI latency timer to 1 ms.** The default is 16 ms. Every block is a
request/response round trip, so 16 ms of dead time per block is the usual
reason a 30 minute read takes hours, and on impatient ECUs it pushes responses
outside the P2 timing window. The **ECU memory → Adapter pre-flight** panel
reads the current value from sysfs on Linux and can set it; elsewhere it tells
you where the setting lives.

**Do not write from a virtual machine.** USB serial timing through a VM is
unreliable, and the adapter check fails outright if it detects one.

**Use a charger.** A 7SM read is about 30 minutes; a backup is two of those.
Pull the headlight fuse or put the battery on a tender.

**Disable screensavers, sleep and virus scanners** for the duration.

## Sources

- `5am_util` by DoI — verified 5AM transcript, bench pinout, region geometry.
  <https://codeberg.org/DoI/5am_util>
- GuzziDiag toolchain changelogs, von-der-salierburg.de — tool inventory,
  per-family coverage, the HW1xx/HW3xx warning, the 1 ms latency requirement,
  the `.ddg` jump-table test, TesterCode `WLoad1039T`.
- ISO 14230-2 and ISO 14230-3 for framing and service semantics.
