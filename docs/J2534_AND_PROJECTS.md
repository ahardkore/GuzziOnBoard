# J2534 inventory, portable projects and capture filtering

## J2534 driver inventory

In Firmware → Adapter pre-flight, **List installed J2534 drivers** inspects the
Windows 32- and 64-bit `PassThruSupport.04.04` and `.05.00` registry views.
It reports the library path and registered protocol flags exactly as claims,
not verified capabilities. It does **not** load a DLL, discover USB hardware,
open a device, connect to an ECU, or implement a J2534 transport. The registry
view's bitness is not proof of DLL bitness. Non-Windows hosts and the hosted
demo cannot inspect the Windows registry. The scan is tested with a fake
registry; it has not been validated against real Windows drivers or a bike.

A future transport needs a defined 32/64-bit driver strategy, mocked API
contract tests and bench verification of adapter-specific ISO14230 fast/slow
initialization, timing, echo, voltage handling and disconnect behavior.
No catalog capabilities, hardware gates or programming permissions are changed
by discovery.

## Calibration projects

The map editor exports schema 2 JSON. Render the original source and the same
XDF first, then import the project. The image SHA-256, XDF filename and SHA-256,
and image address base must match, as must each edited cell's original raw
value. Duplicate changes are rejected. The stored plan is not a firmware image,
and importing does not bypass validation, preview, checksum-provider selection,
fitment, source, evidence or programming gates. A schema 1 project cannot be
safely verified against its definition: recreate and review it as schema 2.

Projects retain explicit trace mappings, staged changes, evidence references,
checksum provider and recommendation-package references. If an offline CSV was
loaded in a secure browser context, they also record its SHA-256, filename and
analysis control settings. To restore those controls, load the **identical** CSV;
missing or different data leaves settings pending, not applied. Reports and
proposals must be regenerated. A project contains no firmware or log data, but
it does contain local paths, filenames, hashes, edit values and evidence
references; review it before sharing. Source and log files must be transferred
separately when appropriate and legally permitted.

## Passive CAN capture filtering

The existing capture analyzer accepts an optional comma-separated list of
hexadecimal IDs, such as `7E0, 7E8`. Filtering is performed on an already
recorded file or pasted text, not on a live bus. Numeric IDs match both 11-bit
and 29-bit frames. The result provides counts separately for each frame format;
filtering can remove evidence and change the inferred candidate pairs. These
candidates do not establish motorcycle protocol support or enable any ECU.

## External A2L conversion

No A2L converter or third-party source is bundled. The inspected
[a2l2xdf](https://github.com/jakka351/a2l2xdf) project reports a narrow tested
subset and has no explicit repository license; user permission alone cannot
grant rights on behalf of another copyright holder. If you independently obtain
an appropriate converter and an A2L for the **exact** ECU/software, conversion
can produce an XDF for the existing local XDF workflow. Treat it as unverified:
independently review address base, byte order, data types, axes and scaling,
compare known raw values, and use **Validate definition**. Structural validation
is not proof of ECU fitment, checksum correctness or physical safety. Do not
ship guessed conversion output or enable physical writes on that basis.
