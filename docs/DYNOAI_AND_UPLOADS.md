# DynoAI, Harley trouble codes, and the six uploaded files

Reviewed against [DynoAI_3 at `cc22636`](https://github.com/rob9206/DynoAI_3/tree/cc22636aafa40a0b4ce4c27b5e0cc50795012b87),
[harley-davidson-trouble-codes at `68e74b5`](https://github.com/kakhamek/harley-davidson-trouble-codes/tree/68e74b58c351ef187ec282ee7e4e54eabc4eda1c),
and [the six uploads at `9a5d6012`](https://github.com/ahardkore/GuzziOnBoard/commit/9a5d6012).
The six files were uploaded to the public repository's main branch, not attached
to this PR; five are byte-for-byte copies of files already present in the
checkout's `docs/`. This change does not add the six files again or execute any
uploaded executable. The earlier desktop packaging recipe collected the entire
`docs/` directory, including the five existing copies; it is now restricted to
Markdown and JSON documentation, with a release-build check rejecting other
files in `docs/`. Previously built artifacts may already contain those copies. Review public uploads for licensing, customer/vehicle
identifiers and other information before sharing; removing a file in a future
commit would not remove it from Git history.

## Live JetDrive observation

Tools → **Dynojet JetDrive · live network observation** listens for a bounded
three-second multicast window from an explicitly chosen local network interface
and either the `224.0.2.10` or `239.255.60.60` group, UDP port 22344. Packet
layout, channel metadata and sample decoding are adapted from
`api/services/jetdrive/jetdrive_client.py` in DynoAI_3. Copyright (c) 2024–2026
DynoAI, MIT; license: `LICENSES/DynoAI-MIT.txt`. DynoAI also contains a much
larger tuning, analytics and Power Core integration suite; this is not that
entire product and does not run its server or simulator.

Passive mode sends no application messages. The separate opt-in sends one
multicast request for channel metadata, using the source-described key `0x06`;
it does not send an ECU write or dyno-control command. No background discovery
or telemetry upload occurs. The socket binds a wildcard local address to receive
multicast: the chosen interface controls group membership, **not an authenticated
source or an exclusive inbound-interface filter**. Network clients can spoof or
mislabel packets. Channels are keyed by source IP and provider ID, metadata is
used only if already received, and values, timestamp milliseconds, provider
name, channel name and numeric unit code are reported without inferred units or
conversion. Metadata is discarded at the end of the window. No samples are
carried into a subsequent window. Windows are capped at 1,200 datagrams and
4,000 samples, with limits reported; UDP packet loss, reordering, timestamp
wraparound, clock alignment, or malformed packets can cause incomplete data.
CSV export is explicit, long-form rather than automatically aligned, and may
include source IPs and provider names. It is not automatically imported into a
fuel-correction workflow or shared. The user must verify channels, units,
calibration and timing before using any data. No physical dyno was tested;
parser and UI use synthetic fixtures; a local UDP loopback check sent a synthetic
frame, not a physical dyno signal. Do not use output for
operating or safety decisions.

## Local Power Vision PVV table editing

The new PVV tool accepts a local user-supplied XML document using DynoAI's
`PVV/Item/Columns/Rows/Cell` layout. It displays supported numeric scalar and
2D tables, stages individually entered numeric values, shows a list of changes,
and exports a separate PVV XML copy only after review and confirmation.
Malformed/unsupported items are preserved without editing; DTD/entity documents
are rejected. XML formatting can change. Exports are local and do not connect
to Power Vision or a motorcycle, calculate a checksum, validate metadata,
check ECU/vehicle fitment, recommend a value or prove that vendor software or
hardware accepts the output. The original file is not overwritten.

The editor was exercised against a synthetic example and separately inspected
DynoAI's own `config/pvv_template.pvv`: 129 editable items were shown. That
source template is not bundled or treated as a vehicle's calibration. This
integration and all edits are synthetic-tested, not hardware-validated. Use
vendor software and model-specific recovery procedures to determine how a
particular PVV should be handled; no ECU flash or security access is added.

## Harley trouble-code descriptions

The source JSON has 178 entries and 175 distinct code strings. Three codes have
multiple entries; one is the nonstandard string `P691`. The repository has no
license file; GuzziOnBoard does not bundle its data or fetch it automatically.
In Fault codes, a user can select their own `codes.json` and do an in-memory
lookup. Duplicate descriptions are retained, including nonstandard source
strings, without silently rewriting them. Matching live fault reads show these
as additional **local Harley reference** labels. File selection and clearing do
not connect to the bike, set code status, clear faults, diagnose a cause or
establish year/module fitment. The existing HarleyDroid EVO descriptions remain
separately attributed. Reference text remains local to the browser session.

## Upload inventory

| Uploaded file | Review and supported use |
| --- | --- |
| `Suzuki-GSXR1300-32910-10LX0.zip` | Contains one TunerPro XDF. The existing parser extracted 122 tables and flagged 10 unsupported patch definitions. No checksum declaration was present. User-supplied XDFs can be used via the existing local research workflow; patch support and checksum safety are not implied. Rights in the branded definition are not established merely by a repository license. |
| `Hayabusa gen 3 stock.bin` | The uploaded 2 MiB file rendered all 122 supported tables in that XDF at base zero with no table-range errors in a local inspection. Address ranges fitting is **not proof** of the matching ECU/software, physical correctness, or checksum state. No ECU flashing was tested. |
| `Boost map ON Legacy.bin` | A 1 MiB binary; it is not a fit for the 2 MiB Suzuki XDF's addresses. Its filename alone does not establish the ECU, software revision, intended changes, checksum or write protocol. |
| `STOCK ECU OPEN.bin` | A 1 MiB binary; likewise not address-compatible with that Suzuki XDF. Do not infer a fitment or checksum from the filename. |
| `14CUX_CHECKSUM.ZIP` | Contains an XDF describing Rover 14CUX and a Windows checksum DLL. The XDF parsed as 13 tables and 10 constants, with a checksum declaration; that declaration alone does not implement the algorithm. This is not a Harley or Suzuki checksum. The DLL was not run. |
| `MTX-TPPlugins_Pack_u1J2.zip` | MTX Electronics' TunerPro checksum-plugin pack contains 11 Windows DLLs for named Bosch and Siemens automotive ECU families. Its readme calls it a free edition; the included license text is a warranty disclaimer rather than a clear redistribution grant. Some plugins require an original BIN at a fixed `C:\\` path. The DLLs were not run or copied into this branch, and GuzziOnBoard's isolated Python checksum providers do not load TunerPro DLLs. Do not use them as evidence of a Harley/Suzuki checksum or execute unknown native code in the workstation. |

The two 1 MiB images differ by 1,843 bytes across 37 contiguous ranges; this
comparison does not identify what those changes do or prove fitment. The zip
inventories were read without executing their contents. The existing
local XDF preview and research-copy workflows do not establish ECU write
protocol, matching identity, checksum, or safe flash/recovery.
