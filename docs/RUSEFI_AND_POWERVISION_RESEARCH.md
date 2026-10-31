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
read (`R`), output-channel read (`O`), and also write and burn commands. In
**Tools → rusEFI aftermarket · live serial research**, this integration offers
only the first three. Identify returns a signature; for either read, provide
that exact signature **from the matching rusEFI INI** and the range described by
that INI. A successful signature check is not cryptographic authentication.

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
board bundle; extract it yourself. Selecting the INI locally imports only the
unambiguous, quoted `[TunerStudio]` signature (up to 2 MiB). It is not uploaded,
saved, parsed as executable code, or used to install firmware. A matching string
is not authentication and the tool does **not** validate INI contents, determine
page geometry, decode tables, or automatically authorize any ECU write. It
still requires confirmation and rechecks the live signature for every read.

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
checksum. No write, burn, flash, page decoding, INI fitment verification,
full-image export, or recovery is implemented here. User-provided INI signature
and offsets are operator assertions. White-label signatures not beginning
`rusEFI ` and older single-page command variants are not supported here.

**Testing is synthetic only:** a fake serial device tests response framing,
CRC, exact signature gating, request fields, bounded reads, and failure handling;
no physical rusEFI hardware was tested. The browser integration test mocks the
API. The upstream root `license.txt` presents GPL-3.0 with additional stated
usage terms; individual files should be reviewed before copying. This integration
is an independently written protocol client; no upstream code, engine
configuration, tunes, binaries, or customer identifiers are redistributed.

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
