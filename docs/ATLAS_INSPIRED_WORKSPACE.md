# Workstation improvements inspired by Atlas

The publicly visible [Atlas feature overview](https://github.com/motorsportsresearch/atlas-public)
and screenshots informed this workstation's visual direction and the idea of
multi-channel telemetry and a searchable calibration workspace. The UI and
renderer are GuzziOnBoard's; the map editor additionally adapts interpolation
code from the earlier AGPL Atlas source. No Atlas artwork is included.

There are distinct Atlas repositories and versions with different licensing:

- The [jakka351/atlas fork](https://github.com/jakka351/atlas) contains an
  earlier Atlas source tree and an AGPL-3.0 license. Its README explicitly
  describes that version as AGPL-3.0. Reusing code from it requires reviewing
  provenance and complying with that license, including applicable source
  availability and copyleft obligations; it does not require contributing
  changes to the original repository.
- The newer [motorsportsresearch/atlas-public](https://github.com/motorsportsresearch/atlas-public)
  repository's LICENSE says **all rights reserved** and its public tree does
  not contain the application source. Its terms should not be conflated with
  the AGPL-licensed fork.

The combined application is distributed under AGPL-3.0-only; pre-existing
GuzziOnBoard material retains its original MIT grant. See the root `LICENSE`,
`LICENSES/GuzziOnBoard-MIT.txt`, and `vendor/atlas/README.md` for provenance.
Subaru-specific flashing, recovery, calibration and custom-logic claims are not
evidence that those operations are supported by a Guzzi ECU.

## Using the workspace

- **Layout** in the header switches between comfortable and compact spacing.
  The preference stays local to the browser or desktop webview.
- **Live data → Live timeline** plots up to four explicitly selected channels
  from the last 300 polling sweeps of the current connection. Timeline selection
  does not change which channels are polled. Each lane scales independently and
  displays its own units, minimum, maximum, latest value and sample count; do
  not compare the vertical position of different lanes as if they shared units.
  Missing/invalid values and polling restarts break lines. A backwards or duplicate timestamp breaks
  a line; changed units are refused rather than combined. The graph is a display
  aid, not a diagnostic verdict. The original session logging and CSV export
  remain unchanged, including raw provenance.
- In **ECU memory → Maps & tables**, render an image and use **Search tables or
  categories** to narrow the visible tables. Search is visual only: it does not
  discard selections or staged edits and does not change the exported map.
- **Interpolate rows / columns** supports uniform cell spacing (the default)
  or numeric X/Y axis spacing, and linear or nearest-endpoint interpolation.
  Axis spacing uses staged axis edits, accepts ascending and descending axes,
  and rejects missing, nonnumeric, duplicate or non-monotonic coordinates
  before changing any selected cells. Edits are proposals, not validated
  tuning values. Axis values may be quantized during build; review the exact
  preview and evidence before proceeding. Bilinear blend remains cell-spaced.
- The desktop app uses these same local assets inside its existing pywebview
  shell. Its guarded loopback API, safety gate, export bridge and close handling
  are unchanged; no new connection or write privilege is granted by this UI.

Atlas advertises faster flashing, ECU logic creation, cross-application of
calibrations, and additional hardware support. Those features were deliberately
not transplanted or claimed here: they need ECU-specific evidence, compatibility
checks and physical validation. Simulation and browser tests are not a substitute
for a real-bike or dyno test.
