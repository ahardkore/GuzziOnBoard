# Harley Delphi offline calibration-region workspace

## Source and fitment

[HarleyECUTool, in rob9206/lawflo, commit
`6255518dc9118d960efa42d6d9dc975926bbd579`](https://github.com/rob9206/lawflo/tree/6255518dc9118d960efa42d6d9dc975926bbd579/ZOOSH_ECU-main/HarleyECUTool)
describes Delphi ECUs in roughly 2014–2020 models. It describes a 160 KiB
calibration read at `0x7D8000` and a 16 KiB tune at offset `0x1C000`
(corresponding to read address `0x7F4000` and source-reported write address
`0x4000`). The repository has an example calibration and extracted tune;
we compared the bytes and confirmed that the example's 16 KiB region matches
its extracted file exactly. No firmware, customer files, VINs or authentication
payloads are distributed here. That one example does not establish compatibility
of the mapping with every Harley model, ECU, or software revision.

The source also describes CAN/ISO-TP read and write tooling. Its wiring
instructions differ between the ECU Dump and ECU Tool subprojects, and the
sample dump metadata leaves part number and serial blank. It uses a
vehicle-specific authentication payload; its SHA-256 verification is a file
integrity check, not a documented calibration checksum algorithm. Source code
has an MIT text **and** a personal/educational-only disclaimer; no code or
firmware was copied from it. Another source,
[Harley-Davidson-TC265](https://github.com/jakka351/Harley-Davidson-TC265/tree/f4aa1e3197da9d21e95b90cf7dc762c694410356),
notes security, secondary bootloader and read/write services but does not
provide complete steps in its README and has no detected license.

## Using the workspace

In **Tools → Harley Delphi offline calibration-region workspace**, explicitly
select this layout, choose a raw 160 KiB calibration or 16 KiB tune, and
inspect it locally. Optionally select a second file of either size to compare
tune-relative byte ranges. For a 160 KiB first file the tool can export a new
16 KiB research copy, with both the source and region SHA-256 displayed. You
can also select a 16 KiB replacement as the second file, explicitly confirm
it is the intended replacement, inspect the differences, and export a new
160 KiB research calibration with only the tune region replaced. Source,
replacement, and output hashes are displayed; neither input is modified. This
does not verify that the replacement originated from the source calibration.
The desktop host saves exports without overwriting an existing file; the
browser downloads them. Files are processed in the
page, not uploaded to a remote service; the desktop export is sent only to the
local host. Tool containers such as Centurion `.ori` are not interpreted.

**This is not full Harley tuning.** File size and SHA-256 do not identify a
bike or establish calibration integrity, compatible table definitions,
checksums, signatures or a safe tune. The exported region has no checksum
correction, and must not be treated as flash-ready. This feature does not send
frames, read or write a physical ECU, or bypass existing programming gates.
A matching definition, ECU-specific authentication/session implementation,
calibration checksum/signature handling, robust read-back and recovery behavior
are still needed for an integrated tuning and programming workflow.

## Additional diagnostic capture profiles

[HarleyDroid EVO](https://github.com/QuickosssLabs/HarleyDroidEVO/tree/668b63efc05977eb65cb8e84e597ae2205355d4c)
provides J1850 diagnostics and a separately documented, **best-effort**,
passive CAN/HDLAN telemetry decoder. Copyright (C) 2010–2012 Stelian Pop
and (C) 2026 Quickosss; GPL-3.0-or-later. The adapted code is included in
the AGPL combined work; see `LICENSES/HarleyDroidEVO-GPL-3.0.txt` and
provide corresponding source and applicable license terms when distributing
or offering the combined work over a network. Contributing upstream is not
required.

* **Tools → Multi-brand offline capture research → Harley J1850** decodes
  complete CRC-valid frames. HarleyDroid reports trial-and-error captures on
  Harley bikes, notably Sportster; this integration has not been tested on a
  bike. VIN, part number and calibration ID are shown as individual fragments,
  not assembled across unrelated captures. DTC current/historic status is not
  assigned: the original and EVO versions interpret the address differently.
  The original README describes temperature as Fahrenheit, whereas the code
  and EVO use raw minus 40 °C. Gear is raw only because the original documented
  lookup differs from the implemented shift count. The EVO test calls bytes
  `41 51` C1151, but its code's packed-code conversion gives C0151; this
  implementation follows that conversion (`51 51` gives C1151).
* **Discovery → CAN identifier discovery → Harley HDLAN community** decodes
  the source's speed, odometer, temperature, clutch, neutral and tentative RPM
  candidates from captured standard data frames. The source explicitly says
  the layout is best-effort and varies with model/year; no gear estimation is
  included. Both capture tools preserve raw bytes, are opt-in, and do not
  connect, transmit, identify the bike, read faults live, or clear them.

The separate [2017 XL1200X Sportster Forty Eight CAN research](https://github.com/earnaz/Harley-Davidson-CAN-Bus/tree/835a1bccb1cdee0369e120f4a134fbb0bde3564d)
reports some matching IDs, but is not a blanket fitment claim. Neither
capture profile enables Harley tuning or memory programming.


## Live J1850 diagnostics (desktop and local workstation)

The separate **Harley J1850 / HarleyDroid (read-only research)** profile
implements a narrow live diagnostic path based on the same pinned GPL
HarleyDroid EVO source. In Garage, select a source-listed Harley model/year or clear the model and choose the ECU-only override, then choose **Harley J1850
(ELM327 serial)** and **read-only**, and enter the explicitly addressed
serial port. [Dynojet’s J1850 product list](https://www.dynojet.com/harley-davidson-power-vision-delphi-j1850-black-1/) lists these model/years for fuel-injected Delphi ECUs; it does not establish compatibility of our separate integration. Some years may include carbureted or different-ECU variants: verify the bike, fuel injection, ECU and wiring. These vehicle attempts are synthetic-tested only and not hardware-verified. Install `pip install -e '.[hardware]'` if the ELM transport is
unavailable. The ELM327 serial interface is configured at **38400 baud**,
8N1; paired Bluetooth serial ports can be used if the operating system exposes
them as a serial device. Raw Wi-Fi ELM sockets and J2534 are not implemented.
Use the correct adapter, diagnostic connector, wiring and power supply for
the particular bike; source projects do not establish universal fitment.

ELM initialization selects VPW with headers on. Setup confirms the **adapter**,
not a responding ECU. Identification requests only the source-defined part
number, calibration ID, VIN and software-level fragments; an identity is shown
only when at least one complete CRC-valid field is returned. Live RPM, speed
and candidate engine temperature come from bounded passive monitor windows;
missing or corrupt frames are shown as missing, never reused as fresh values.
The temperature unit differs between original source documentation and code;
treat it as a candidate. DTC requests target the source's ECM, ABS and TSM
addresses. The display identifies which modules responded, and does not infer
that missing modules are clean or label a fault current/historic. For matching
codes it also displays a source-labelled reference description from the
HarleyDroid EVO English DTC list (167 codes, GPL-3.0-or-later); descriptions
are leads, not verified fitment or a diagnosis. Unknown codes remain unlabeled. A verified
response with a zero code is not a complete health assessment.

The transport allows only its fixed setup, the named identity/DTC requests and
passive monitoring; no generic frame send, fault clearing, output control, memory
read or programming is available. It closes the link when the adapter loses
its prompt. These tests use synthetic adapter responses; this integration has
**not been tested on physical hardware**. The source reports model-dependent
behavior, notably Sportster, and CAN/HDLAN bikes require a different path.
Do not connect this profile to a model without confirming the actual bus and
adapter wiring.

## Definitions and commercial alternatives

[OldSkullTuning](https://oldskulltuning.com/tunerpro-maps-for-all-harley-davidson-with-ecu-delphi/)
advertises Harley Delphi J1850 and CAN XDF definitions. These are commercial
third-party definitions; they are not bundled and the seller's coverage claims
have not been validated by this project. The existing map editor can inspect
user-supplied XDFs, but merely loading one does not establish that it matches a
particular ECU/image or enable flashing. [BitBox Harley-Davidson Delphi
Module](https://chiptuningshop.com/product/bitbox-harley-davidson-delphi-module/)
advertises reading, writing and checksum correction for MT05 CAN and VooDoo CAN;
it is a separate commercial tool, not an algorithm or protocol implementation
provided here. Neither establishes a reusable checksum algorithm for the
HarleyECUTool 16 KiB region. The local checksum-plugin framework is available
for a suitable user-supplied provider, but no Harley calibration checksum
provider or validated matching Harley definition is bundled.

## Live CAN broadcast observation (local Linux workstation)

**Discovery → Harley HDLAN · live CAN observation** reads bounded two-second
windows from an existing Linux SocketCAN interface after explicit confirmation.
Configure the correct bitrate and adapter/wiring in the operating system first;
the application neither configures the interface nor sends CAN frames. A normal
CAN controller may still electrically acknowledge traffic: if true silent bus
monitoring is required, configure and verify the adapter/controller's
listen-only mode independently. Adapter support and permissions vary; this
feature is unavailable in the hosted demo and is not an ELM327 CAN session.
Stopping the monitor prevents further windows; an already-running window can
take up to two seconds to finish and its result is discarded. The monitor also
stops when the page is hidden or its interface/profile changes. It keeps only
the most recent matching frame per ID in each window and never carries a missing
value forward. Raw bytes remain visible.

Two explicit mapping choices are supplied:

* **HarleyDroid HDLAN community** uses the GPL best-effort candidate mappings
  already described above. Speed, odometer, temperature, clutch, neutral and
  tentative RPM depend on model and year, and these broadcasts do not identify
  the bike. No gear is estimated.
* **2017 XL1200X Sportster** follows reported observations in
  [earnaz/Harley-Davidson-CAN-Bus at 835a1bcc](https://github.com/earnaz/Harley-Davidson-CAN-Bus/tree/835a1bccb1cdee0369e120f4a134fbb0bde3564d),
  copyright 2023 Chrisisbrown, MIT (`LICENSES/Harley-Sportster-CAN-MIT.txt`).
  It exposes raw throttle-frame and battery-frame bytes and narrowly recognized
  switch/stand patterns, not percentages, volts or complete switch semantics.
  Unknown patterns stay unknown. The source reports observations on one bike;
  selecting this option is a user assertion, not vehicle detection.

These are passive candidate broadcasts, not verified instrumentation, and must
not be used for riding or safety decisions. No fault queries, ECU memory,
security, calibration writing or other diagnostic requests are sent. This
integration has synthetic tests only, with no physical Harley testing.

## Live Delphi CAN identity and raw DID research

In Garage, select a source-listed Harley model/year, or use the ECU-only override **Harley Delphi CAN (identity research)**. Select CAN and read-only mode, and specify a CAN channel. [Dynojet lists these models](https://www.dynojet.com/harley-davidson-power-vision-delphi-can-black-1/) for its Delphi CAN product; that fitment list does not establish that this separate implementation or its fixed DIDs work on any particular motorcycle. This integration is synthetic-tested only. On Linux use an
already configured SocketCAN channel such as `can0`; for a PCAN adapter use a
python-can PCAN channel such as `PCAN_USBBUS1` with its driver installed.
The profile is restricted to 500 kbit/s, physical `0x7E0`/`0x7E8` and zero
padding. The DID source describes Delphi ECUs approximately 2014–2020; Dynojet’s product fitments include additional 2011–2013 and 2021–2022 models. Those extra model-years use the same experimental default-session requests, with no GuzziOnBoard hardware validation; ECU protocol and response layouts may differ. Selection does not establish the actual ECU or software revision.

The connection requires a matching `3E 00` / `7E 00` tester-present response;
that confirms only a responder. The Identify action attempts the source's
five fixed identity DIDs (`F1EA`, `F1ED`, `F1F5`, `F1F2`, `F1EF`), displaying
successful responses as **raw candidates**. The source's example metadata
has blank part and serial fields and its tool reads DIDs after authentication;
this default-session attempt can be refused or time out. A negative or absent
reply is not a confirmed identity. Successful candidate values are not used
as the programming gate's identified or hardware evidence. DIDs and session
logs may contain sensitive identification information.

The Live view offers four fixed raw DIDs (`0100`–`0103`) observed in a source
capture. Their units and semantics are unknown, so the app shows only the raw
bytes and their big-endian integer representation. Each has the captured length
checked; no sensor interpretation or safety state is inferred. Other arbitrary
DIDs, security, session changes, resets, fault clear, memory operations and
writes are refused. The source's memory-read path actually requires an opaque,
vehicle-specific transfer payload sent using **RequestDownload (`34`) and
TransferData (`36`)**, not merely a passive read. We do not treat that as
read-only, nor replay a proprietary payload or claim it works across Harleys.
The published sample does not establish target identity, firmware compatibility
or checksum/recovery requirements for a safe flash. This integration has
synthetic tests only and has not been tested on physical hardware.
