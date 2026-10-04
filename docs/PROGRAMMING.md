# Reading and writing ECU memory

This document covers what GuzziOnBoard does when it touches ECU memory, what
it refuses to do, and exactly which missing piece of information causes each
refusal. Nothing here is aspirational: if the code cannot do something, the
reason is named.

## The short version

| Operation | State |
|---|---|
| Read flash, IAW 5AM | Implemented against a verified wire capture. Needs a SecurityAccess key provider. |
| Read flash, 7SM / 15M / 15RC / MIU G3 | Implemented, but region geometry is uncaptured, so it refuses rather than guessing. |
| Read flash, P8 / 16M | Not possible over K-Line. Socketed EPROM; use a programmer. |
| Read EEPROM, any family | Implemented, geometry uncaptured. |
| Backup with verification | Fully working. |
| Image validation | Fully working. |
| Write / erase / program | Fully implemented and simulator-tested. Disabled against hardware pending a verified key algorithm and a verified write sub-function. |
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

1. The catalog declares a `verified-*` programming definition for the family.
2. The ECU has been identified.
3. A backup exists **and was verified by reading it twice**.
4. The image passes every structural check.
5. Battery voltage is observed above 11.5 V.
6. The hardware checklist was accepted.
7. The operator typed the acknowledgement string exactly.

Seven green lights and the write proceeds. Six and it does not. The remaining
red light on every Guzzi family today is the first one, and that is an
evidence problem, not a policy one.

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

### Region geometry

The readable region runs `0x4000` to `0x50000`, which is 311,296 bytes. The
often-quoted figure of 327,680 bytes (`0x50000`) is the whole device including
the bootloader below `0x4000`, and that part is not reachable over K-Line.
A read takes about 20 minutes at 32 bytes per block.

## The missing piece: SecurityAccess

Service `0x27` is a seed/key challenge. The ECU sends four bytes, the tester
must answer with the right four bytes, and the algorithm is proprietary.

**GuzziOnBoard ships no working key algorithm for any Moto Guzzi ECU.** This
is not modesty, it is accuracy. Two seed/key pairs appear in the `5am_util`
transcript:

```
seed 0x27882789 -> key 0xDA786927
seed 0x3CA93CAA -> key 0x0E816927
```

The seed is structured (a 16-bit value `X` followed by `X+1`) and both keys
end in `0x6927`, which is suggestive. Fitting `key_hi = a*X + b (mod 2^16)` to
two points yields exactly one `(a, b)` pair — and that is worth nothing, since
any two points define a line. That fit is registered as
`iaw5am-affine-hypothesis`, marked unverified, and never selected by default.

A wrong key is cheap once and expensive repeatedly: most ECUs lock the
security gate after a few failures, some with a timed penalty. So the tool
will not spray guesses at your ECU.

> **Update (see `docs/PRIOR_ART.md` §1.1):** the `5am_util` *source* (not just
> its transcript) contains the working 5AM key algorithm. A Python port there
> reproduces both published pairs exactly. It is not yet wired into
> `security.py`; until it is bench-confirmed on a Guzzi-fit 5AM it stays
> `documented`, not `verified`.

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
and the image, compares the family digit, and refuses on mismatch.

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
