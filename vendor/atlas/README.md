# Atlas interpolation source reference

These four Java files are unmodified copies from the AGPL-3.0 Atlas source
at <https://github.com/jakka351/atlas>, commit
`91499280f20a81cabdd891c5e0ca70143bb8c800`, path
`java/src/main/java/com/github/manevolent/atlas/math/`. The interpolation
implementation and axis-aware mode were committed by `manevolent` in May 2024.
The upstream README and root LICENSE identify the project as AGPL-3.0. The
license text is reproduced in this repository's root `LICENSE`.

`web/atlas-interpolation.js` adapts the axis-based relative-position and
linear/nearest interpolation functions to JavaScript. It is not a verbatim
copy: it rejects non-finite or non-monotonic axes, does not use Java floats,
and produces proposals for the existing GuzziOnBoard safety pipeline rather
than writing ECU calibration bytes. It does not port Atlas's ECU protocols or
its assumptions about Subaru calibrations.
