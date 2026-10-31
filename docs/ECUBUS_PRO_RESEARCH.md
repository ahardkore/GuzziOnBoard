# EcuBus-Pro source review and classic CAN improvements

[EcuBus-Pro](https://github.com/ecubus/EcuBus-Pro/tree/ca3207801b34ded99b67b8b12b5d4547b5a868e8),
revision `ca3207801b34ded99b67b8b12b5d4547b5a868e8`, is an Apache-2.0
vehicle-ECU development tool. See `LICENSES/EcuBus-Pro-Apache-2.0.txt`. It
supports general CAN, CAN-FD, LIN, DoIP, UDS configuration, scripts and various
adapters. EcuBus-Pro itself and its native binaries are **not bundled** here.
Third-party adapter drivers and bundled assets may have separate terms.

## Changes made here

- Improved the existing classic-CAN ISO-TP sender to honor each receiver block
  size and separation time, handle multiple CTS frames, bound WAIT responses,
  reject malformed/overflow/invalid flow control, and conservatively use 127 ms
  for reserved timing values. ISO-TP reassembly now rejects invalid, truncated
  and interleaved transfers before accepting data or sending flow control.
  These changes are informed by EcuBus-Pro's `src/main/docan/cantp.ts`; the
  GuzziOnBoard implementation is separate and uses a fixed bounded policy.
- Added an opt-in SLCAN backend to the desktop CAN selection using the existing
  `python-can` / `pyserial` stack. Hardware-enabled packaged builds already
  include the backend; the hardware self-test now also imports it. Choose
  **CAN (ISO-TP) → SLCAN USB serial adapter**, enter a local port such as
  `COM5` or `/dev/ttyACM0`, and use the appropriate profile's ECU IDs and
  bitrate. The serial connection defaults to 115200 baud; append an explicit
  `@230400` (or another 9600–4000000 rate) to the port if the adapter requires
  it. Network serial URLs are intentionally not accepted. Verify the adapter's
  firmware, physical CAN transceiver, wiring and assigned port.
- Opening SLCAN configures the adapter to the profile's CAN bitrate and opens
  the channel. Diagnostic sessions can transmit requests and flow-control
  frames; this is not a silent/listen-only observer. EcuBus-Pro documents
  SLCAN and other adapter types, but its device support does not by itself prove
  compatibility with GuzziOnBoard or any motorcycle.

All changes are **synthetic-tested only**; neither this CAN-TP adaptation nor
SLCAN was tested by GuzziOnBoard on physical hardware. The supported transport
here is classic CAN with normal addressing, up to 4095 bytes per ISO-TP
payload. CAN-FD, extended/mixed ISO-TP addressing, multi-ECU routing and DoIP
are not added. Backend timing is governed by the OS and adapter; hardware
interoperability is unverified.

## UDS programming and fitment

EcuBus-Pro's [S32K144 UDS bootloader example](https://github.com/ecubus/EcuBus-Pro/blob/ca3207801b34ded99b67b8b12b5d4547b5a868e8/docs/en/um/uds/example/example.md)
and generic download scripts demonstrate configurable UDS services, including
security access and transfer. They are not stock Harley or other motorcycle
ECU protocols and do not provide the missing ECU-specific security algorithm,
image/region geometry, checksum, recovery or fitment evidence. No programming
safeguards or write capabilities were changed by this integration. The included
examples and scripts must not be treated as validated stock ECU flashing recipes.
