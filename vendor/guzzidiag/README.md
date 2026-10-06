# `vendor/guzzidiag/` — mirror of the GuzziDiag download archive

Byte-for-byte copies of the files published at
<https://www.von-der-salierburg.de/download/GuzziDiag/>, kept exactly as the
site distributes them (original zip names, untouched archive bytes).

```
vendor/guzzidiag/
  xdf/            72 zips, each containing one TunerPro .xdf map definition
  tools/          23 zips + 1 .exe — the Windows GuzziDiag/IAWDiag toolchain
  MANIFEST.json   per-file size, SHA-256, zip contents and upstream URL
```

Regenerate the manifest with:

```bash
python3 scripts/vendor_manifest.py          # rewrite
python3 scripts/vendor_manifest.py --check  # verify it matches the files
```

## Why both this folder and `guzzionboard/xdfs/`?

They serve different jobs and must not be confused:

| | `vendor/guzzidiag/` | `guzzionboard/xdfs/` |
|---|---|---|
| Content | the original zips as downloaded | the extracted, parse-checked `.xdf` files |
| Purpose | provenance / archive; verify any byte against the origin site | what the application actually loads at runtime |
| Produced by | manual download, `scripts/vendor_manifest.py` | `scripts/import_xdfs.py --source vendor/guzzidiag/xdf` |
| Shipped in the wheel | no | yes |

Every one of the 72 XDF zips here has been imported with the project's own
parser (`guzzionboard.maps.XdfFile`) — 72 files, 2616 tables, 1531 constants,
zero rejects — and recorded in `guzzionboard/xdfs/PROVENANCE.json` with its
SHA-256. `python3 scripts/import_xdfs.py --status` lists the catalog entries
still missing from the mirror.

## The tools, and what this project does instead

The `tools/` zips are closed-source Windows binaries. **Nothing in
GuzziOnBoard executes, links against, bundles or decompiles them** — they are
mirrored as the reference implementation and changelog record that
`docs/PRIOR_ART.md` §2 analyses, and as the only practical way to reproduce a
wire capture against a bench ECU.

| Mirrored tool | Families | GuzziOnBoard equivalent |
|---|---|---|
| `GuzziDiag_V0.61` | K-Line live data, TPS reset | Live data + `procedures.py` (TPS reset) |
| `IAWDiag_V0.52` | P7, P8, 16M, 15M, 15RC, 15P, 59M, 5AM, 5SM, 5DM, MIU1, 7SM, MIUG3 | Diagnostics panel, capability catalog |
| `GuzziCanDiag_V0.02` | CAN-era diag (MIU G4 / 11MP) | CAN transport (identifiers unconfirmed) |
| `IAW15xReader/Writer/EEPROMTool` | 15M, 15P, 15RC | `programming.py` read; write gated on hardware |
| `IAW5xReader/Writer`, `IAW5AMEEPROMTool` | 5AM, 59M | `programming.py` (5AM path grounded in a verified capture) |
| `IAW7SMReader/Writer/EEPROMTool` | 7SM | `docs/7SM_WORKFLOW.md` |
| `IAWMIUG3Reader/Writer/EEPROMTool`, `IAWMIUReader/Writer` | MIU G3, MIU1 | `programming.py` |
| `IAWMBC1Reader_V0.01` | MBC1 (BMW C600, Nuda 900) | read-only, cross-brand by design |
| `ManaTCU_V1.03` | Aprilia Mana gearbox TCU | not covered |
| `RPMSensorEmu_V0.17` | bench phonic-wheel emulator | hardware-validation aid (PRIOR_ART §6) |
| `AdapterTest_V1.01` | FTDI interface pre-flight | `adapter.py` preflight |
| `GearSpeed_V1.55` | gearing/speed calculator | `derived.py` parity target |
| `ZT2CSVToLogWorksDIF_V0.71` | Zeitronix ZT-2 log conversion | session log export |
| `CDM-v2.12.36.20-WHQL-Certified` | FTDI D2XX/VCP Windows driver | OS-level dependency only |

Operational constraints published alongside these tools (FTDI latency timer
1 ms, no VMs, 7SM reads ≈ 30 min, never flash HW1xx images into HW3xx) are
tracked in `docs/PRIOR_ART.md` and enforced where the code can enforce them.

## Licensing

These are **third-party, community-authored files**, not covered by this
repository's MIT license. The origin site publishes them free for
non-commercial use with a blanket "use at your own risk, no liability"
notice; this mirror keeps that posture, adds no modifications, and credits
the GuzziDiag / IAWDiag / wildguzzi.com community (XDF authorship is recorded
in each file's own `<author>` field — largely `beard`). If you are an author
and want something removed, credited differently or updated, please open an
issue.
