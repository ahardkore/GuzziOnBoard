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
