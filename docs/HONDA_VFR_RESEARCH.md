# Honda VFR1200F Keihin MGE source audit and research workflow

This work is **synthetic-tested in GuzziOnBoard, not tested on a physical ECU**. It does not unlock Honda writing or recovery. A candidate ID, checksum and matching bytes do not prove a vehicle, complete flash contents, XDF fitment, engine safety or writing compatibility. Keep original files and logs private. Stable power and a stopped engine are essential for any ECU work.

## What was added

The existing desktop ECU-only, physical K-Line research profile can attempt these additional source candidates using one explicit research read. It uses the two fixed source security messages, then sequential 128-byte requests starting at zero, validates the framing and exact response length, ID at the sample-observed offset and zero byte sum, and saves only a **research** image. After one successful read the desktop automatically opens the source-named candidate XDF for map review; it preserves any already staged edits instead of replacing them, and warns that the 701 filename and title conflict. This handoff never authorizes writing. Failure produces no image. The source reader begins at 128 bytes and decreases size on failures; this integration fails rather than automatically retrying at a smaller size. Read replies do not echo the requested address; sequential association is assumed. Logs may include raw image data.

| Source candidate (not definitive identification) | Live ID | Observed sample-file ID offset | Sample length | Source checksum byte |
|---|---|---:|---:|---:|
| 2010–11 VFR1200F 38770-MGE-773 | `01 00 AA 05 01` | `0x36B57` | 1 MiB | `0x7FFF8` |
| 2010–11 VFR1200 Japan 38770-MGE-701 | `01 00 AA 06 01` | `0x36B7F` | 1 MiB | `0x7FFF8` |
| 2013–16 VFR1200F 38770-MGE-D41 | `48 01 01 19 01` | `0x3A563` | 1 MiB | `0x7FFF8` |

The `keihinaddr` in the source ID table is `0x36B57` for all three, whereas the 701 and D41 source-named examples contain the respective ID at the different offsets above. The sample locations, origin, zero read start and 1 MiB extent are assumptions for this integration. All three stock files have an all-`FF` second 512 KiB; this is not proof that a live read returns padding, a complete backup, or that an ECU's flash is 1 MiB. Source example firmware is **not distributed**. A fourth `48 08 01 19 01` VFR1200FD entry has unknown part number and no matching named example; it is not included in the reader.

The separately distributed XDFs from [AlexKovalevich/HondaECU at db0a6cb8](https://github.com/AlexKovalevich/HondaECU/tree/db0a6cb8e516aac2406a231380c93e258c722b7c) are unchanged and marked research-only. They parse as 45 (773), 46 (701), and 45 (D41) tables plus two constants each. **The 701 filename conflicts with its embedded 773 title**; do not assume its maps match 701. The D41 XDF names a 2013 German variant. No declared XDF checksum is parsed. The repository provides GPL-3.0; the license is retained in `LICENSES/HondaECU-GPL-3.0.txt` and provenance/hashes are in `guzzionboard/xdfs/PROVENANCE.json`. In the [author's VFRworld guide](https://vfrworld.com/threads/vfr1200f-2010-2011-ecu-reflash-diy-free-xdf-interested-here-is-how.59008/) Alex Kovalevich identifies himself as the XDF author, says he released it free, and reports using his fork to read and reflash a 2010–11 MGE-773; he states he did not test automatic checksum fixing. This is a source report, not a GuzziOnBoard hardware test or a claim for every VFR.

For offline research in Tools, choose the exact candidate, the original and a separately edited 1 MiB image. The tool requires the source-observed IDs and zero original sum, reviews hashes and the count of changed non-checksum bytes, and can explicitly save a new copy with the byte at `0x7FFF8` adjusted so the whole-file byte sum is zero. It doesn't alter either input. Changing only the checksum is rejected. A zero sum does not validate any other checksum, signature, maps, completeness or safety. For existing files this manual tool requires file selection; the desktop Maps research preview also offers an integrated checksum-adjusted export for matching candidates, described below.

## Why there is no GuzziOnBoard write

The author reports a successful 773 write using **his fork**, unlike the separate WiseNoodle suite, which explicitly marks its own writer broken. We inspected actual code rather than treating that statement as universal. The fork's `src/threads/kline.py` and `eculibDistrib/eculib/honda.py` contain a five-command `7D` write initialization, 14-second wait, `7E` erase commands and `01 05` status poll, 128-byte `01 06` blocks in 16-byte address units with two data checksums, a zero next address for the last block, `01 08` status and `01 09/0A/0C/0D` post-write steps. But the worker can continue to write after erase failure, and its 5-byte block reply handling stops early on a status value of zero. [aeaphichart/HondaECU-1 at b59ae98b](https://github.com/aeaphichart/HondaECU-1/tree/b59ae98baf092def23d7c34d5ef5f43bd6aba952) has different erase/wait behavior and accepts both 5-byte and address-checked 7-byte replies, with optional 64-byte fallback. The precise meanings and success/failure transitions of the shorter acknowledgments and post-erase recovery are not established by these sources or a captured session here. Blindly guessing them could turn a reported successful source workflow into a destructive failed implementation. No write-initialization, erase or write commands are enabled in this profile (the read-specific security exchange is still sent), and no synthetic test is represented as verification of missing wire semantics. Further work needs source-level resolution or a real trace for the exact ECU and a fail-closed recovery procedure.

## Broader Honda work (source IDs, checksum and map handoff)

The ECU-only research reader also offers two source-table entries with no independently checked example: **MGE-D02** (`01 00 AA 01 02`, ID file offset `0x7FF5C`, 1 MiB source model size) and **MFJ-D42** (`01 00 7C 01 02`, ID file offset `0x25439`, 256 KiB source CBR600RR family size), from [aeaphichart/HondaECU-1](https://github.com/aeaphichart/HondaECU-1/tree/b59ae98baf092def23d7c34d5ef5f43bd6aba952). Their metadata says table-only, not sample verified. Like the other readers, a bounded zero-start read and zero file sum are assumptions, and an unsuccessful read saves nothing. Both use eight-byte requests; D02 takes 131,072 requests. The same source contains additional ID-only entries without ROM geometry or image ID positions; this reader does not invent them.

The desktop can automatically open a source-named research XDF after one successful research read for 18 candidates: the three MGE entries above; five 2006–07 CBR1000RR MEL entries; four CB500 MGZ entries; MJW-AQ1; KYK-D12; K0F-A01; and K26-911, B13 and C31. Existing staged map edits are preserved instead of replaced. This is discovery, not automatic fitment confirmation. The MGZ definition's default byte order conflicts with the A03 example; the 701 filename conflicts with its title; some definitions contain unsupported elements; K26 read starts are inferred. Review actual source, offsets, axes, scaling and warnings before using any of these maps.

The offline Honda checksum tool covers **44** source candidates for which a nonzero file checksum location is explicitly listed in the pinned aeaphichart or Alex tables. It requires both the original and edited files, source- or sample-derived image size, matching ID bytes at the stated file offset and a zero original whole-file byte sum. It reports the source, offset basis, hashes, difference count, and proposed one-byte adjustment, then explicitly exports a new research-only copy. For K26-911/B13/C31, checksum positions `0x9FFF`/`0x5FFF` are **file offsets** from the Alex table, not asserted physical addresses; the aeaphichart table instead lists zero. MFL-773 is commented in aeaphichart but active in Alex's table; the conflicting status remains visible. Sixteen other read candidates lack an explicit nonzero checksum location for that ID and are not added by guesswork. Of the 44 checksum candidates, source-named images matching ID/size/zero sum were inspected for 41; two are the table-only entries above, and MKF-L13 table ID has a conflicting named file. No firmware images are distributed. A zero sum does not establish completeness, software fitment, tuning safety, signature validity or permission to flash.

### Further protocol comparison

[roccofz1/HondaECU at dbb8d37b](https://github.com/roccofz1/HondaECU/tree/dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109), GPL-3.0, is an earlier related implementation, not an independent capture. Its writer accepts a five-byte block response by length, does not interpret the block status, and sends `01 08` after every other block; the Alex fork stops on status zero and sends `01 08` after the loop. The later aeaphichart fork accepts five-byte responses or seven-byte next-address responses and differs again in status/waits. These are materially different behaviors; none here establishes how to distinguish every success, duplicate, or failure response on the targeted ECU. `do_post_write` in the Alex library expects final status `0x0F`, not simply any valid frame. Its worker also proceeds after failed erase, which must not be copied. The separate josave-tuner repository inspected at `2ac0fdeb679736271bf12fe210b578683d092aa2` supplies a virtual ECU simulator; its writer constructs a different three-byte address packet, does not check both unlock results or post-write result, and its tests exercise that simulator. No repository license was found. It is not evidence resolving these disagreements and no code was copied. Source-reported successes of other applications remain distinct from GuzziOnBoard's synthetic-only integration; the application still does not send Honda flash erase/write/recovery commands.

## Additional source-example candidates

The 60-ID research reader includes eleven more candidates identified from unique matching five-byte sequences at the previously observed family file offset in source-named examples; each example has the indicated length and zero byte sum. These IDs were not accepted as active, matching ID/part associations in the source table. They have **not** been tested on a physical ECU; a unique sequence, filename and checksum do not prove the live ID, fitment, firmware completeness or protocol. For each, zero read start and source-example length are assumptions. No example firmware is distributed.

| Named example candidate | ID bytes at family file offset | Size |
|---|---|---:|
| MFL-691 | `0100B00401` at `0x2880A` | 256 KiB |
| MFL-861 | `0100B00501` at `0x2880A` | 256 KiB |
| MFL-871 | `0100B00801` at `0x2880A` | 256 KiB |
| MFL-F21 | `0100B70301` at `0x2880A` | 256 KiB |
| MFL-L21 | `0100B70501` at `0x2880A` | 256 KiB |
| MKF-L13 example | `0102480501` at `0x7C745` | 1 MiB |
| KPP-602 | `0101110F01` at `0xC3CC` | 56 KiB |
| MJW-DR1 | `0102F20111` at `0x18BB7` | 256 KiB |
| MFJ-A02 | `0100330401` at `0x280B5` | 256 KiB |
| MJE-T15 | `01014E0D03` at `0x15F72` | 256 KiB |
| MJE-T52 | `01019C0D02` at `0x15F72` | 256 KiB |

The five MFL filename associations conflict with the source's commented ID/part alternatives, which remain unresolved. MKF-L13's active ID table instead says `0102490501`. The reader also offers this table ID as a distinct, twelfth candidate, assuming the D43 family offset `0x7C745` and 1 MiB length; there is no matching checked image for it. Both MKF-L13 ID candidates report the conflict. Their 1 MiB attempts each require 131,072 eight-byte requests. None of the eleven example-only entries receives a guessed checksum correction byte. The table-ID MKF-L13 is offered a `0xFFFF8` checksum byte from the source table, still with the explicit ID conflict and inferred layout warning.

### Desktop map-edit checksum handoff

In the desktop Maps research preview, source bytes of a listed file size and
ID position, an unchanged ID in the edited candidate, and a zero original
whole-file byte sum can now surface the corresponding source-listed checksum
candidate automatically. The preview shows its ID basis, read-start assumption,
source conflicts, checksum-byte change, and corrected SHA-256. An explicit
confirmation exports a separate edited, checksum-adjusted research copy and a
manifest, using the reviewed source, XDF and raw/corrected candidate hashes.
The original is never overwritten. Only source-listed checksum offsets are
used; the eleven example-only IDs do not get invented offsets. Matching file
bytes are **not** proof of ECU identity, fitment, completeness, or flash
readiness; other checksums and signatures are not verified. No ECU is
contacted. Python and desktop browser tests use synthetic files, not hardware.
The independent manual Honda checksum review remains available.

### Further writer-source search

A later code-level search did not resolve the acknowledgment question.
[Cyclegadget/HONDAECU_2.1 `fccb3106`](https://github.com/Cyclegadget/HONDAECU_2.1/tree/fccb310639daa48e9d0731d098087c7a92f9726e)
modernizes the related aeaphichart code and retains its 5-/7-byte reply handling,
64-byte fallback, and erase gate. It is not an independent wire capture. Its
helper also sets its return value to success after calling `do_write`, without
propagating that function's result. No physical GuzziOnBoard test follows from
this code. [KOOD2003/honda-flasher `8bc4c9f5`](https://github.com/KOOD2003/honda-flasher/tree/8bc4c9f5c989ca15246d482c632371ba505173f4)
contains a WebUSB HTML file that ends inside the `Flasher` constructor; despite
its on-page simulator claim, the checked file does not contain the actual flash
sequence or tests, and its adapter warning says hardware was not tested. No
license was found, and no code was copied. The
[eydgv499-sketch/hondaecuflasher iOS starter `53e08c29`](https://github.com/eydgv499-sketch/hondaecuflasher/tree/53e08c290fb96a8fcb171cc973ab0627de49142c)
ZIP states that real flash and K-Line logic are missing and supplies a simulated
transport. [KaracaPK/Honda-Ecu-Flasher `a157a9ee`](https://github.com/KaracaPK/Honda-Ecu-Flasher/tree/a157a9eecf94749c08e51f377da0ecd8a149a1de)
contains only an opaque `ecuData.dat`; no protocol code was established. These
findings concern the inspected versions, not every other tool or fork.
