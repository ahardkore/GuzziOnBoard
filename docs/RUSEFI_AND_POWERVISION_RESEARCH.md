# rusEFI and Power Vision source review

## rusEFI: an aftermarket ECU, not the factory Delphi ECU

[rusEFI at 5359cc971b60a9a0ee3f0f2a870dbb64f0ad36ef](https://github.com/rusefi/rusefi/tree/5359cc971b60a9a0ee3f0f2a870dbb64f0ad36ef)
is an open-source engine-management system. Its `firmware/config/engines/harley.cpp`
contains a Harley V-twin engine configuration for rusEFI hardware, including
board-specific wiring. This does not make its serial protocol compatible with a
stock Harley Delphi ECU, a Centurion file, or a Dynojet Power Vision. A bike may
have an aftermarket controller; do not assume it does based on model alone.

The reviewed `firmware/console/binary/tunerstudio.cpp`, `tunerstudio_io.cpp`,
`firmware/integration/ts_protocol.txt` and Java console `ByteRange` and `IoHelper`
describe a CRC-framed TunerStudio serial protocol: query (`S`), paged calibration
read (`R`), output-channel read (`O`), write chunk (`C`), page CRC (`k`) and
burn (`B`). In **Tools → rusEFI aftermarket · live serial research**, identify
and bounded reads are separate from an explicitly confirmed experimental
settings-page writer described below. Identify returns a signature; provide
that exact signature **from the matching rusEFI INI**. A successful signature
check is not cryptographic authentication.

### Finding the matching INI

The [rusEFI build server](https://rusefi.com/build_server/) publishes
board-specific **snapshot** bundles, not a universal motorcycle tune or a
replacement for the firmware already on the controller. rusEFI describes these
as changing builds that may be less stable than releases; see its
[release process](https://wiki.rusefi.com/Release-Process/). A current bundle's
INI does not necessarily match a controller running an older build. The bundle
may include firmware and executable tools; GuzziOnBoard does not download,
install, or flash them.

In the rusEFI desktop tool, identify the selected controller first. For common
signature formats, the tool offers an explicit link generated using the official
[INI lookup rule](https://wiki.rusefi.com/INI-lookup-logic/). Opening it sends
the signature to rusEFI; the file may be unavailable, and custom formats may
require manual lookup. Alternatively, find the matching `rusefi.ini` from the
installed firmware, controller's exposed storage (where provided), or correct
board bundle; extract it yourself. Selecting the INI extracts its unambiguous,
quoted `[TunerStudio]` signature locally (up to 2 MiB). For the separate
calibration read the INI text is sent to the local desktop backend to check
selected page-zero metadata; it is not uploaded to a remote service, saved as
an INI, parsed as executable code, or used to install firmware. A matching
string is not authentication, and the limited parser does not validate the
entire INI or decode tables. It never automatically authorizes a write. Each
serial operation checks the live signature.

The lookup URL and INI reader have synthetic tests; the reader also accepted a
source-template INI with a synthetic resolved signature. No build-server bundle
or real controller was tested. Some versions or conditional definitions are
unsupported; the user can enter a signature manually.

Use an explicitly selected USB serial port and supported baud; each operation
opens and closes it. Opening a serial port can affect DTR/RTS, so check the
hardware first. Read lengths are bounded to 1–256 bytes per request and a
16-bit page. Output bytes are a single live snapshot, not decoded gauges or a
continuous monitor. Page bytes are working-page data, not a complete backup,
not automatically shared, and not permission to write. Source firmware can
return **all zeros when a settings page is locked**. CRC32 protects transport
framing; it is not proof of calibration correctness or a factory Harley ECU
checksum. The separate writer below supports settings page zero only; it does
not flash firmware, decode page maps, validate INI fitment or recover a damaged
ECU. User-provided INI metadata and offsets are operator assertions. White-label
signatures not beginning `rusEFI ` and older single-page command variants are
not supported here.

### Experimental settings-page write and burn

**Synthetic-tested only; no physical rusEFI ECU was tested.** Wrong values,
loss of power, an incompatible INI, or interrupted communications can damage
the engine or controller. Do not run the engine; this implementation relies on
the operator to confirm it is stopped and does **not** independently measure RPM.
Do not use another tuning application at the same time. Serial-port control lines
may change on open. The matching signature is not a unique controller identity.

1. Select the actual matching INI and use **Read settings page and open review**.
   The backend accepts only a bounded, unambiguous unconditional page-zero size
   and the reviewed multi-page `R`, `C`, `k`, `B` command strings; it checks the
   live signature, reads the page in 128-byte chunks once and saves a research
   original in `rusefi-backups/`. Replies do not echo requested offsets, so
   sequential request/reply association is assumed. A locked controller may
   return zeros; an all-zero page is rejected. Other pages, legacy single-page framing and firmware flashing
   are not supported. The saved page is not independently verified.
2. Use **Open saved page in Maps** and choose a matching user-supplied XDF,
   or edit a **separate** same-size copy using another compatible editor. Maps
   preserves existing staged edits and its explicitly confirmed rusEFI research
   export fills the current write-review path without contacting the controller.
   A changed read or concurrently changed edited-path field prevents stale handoff.
   This tool does not convert INI maps to XDF,
   create an MSQ, interpret values, repair a tune checksum or check whether
   individual bytes are safe. Enter the edited file path, acknowledge the risks,
   and review every displayed before/after byte and hashes. The immutable plan
   expires in five minutes, is single-use, and retains the bytes reviewed even
   if the edited file changes later. Another serial action invalidates evidence;
   an authorized write attempt consumes it. The original must still match.
3. After a second explicit write/burn confirmation, the app reconnects, checks
   the signature and requests a whole-page ECU CRC against the original without
   repeating the full read. It compares each changed range, writes only changed
   bytes to working RAM with `C`, immediately reads them back and checks the
   whole-page CRC against the target. Only then does it send `B` for page zero,
   request CRC to finish newer deferred-burn behavior, wait, and check working
   CRC again. No write or burn is automatically retried. Source firmware may
   ignore a write or apply board overrides; a full-page CRC mismatch prevents
   the new burn command, but prior RAM writes may already affect operation.
4. A **CRC request may complete a burn that was already pending** on that
   controller/channel before this operation. The new burn acknowledgement and
   matching working-page CRC do not prove that flash was actually persisted;
   the app does not power-cycle and verify nonvolatile storage. Signature and
   CRC checks do not prove controller identity, calibration suitability, or
   absence of collisions or intervening changes. Partial RAM changes, failed
   burn or disconnect leave an **uncertain state**; do not retry blindly. There
   is no automatic rollback. The saved original path is reported for recovery.

A synthetic serial emulator tests framing, read, write, burn, CRC, token and
failure behavior; the browser test mocks the API. No physical controller or
flash persistence was tested. The upstream root `license.txt` presents GPL-3.0
with additional stated usage terms; individual files should be reviewed before
copying. This integration is an independently written protocol client; no
upstream code, engine configuration, tunes, binaries, or customer identifiers
are redistributed.

## Power Vision security research

[Hacking a Harley's Tuner – Part 2](https://therealunicornsecurity.github.io/Powervision-2/)
reports reverse engineering of the Power Vision's USB **Filex** file-transfer
service. This is a PC-to-tuner interface, not the Harley ECU's CAN/J1850
programming protocol. The author reports framing, command names, file operations,
and a checksum, but the prose and attached code disagree about the checksum's
final increment and escaping. The article does not provide sufficient verified
packet captures and request/response semantics for a safe interoperable file
client, and says its example keys and passwords are **fake**. It does not provide
a stock Harley ECU read/write sequence, calibration checksum, or proven
compatibility across Power Vision versions. GuzziOnBoard does not implement the
reported vulnerability, forge messages, modify the tuner, decrypt its data, or
bypass licensing. No example credentials are used or shipped.

[Hacking a Harley's Tuner – Part 3](https://therealunicornsecurity.github.io/Powervision-3/)
focuses on the **Power Vision 1 device**, its licensing/lock handling and a
patched tuner firmware proof of concept. The author explicitly warns that the
modified tuner is unstable, may brick the Power Vision, could damage the ECU,
and should never be used against a real bike. The paper's modified-device
reports are not evidence of a successful, safe ECU flash or an ECU protocol
specification. Its published example VINs, credentials, and device patches are
not reproduced in GuzziOnBoard.

A potentially useful future device-integration lead is the `pvinfo` XML request
shown via a Windows `PVLink.dll` function. It queries the **tuner**, not the
motorcycle ECU directly. The article does not establish a supported public API,
complete calling convention, response/buffer ownership, timeout and error
behavior, version compatibility, or an ECU flash sequence. Parts 2 and 3 also
show different assumptions for the final function arguments. We did not call,
load, distribute, or patch the proprietary DLL; an unsafe ABI guess could crash
the application. Tuner info may contain VINs and licensing details and must not
be uploaded or shared without explicit consent. A documented vendor API or appropriately licensed SDK, plus
real-device testing, would be needed to build a reliable integration.

For a separate vendor-supported Power Vision workflow, Dynojet provides
[software and guides for Harley-Davidson](https://www.dynojet.com/downloads/power-vision-for-harley-davidson/)
and [instructions for retrieving PV Info and applying an unlock license](https://www.dynojet.com/amfile/file/download/file/93/category/127/).
Use the vendor's exact model/year compatibility, licensing, and power/recovery
instructions. These are **external Dynojet tools and hardware**, not functions
implemented, tested, or controlled by GuzziOnBoard. The links do not imply that
a GuzziOnBoard research export is compatible with them.

The Maps-to-review handoff is exercised with synthetic pages and a mocked ECU
API in desktop browser tests. The user-supplied XDF is not inferred or validated
from the INI signature, and no physical rusEFI controller has been tested.
