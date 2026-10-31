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

EEPROM GET reads an operator-selected range within pages 1–31, no more than
256 bytes per operation and no crossing a page boundary. Each request is at
most 16 bytes, and an invalid response causes the entire result to be discarded.
Page zero and `0x20` and higher are excluded. The other page numbers and sizes
are **not automatically verified**; EcmSpy documents variable page sizes, and
DDFI-3 layouts differ from earlier ECMs. Use the correct ECM-specific geometry.
Replies do not echo the requested page or offset, so serializing requests and
checking frames cannot prove that a delayed/stale reply is associated with the
current request. A version string is not authentication and does not prove page
geometry. A partial page is not a verified full backup, is not shared as validation, and
must not be treated as flash-ready. ECM versions and calibration data can be
sensitive; review before sharing. No writes, actuator tests, resets, fault
clears, page-zero/service requests or memory modifications are sent.

## Sources, attribution and limitations

* [EcmDroid `2f17d29`](https://github.com/bkp123/ecmdroid/tree/2f17d29f5b08f67fb357ee8f2ec21e7ae930343e)
  describes Buell DDFI/DDFI-2/DDFI-3 serial diagnostics, version, runtime,
  EEPROM GET and separate writes. The read-only PDU framing is adapted from
  `PDU.java` and `ECM.java`, Copyright (C) 2012 Michel Marti,
  GPL-3.0-or-later; see `LICENSES/EcmDroid-GPL-3.0.txt`. GuzziOnBoard's AGPL
  distribution must retain attribution, applicable license terms and source.
  No EcmDroid database, calibration, APK or firmware is bundled.
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
  checksum/fitment from this source. It does not write this Buell ECU.
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
reading, a complete backup, checksum repair, writing, or recovery support.
