# IAW Scan 2 source provenance

This directory contains an unmodified, source-only evidence snapshot from
[TzOk83/IES2](https://github.com/TzOk83/IES2), an open-source diagnostic
implementation for legacy Magneti Marelli automotive ECUs.

- Upstream commit: `a5995eab86e82be60386e99b2eecc9c14810ec85`
- Retrieved: 2026-10-06
- License: BSD 3-Clause (`LICENSE.txt`)
- Scope retained: the ECU protocol classes, their common data structures, the
  serial/initialization orchestration in `frmMain.cs`, and the upstream readme.
- Integrity: `SHA256SUMS` hashes every retained upstream file. It intentionally
  does not hash this provenance note or itself.

## Evidence boundary

The `iaw16f.cs` and common `ecu.cs` sources corroborate the 16F/1.6M legacy
one-byte query/response design and are used together with Marelli document
3.00600 and the published 1.6M implementation notes. `iaw04k.cs` demonstrates
a direct legacy protocol for the automotive IAW 04K. It does **not** establish
that a Moto Guzzi IAW P8 has the same register map or exact behaviour; the P8
profile therefore remains inferred and physical use is blocked.

No claim is made that this automotive program supports the later motorcycle
15M, 15RC, 59M, 7SM, MIU, or Mana families.
