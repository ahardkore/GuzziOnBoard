# Buell DDFI serial research

## What is implemented

**Tools → Buell DDFI · live serial research** is a narrow serial path for
compatible Buell DDFI-family controllers. It is separate from Harley J1850 and
CAN: use a Buell-compatible TTL interface or a properly paired Bluetooth serial
adapter, not an ELM327 or a direct RS-232 connection. EcmSpy specifies TTL
levels, **5 V maximum**, 8 data bits, no parity, one stop bit and no flow
control. Check connector, adapter voltage, power, ground and wiring for the
specific bike; opening the serial port can change control lines.

The operator selects stock/P&A (9600 baud, destination `0x42`) or factory race
(19200 baud, destination `0x55`); these settings come from EcmDroid. Do not infer
which protocol applies solely from the word “race” on the case. Identify uses
the `0x56` version request and checks response framing, addressing, status,
length and XOR checksum. Runtime (`0x43`) and EEPROM page GET (`0x52`) repeat
identification and require an exact match with the version shown previously.
The available runtime output is the raw response payload. Only when the version
starts `BUEIA` and the frame is exactly 100 bytes, selected RPM, throttle,
battery voltage, engine temperature and air-temperature **candidates** are
shown using the source ADX offsets/scaling; 16-bit values use EcmDroid's
little-endian convention. This interpretation is synthetic-tested, not
hardware-validated. Other versions and lengths remain raw, not misdecoded.
Never use these values to make riding or safety decisions.

EEPROM range GET reads an operator-selected range within pages 1–31, no more
than 256 bytes per operation and no crossing a page boundary. For the **image**
action, source-derived layouts are available for 19 ECM ID prefixes:
`BUEGC`, `BUEIA`, `BUEJA`, `BUEKA`, `B2RIB`, `BUECB`, `BUEGB`, `BUEIB`,
`BUEIC`, `B3R1D`, `B3R2D`, `B3R3D`, `BUE1D`, `BUE2D`, `BUE3D`, `BUEOD`,
`BUEWD`, `BUEYD`, and `BUEZD`. These are ECM IDs, **not** 19 newly
verified motorcycle fitments. The full previously identified version must match
again before any data GET. Normal pages are read in chunks of at most 16 bytes;
page zero, if present, is read a byte at a time from the high end of its page.
Normal pages are concatenated in ascending order and page zero is appended,
matching the source XPR EEPROM image layout. A successful local image read
automatically saves a binary `.xpr` original under the app data directory's
`buell-backups/` and opens write review. Its path can be used as Maps input.
The separate save button also exports/downloads an XPR. A SHA-256 is displayed.
If automatic saving fails, the read is still displayed and can be exported,
but no single-read write evidence is created.
Read actions send no service-page (`0x20`) requests or SET/write requests.

One read is sufficient; optional repeated comparison reads the entire image
twice and discards the result if any bytes differ. Any malformed/short reply
also discards the operation. Replies do not echo the requested address, so even
equal repeated responses cannot rule out delayed/stale data. An identified
version is not authentication, and these layouts do not prove a particular
bike fitment or guarantee the data is a verified backup. The image covers the
source-described EEPROM, **not full ECU firmware**. Treat calibration data as
sensitive; review before sharing. Read actions send no actuator tests, resets, fault clears,
writes or memory modifications.

## Source-derived maps and experimental live writes

Thirteen bundled XDFs cover front/rear fuel and spark tables and their axes for
all 19 listed IDs; some IDs share the same source geometry. They are derived
from XBTune's EcmDroid definitions, not from the user's ECU. In desktop
**Maps & tables**, clear **Only definitions for this ECU** if necessary and
select the XDF whose title lists the ID. Enter the saved original XPR path and
address base `0`, render, stage edits, then **Preview edits for research** and
export a separate research copy using the declared file range. The XDF, file
size, filename and ECM ID alone cannot authenticate identity or fitment. The
research copy is not certified flash-ready: its manifest records no checksum
or signature repair. Keep the original unchanged.

**Tools → Buell DDFI → Experimental Buell fuel / spark EEPROM write** provides
a separate, explicitly confirmed, source-scoped live SET path for these maps
and axes. It does not use the normal firmware programming gate, write page zero,
accept edits to other EEPROM variables, issue service-page commands, erase, or
flash full firmware. SET resends entire affected chunks, including unchanged
neighboring EEPROM bytes; those bytes come from the immediately preceding
live chunk read. This is a **new synthetic-tested implementation, not hardware-tested**.
Wrong values, wiring, voltage, interruption or protocol behavior can permanently
damage the ECM. Confirm the actual bike, ECM ID and full software version,
source definition, edited values, stable power, adapter and ignition state.
Do not use a different ID merely because the image has the same length.

1. Identify the ECM and read its source-layout XPR once. The desktop saves the
   original and opens the write panel. Use its path in Maps with the matching
   XDF, review the results and export a separate edited image. The original and
   edited files must have the exact source-described image length; only bytes
   in the four maps or their axes may differ. Row padding, page zero and
   unrelated EEPROM bytes cannot be changed. The filename beginning with the
   ECM ID is a convenience check, not proof of origin.
2. Enter the edited file path in the Buell write panel, check the acknowledgements,
   and review byte offsets, before/after bytes and SHA-256 hashes. This review
   sends no serial traffic. A server-held token binds the exact read bytes,
   serial device, mode, version and original path; the saved file must still
   match. The reviewed immutable plan expires after five minutes and is one-use.
   Editing the target after review does not change the held plan. Another Buell
   operation invalidates the evidence and plan; an authorized write attempt
   consumes both. A restart also loses the in-memory evidence.
3. After final live-write confirmation the app verifies the saved original,
   reconnects and checks exact version and stopped RPM. It **does not read a
   second full image** in this path: it prechecks every affected normal-page
   chunk against the original before any SET, then rechecks each chunk and RPM
   immediately before its SET, preserving unchanged neighbors from that live
   chunk, and reads back each written chunk. No SET is retried automatically.
   Version is not unique identity; an ECM swap with the same version and chunks,
   or changes outside those chunks, can go undetected. Responses do not echo
   addresses. Optional repeat comparison is a second full image read.
4. A mismatch detected after an earlier SET, timeout, rejection, readback
   mismatch, power failure or disconnect after a SET leaves an **uncertain,
   possibly partially written ECU**. Do not retry blindly; the error reports the
   saved original when available. There is no automatic rollback or recovery.
   Matching readback does not prove reply-address association, calibration
   suitability, safe operation, or immunity to ECM-internal changes. A saved
   original or repeated read is not independent validation.

The older explicit-file API remains available: it requires an ID-prefixed
original path and makes a fresh full-image backup before writing, rather than
using the single-read evidence. Both paths retain the same map/axis limits and
confirmation requirements.

The normal firmware builder still blocks research-only XDFs; the operator-
declared research export and this purpose-built, limited EEPROM writer are
separate. The hosted demo does not access hardware. The app does not test or
repair checksums or signatures. Synthetic tests cover framing, fresh backups,
comparison, one-use plans, no-write errors, uncertain failures and readback,
not an actual motorcycle or adapter. Rebuilding the 12 additional XDFs requires the externally obtained, hash-pinned
XBTune TOML: `scripts/build_buell_xdfs.py`; the earlier BUEIB adaptation is
maintained separately. The full upstream database is not bundled.

## Sources, attribution and limitations

* [EcmDroid `2f17d29`](https://github.com/bkp123/ecmdroid/tree/2f17d29f5b08f67fb357ee8f2ec21e7ae930343e)
  describes Buell DDFI/DDFI-2/DDFI-3 serial diagnostics, version, runtime,
  EEPROM GET and separate writes. The read-only PDU framing is adapted from
  `PDU.java` and `ECM.java`, Copyright (C) 2012 Michel Marti,
  GPL-3.0-or-later; see `LICENSES/EcmDroid-GPL-3.0.txt`. GuzziOnBoard's AGPL
  distribution must retain attribution, applicable license terms and source.
  No complete EcmDroid database, calibration, APK or firmware is bundled; selected source-derived page and map geometry is included as described below.
* [EcmSpy EEPROM and serial protocol](https://www.ecmspy.com/eeprom_info.shtml)
  describes DDFI-2 page geometry, messages and hardware. Its pre-2008 layout
  must not be applied automatically to DDFI-3. The requested runtime command
  and live data are not a firmware image or an ECU flash protocol.
* [BUEIA V5 ADX/XDF source at `61136c6`](https://github.com/Snoman002/Engine-Tune-Repository-TunerPro-EFIlive-TunerCat/tree/61136c6d0d59506d60a01b4ff7176679d9903fd4/Buell/BUEIA_ECU/Software)
  supplies an ADX describing 9600-baud identification, runtime requests, a
  100-byte runtime frame, and value offsets. The repository has no root
  license and the files identify EcmSpy author Gunter Baumann. They are not
  redistributed. The XDF's title is `BUE1D` while its description says
  `BUEIA`; resolve the definition's identity/fitment before using it. The
  existing research map workflow can use a separately acquired user XDF and
  an appropriate raw image, but it cannot derive complete geometry or validate
  checksum/fitment from this source. The separate source-derived writer described above uses the bundled XBTune/EcmDroid map definitions instead.
* [Original HarleyDroid `0268f3c`](https://github.com/stelian42/HarleyDroid/tree/0268f3cbfe4432b6f5b1e911181aea6c1181d5b9)
  documents Harley J1850 trial-and-error broadcast decoding, not Buell DDFI
  serial EEPROM commands. GuzziOnBoard already supports source-scoped live
  Harley J1850 diagnostics and offline decoding via the EVO fork. Its original
  and fork disagree on some value interpretations; see `HARLEY_TUNING.md`.
* [2017 Sportster CAN research `835a1bc`](https://github.com/earnaz/Harley-Davidson-CAN-Bus/tree/835a1bccb1cdee0369e120f4a134fbb0bde3564d)
  is already integrated as the explicit Sportster raw CAN observation profile,
  not ECU tuning or a blanket fitment claim.

The protocol, serial device, runtime fields and UI were tested with **synthetic
fixtures only**. No physical Buell ECU or adapter was tested. Source-reported
capabilities are not a claim that this integration has full tuning, fault
reading, a verified backup, checksum repair, complete EEPROM writing, or recovery support.

## XBTune geometry, attribution and repeat comparison

[XBTune `c592b11`](https://github.com/kz6fittycent/XBTune/tree/c592b11b17e1a3cd5f55f8bc726f2890d892d63b)
contains source-described DDFI EEPROM reads, editing and guarded burning. Its
Rust code is GPL-3.0-or-later, with EcmDroid attribution. The 19 ID/page-length
facts and selected BUEIB/BUEIC/B2RIB map geometry in GuzziOnBoard are adapted
from `data/ecmdroid.toml` (GPL-3.0), which XBTune attributes to the EcmDroid
`ecmdroid.db` and ultimately ECMSpy. XBTune's `docs/PROVENANCE.md` reports
permission to publish on 2026-10-22, while the generated TOML header still
contains an older "do not publish until permission is confirmed" notice. We
rely on the later provenance statement; the full database is not redistributed.
The GPL text is in `LICENSES/EcmDroid-GPL-3.0.txt`; distribution of this
combined AGPL work must retain the applicable notices and source obligations.

XBTune reports a physical 2005 XB9SX/BUEIB test and simulator tests for other
ECMs. That does not test GuzziOnBoard. GuzziOnBoard's implementation, XDF and
UI have **synthetic tests only**; optional comparison cannot prove address
association, geometry, fitment, backup completeness, write compatibility or
safety. XBTune supports a broader guarded burn, including selected page-zero variables; GuzziOnBoard implements only the limited normal-page map/axis-difference writer described above. Its SET requests resend whole affected chunks, including unchanged neighboring bytes.

### Single-read Maps-to-write handoff

After a successful image read and saved single-read evidence, the desktop now
opens the ID's bundled source-derived XDF against that original in Maps. It
supports the 19 IDs in the existing writer mapping, including shared-geometry
aliases. A button switches to the prepared map; if staged edits already exist,
they are preserved and the handoff can be retried after clearing them. Review
fitment and every value before staging. Previewing the edits offers an explicit
**Save reviewed copy for Buell write review** action. This saves a separate
research copy and manifest and fills its path in the Buell panel without sending
SET; the normal write review still enforces source map/axis byte bounds and the
page-zero exclusion, and a separate explicit confirmation is required to write.
Changed read selections or in-progress manual path edits prevent a stale handoff
from replacing the target. A matching XDF name, ID or image hash does not prove
ECM identity, fitment or tune safety. Browser tests use synthetic images and a
mock ECU API; the live protocol remains synthetic-tested, not hardware-tested.
