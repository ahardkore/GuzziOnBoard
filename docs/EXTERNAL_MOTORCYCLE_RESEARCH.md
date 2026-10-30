# External motorcycle and calibration research

Reviewed 2026-10-28. These sources are useful references, not evidence that a
Moto Guzzi ECU supports a particular service, memory layout or checksum. Code,
calibration data, images and firmware can have different rights; a public file
is not automatically licensed for redistribution. Links are research leads,
not endorsements or safety approvals.

| Source and inspected revision | What is useful here | Limitations / disposition |
|---|---|---|
| [motorcycle-service-db](https://github.com/ramblenride/motorcycle-service-db), `3d21b582720e18c9f80e254bfdaf3875cf443990` | CC BY-SA service data and a JSON service-template shape. The independently written worksheet can review user-selected templates and calculate from documented service anchors. | Five unchanged templates for Honda, KTM, Royal Enfield and Suzuki are bundled with CC BY-SA attribution. Yamaha was excluded due to a conflicting model label and description. Verify model, year, market, initial and severe-use rules in the applicable manual. See `web/service-templates/README.md`. |
| [OpenRaceTelemetry](https://github.com/brendisurfs/OpenRaceTelemetry), `3daf1322dee956f77bdd838978c5d5b962572dec` | GPL-3.0 motorcycle telemetry project and a direction for possible GPS/IMU workflows. GuzziOnBoard already provides an independently implemented read-only live timeline. | Upstream firmware and desktop UI are incomplete, with hardware functions marked TODO. No firmware, telemetry hardware driver, sensor math, or code imported or claimed to be working with GuzziOnBoard. |
| [manual-rag-assistant](https://github.com/SRodriguezSpina/manual-rag-assistant), `972b8c7c2db28aea6018d367489caf14c07f6cc9` | MIT-licensed, source-attributed manual-excerpt search workflow informed the independent local text search and service arithmetic. | Upstream uses a Kotlin MCP server, local embedding models, and separate copyrighted PDFs; none are bundled or ported. Our tool only searches user-supplied text literally, without AI, PDF extraction, or page validation. |
| [motorcycle-canbus-info](https://github.com/talss89/motorcycle-canbus-info), `b65a4a8d58bbf60c6d9bf5823d1df5a0f4d4cccc` | MIT-licensed, incomplete sniffing notes for the 2017–2021 Triumph Tiger 1200 Gen 3, including switch and TPMS observations. The general research workflow informed the independent raw-byte summary in CAN discovery. | Triumph observations are not Guzzi protocol evidence; parts are explicitly uncertain and the pressure-change status descriptions conflict. No IDs, signal definitions, commands or code were imported. |
| [DucatiPanigaleCanBus](https://github.com/renatobo/DucatiPanigaleCanBus), `03e7127c69ee3398c03076352ac93bbd3f795ce2` | MIT-licensed source for selected Mitsubishi Ducati CAN broadcasts. Adapted as an **opt-in offline** decoder, retaining raw frames; upstream credits and MIT notice are in `LICENSES/DucatiPanigaleCanBus-MIT.txt`. | Upstream names specific Ducati models. No automatic vehicle detection, live capture, transmission or Guzzi compatibility. The adaptation reports below-zero temperatures as signed integers rather than allowing unsigned wrap. Test vectors are synthetic; interpretation is not independently bike-validated. |
| [moto-service-tool](https://github.com/slava-fm/moto-service-tool), `ac39e456fdc9e93c1a0c64c426c8b6d0e1385e45` | MIT-licensed Ducati Panigale V2 service workflow and ELM327 research reference. | Reset routines write to the ECU and are reported validated only for the author's stated Ducati fitments. No reset commands or IDs imported into Guzzi profiles; Guzzi operations remain gated. |
| [Ducati-Desmo-Shim-Calculator](https://github.com/EhrenTheMan/Ducati-Desmo-Shim-Calculator), `146d2e93261d9978f15258af1739751e327aed07` | The idea of a clearance worksheet informs the independent, manual-only worksheet in Tools. | No license was found in the repository metadata when reviewed. No code, presets, specifications or shim data copied. Guzzi engines may use screw adjusters; the user must verify the mechanism and specs. |
| [Engine Tune Repository](https://github.com/Snoman002/Engine-Tune-Repository-TunerPro-EFIlive-TunerCat), `61136c6d0d59506d60a01b4ff7176679d9903fd4` | Example of organizing definitions and calibrations by ECU and software identity; the existing project format already locks image and XDF hashes. | Aggregates files from various authors and says validity is unverified; no overall license found. No definitions or binaries copied or assumed compatible. The duplicate user link refers to the same repository. |
| [ZedSuite](https://github.com/LeZed97/ZedSuite), `77d75fb9e28df04379fd6d1912197947f1cce0c0` | GPL-3.0 local editing, versioning and positive ECU-identification design reference. Existing map editor provides staged edits, undo and hash-locked projects. | Automatic detection targets specific VAG Bosch ECUs; its identification patterns and checksums are not Guzzi evidence. No code imported. |
| [CBR250RR ECU binary definition](https://github.com/kelvinvalencio/cbr250rr-ecu-binary-definition), `8be351c718205843c842c7abe62eafa51bdac218` | Documented example of hardware/software-specific XDF layout and uncertainty. | Honda MC51 Keihin, not a Guzzi definition; no repository license found. No binary, XDF, offsets or scales imported. |
| [moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum), `43ccc5f3663e2a175b7217f802bc302830e6862b` | Its README says MIT and documents useful model-specific checksum verification and pre/post examples. | README evidence covers its listed Bosch, Yamaha, Honda and other profiles—not an exact Guzzi profile. The Yamaha and Bajaj checksum layouts support explicitly confirmed offline research-copy repair; Bosch MSE6 remains inspection only. No map-builder plugin or auto-enabled repair is provided. A matching Guzzi image, licensed provenance and independent test vectors are prerequisites for any Guzzi plugin. |
| [ECU Studio AI](https://github.com/PCTestAdmin/ECU-Studio-AI), `af590074bafc7077ba12b080b80f44d553c24e99` | GPL-3.0 measured-confidence, evidence-ranked detection and image/definition checks provide a useful research direction. | Published benchmarks refer to its listed ECU families, not Guzzi validation. No detection or checksum code copied; no heuristic map locations promoted to safe Guzzi definitions. |
| [TunerPro definition index](https://www.tunerpro.net/downloadBinDefs.htm) | Index links to Ducati M15 and, for Moto Guzzi and others, the GuzziDiag definitions already catalogued in this project. | The page itself warns that most definitions are unverified and identifies different contributors. No additional files imported; inspect each file's provenance and terms and verify exact software fit before use. |

## Inspecting raw CAN-byte changes

In **Discovery → CAN identifier discovery**, enter a hexadecimal ID filter,
select **Summarize raw byte changes**, and analyze a previously captured log.
For each filtered ID, frame format and direction, the summary reports payload
lengths and per-byte sample count, minimum, maximum, number of observed changes,
and a bit mask of observed variations. Bytes are numbered from 1. Comparisons
follow capture order, skipping frames where the byte is absent; empty and
oversized payloads are counted but excluded from byte statistics. At most 100
groups are returned. The report contains no interpreted signals or units.

The capture parser does not preserve bus/interface identifiers. Use a single-bus
capture or split it first; otherwise different buses may be mixed. Direction can
also be unknown, in which case incoming and outgoing traffic may be combined.
Correlations and changed bits are not proof of function, ECU fitment or safe
transmission, and this feature does not connect to hardware.

## Using the offline decoder

In **Discovery → CAN identifier discovery**, select **Ducati Mitsubishi
(research only)** and analyse pasted or local captures. The default is **None**.
The filter applies before decoding; only matching 11-bit frames are considered.
Known transmitted frames, short/oversized data frames and extended frames are
not decoded. For unknown direction the output explicitly says `unknown`, so it
may include transmitted traffic. At most the first 200 decoded events are
shown; counts identify omitted events. Raw data accompanies each result.

Matching IDs alone do not establish the source vehicle, signal validity or
units; compare the exact motorcycle and independent observations. Candidate
signals do not become diagnostic addresses, an ECU profile or a write
capability. The simulator and both hosted and desktop workstations use the
same explicit selection. Desktop reads existing files via its normal local API;
there is no new hardware connection.

## Manual shim worksheet

In **Tools → Manual shim worksheet**, enter a measured clearance, current shim,
target minimum/maximum, and confirm whether a thicker shim increases or
decreases clearance for the exact mechanism. Optionally enter available shim
sizes in millimetres. The worksheet targets the midpoint, reports the ideal
thickness and predicted clearance for each entered size, and flags negative
predictions. It does not know the bike, its correct target, or whether a linear
1:1 relation applies; it supplies no preset or shopping/installation decision.
Follow the exact service manual and physically remeasure after assembly.

## Honda 2005 CBR600RR: source-scoped read-only live data

Source: [andreibaw/Honda_K-Line_KWP2000](https://github.com/andreibaw/Honda_K-Line_KWP2000/tree/f3bd42ff438e840e4da3802dd5038a195f3d67be), commit `f3bd42ff438e840e4da3802dd5038a195f3d67be`, Honda ECU Manager, Copyright (C) 2025 andreibaw, GPL-3.0-or-later. `web/honda-offline.js` adapts the response table byte offsets, scaling and two's-complement checksum from `src/HondaKWP2000.cpp`. The upstream GPL license is preserved in `LICENSES/Honda-KLine-GPL-3.0.txt`; source and attribution must accompany distribution of the combined AGPL application in accordance with the applicable licenses.

The author reports testing on a **2005 Honda CBR600RR**, but does not establish an ECU part number, all variants/markets or compatibility with other years/models. GuzziOnBoard now has a read-only, model/year-scoped **desktop K-Line** adaptation of this source; the integration has only synthetic tests, not motorcycle tests. Select Honda → CBR600RR → 2005, read-only and the profile-default handshake, with an appropriately wired, echoing K-Line USB interface. There is no simulator, confirmed part-number identification, fault reading/clearing, actuator, arbitrary table, security, ECU image reading or programming. Table 00 may return an **unverified raw ECM ID candidate**, not an identified ECU or authorization to program. The source calls diagnostic tables “memory”; table 10 is a live sensor snapshot, **not** a flash-image dump. Other catalog entries and tools do not establish Honda compatibility.

The desktop path sends a 70 ms K-Line low pulse, waits 120 ms, sends `FE 04 FF FF`, waits 200 ms, then sends `72 05 00 F0 99` at 10400 baud and requires `02 04 00 FA`. Thereafter its only allowed requests are `72 05 71 00 18` for a raw ECM ID candidate, `72 05 71 10 08` for sensor table 10, and `72 05 71 D1 47` for status table D1; table 10 also serves as keepalive. The 2005 source uses table 00 for keepalive, and HondaECU extracts five bytes after `71 00` as an ECM ID for its 2007–2018 range; that interpretation is not validated for this 2005 ECU. It accepts only complete 22-byte table-10 or 10-byte D1 responses with destination `02`, matching service and table, correct length and two's-complement checksum. Each selected table is requested once per poll; a failure in one table does not invalidate the other. Raw channel bytes are shown beside each candidate. D1 distinguishes only source-described candidate status, including **neutral or clutch** rather than a confirmed gear. Sensor and status interpretations do not set the workstation's engine/battery safety state. Stop the engine, secure the motorcycle, and never operate the app while riding.

The shared browser/desktop Tools page accepts pasted complete hex responses, validates exact table lengths and the source's checksum, and presents table 10/D1 results as **candidates** together with the original bytes. D1's combined neutral/clutch flag is not a confirmed gear. Results must not be used as safety measurements or treated as fitment proof. No capture, data or model selection is uploaded by the decoder. There is no stream reconstruction, frame pairing or diagnosis.

Important source limitation: the two example received frames in the upstream README do **not** satisfy its own checksum algorithm (their byte sums modulo 256 are `0x71` and `0x0d`). They are not used as validated captures. Tests instead create clearly synthetic checksum-valid frames and verify that those published examples are rejected. A valid checksum establishes only internal frame consistency, not real-world correctness. GuzziOnBoard has not tested the decoder or the new desktop session on a real motorcycle; the physical session is source-reported, not validated by this project.

## Multi-brand expansion: protocol and calibration evidence

All new decoders are **offline research only** in the shared browser and desktop
Tools page. A user selects the source/profile and pastes complete frames. There
is no ECU connection, hardware driver, automatic brand detection, polling,
unlock, fault clearing, programming, or proof that a capture came from the
selected bike. The Suzuki catalog entry remains a research placeholder with no diagnostic
capabilities; physical and simulator sessions are blocked. Kawasaki ER-6n 2006
and Triumph Daytona 675 2012 also have separate read-only diagnostic paths described below. BMW and Harley research are
not claimed as garage vehicle fitments. Raw frames and candidate values remain
local to the tab. Limits: 100 frames per invocation and 70 K-Line bytes per
frame; no stream reconstruction. Do not use these candidates as safety data.

| Evidence source and pinned revision | Scope imported | Important limits |
|---|---|---|
| [iKawa](https://github.com/gabrielerandazzo/iKawa/tree/79eb9049d13037be6fd91b8a1d1acd164ca70104) | Copyright (c) 2026 Gabriele Randazzo, MIT; `ikawa/Kline.cpp` response parsing and a subset of read-value formulas for author-tested **2006 Kawasaki ER-6n**. Full notice: `LICENSES/iKawa-MIT.txt`. | Exact ECU ID and broader model/year coverage unverified. Source-specific throttle calibration, decimal-byte RPM/speed formulas and all values are candidates. Rejects negative, short, wrong-address and bad-sum frames. |
| [SV650overlay](https://github.com/BananaJoh/sv650overlay/tree/cc80f0d35abd60255bbcd74cdddef515ed4945ce) | BananaJoh, GPL-3.0; `MainActivity.java` and `DataInfo.java` candidates for author-operated **Suzuki SV650AK7 (2007)** SDS all-sensors frames. License: `LICENSES/SV650overlay-GPL-3.0.txt`. | Source says some conversions are missing or inaccurate. Its RPM uses only the high byte; another SDS implementation treats both bytes differently. Other conversions also differ. The Suzuki source explicitly says conversions may be inaccurate, so it is not promoted to a physical ECU profile. |
| [daytona-kline](https://github.com/andrewwilke/daytona-kline/tree/d37e96718f5cd82ebde3297c1181c687a922ea32) | Copyright (C) 2026 Andrew Wilke, GPL-3.0-or-later; ISO 9141 response framing and subset of SAE mode 01 formulas for **2012 Triumph Daytona 675**. License: `LICENSES/Daytona-Kline-GPL-3.0.txt`. | Author tested one bike; formulas have not been compared against its dash. Other years untested, and its `0x21` sensor block did not work on the tested bike. The offline decoder does not transmit. A separate read-only implementation below adapts slow wake-up and polling; security access and output tests are not imported. |
| [EasierCan](https://github.com/HagayBT/BMW-R1300GS-Smart-Backlight-Fog-Light-Controller/tree/a4c37ceabeea57bc7e97b51da345dd7b84e21596) | Copyright (c) 2026 HagayBT, MIT; candidate RPM and switch bits from a **BMW R1300GS** capture source. License: `LICENSES/BMW-R1300GS-EasierCan-MIT.txt`. | No specific model year is established by the README. No transmitting, wiring or output-control code is imported. Input is a manually supplied 11-bit classic CAN frame; its direction is unknown. Matching IDs do not establish fitment. |
| [vpw-sniffer](https://github.com/bbutka/vpw-sniffer/tree/37aa6f974615154419bc28eb9cf9f9cfb804ade0) | Copyright (c) 2026 bbutka, MIT; generic J1850 CRC-8 check, for research into a **2008 Harley-Davidson Touring** bus. License: `LICENSES/VPW-Sniffer-MIT.txt`. | Source says it has not been validated on a bike. Its test labels `01 02 03 → 1B`, but its own CRC implementation yields `C1`; we test `C1` plus standard `123456789 → 4B`. Only CRC consistency is reported—no Harley data, timing, bus capture or bike compatibility is established. |

The research UI omits an unsupported ID, malformed length, invalid additive
checksum or invalid J1850 CRC rather than producing a value. A valid checksum
alone is not provenance, diagnostic evidence, vehicle identification or proof
of safe use. BMW CAN has no payload checksum validation in this research tool.

### Tuning information reviewed, not imported

- [moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum/tree/43ccc5f3663e2a175b7217f802bc302830e6862b) reports CFMoto NK250 2024 (`F01R00DG1Z_X10A04B228`) and 450SR 2023 (`F01R00DKAI_X10G04A120`) Bosch MSE6.0 examples, Yamaha MT and Honda X-ADV/ADV350 checksum research. The README declares MIT but provides no license file or copyright notice. Untouched running 450SR factory images reportedly fail two computed records; the Yamaha 896 KiB target is reported only for one 2020 MT-07 example. The listed software strings do not themselves establish the exact binary trailer signature expected by its detection code. The Yamaha word-sum and trailer check and the Bajaj DellOrto checksum are adapted for explicit local-only research copies in `web/yamaha-checksum.js` and `web/bajaj-checksum.js`; the declared MIT notice and missing copyright attribution are recorded in `LICENSES/Moto-ECU-checksum-MIT.txt`. No firmware, binary or programming code is imported. Tests use synthetic files only. A checksum match is not a firmware signature, fitment, calibration approval or flash authorization.
- [DensoToXDF](https://github.com/tientuk3/DensoToXDF) proposes generated Denso map definitions for Suzuki/Kawasaki but has no detected license or exact verified fitment. No generator, definitions or offsets imported.
- [Performance Harley-Davidson Tuning](https://github.com/aaronlumen/Performance-Harley-Davidson-Tuning) is labeled GPL-3.0 and describes dyno tunes, but the README does not establish exact ECU/software fitment, source rights or legal applicability. No tunes or files imported.
- Honda CBR250RR XDF research (listed above) similarly lacks a detected license and includes uncertain scaling. No commercial firmware, ISO standard documents, binaries, paid service manuals, proprietary protocols or ECU keys were bundled.

Unknown/research ECU identities are refused by the server's XDF preview/build
fitment gate; a Marelli filename cannot make a selected unknown family match.
When both a source ECU and a selected ECU are present, unknown or conflicting
source identities are also refused rather than ignored.
This is not proof that a known-family XDF matches a particular software revision.
Before any future calibration feature, obtain redistributable definitions and
known-good, independently validated ECU/software-specific test vectors; do not
use family names or generic checksums as a proxy for exact fitment.

Other requested makes including CFMoto, Yamaha, Husqvarna and Norton have not
been added as supported diagnostic profiles in this increment: sufficient
model-specific transport, application, fitment and independent evidence was not
found. Further vendor manuals or owner-provided captures may support future work.

### Yamaha image inspection

In **Tools → Yamaha MT image checksum**, explicitly select the reported 1 MiB
or 896 KiB scope and choose a plain local binary. The tool validates the
source-described alphanumeric trailer shape and marker, shows the raw stored
word, full-image big-endian word sum, source target and SHA-256 (when browser
crypto is available). It does not validate the user's model claim, identify the
ECU, inspect map contents, verify a digital signature, correct any checksum,
write a file or connect to a vehicle. Different software may share a trailer
shape and sum. The 896 KiB target is reported for only one MT-07 2020 example.
No real image was downloaded or independently validated. Synthetic tests prove
the arithmetic and fail-closed handling only.


### Kawasaki ER-6n 2006 read-only KDS

The desktop/local workstation has a read-only K-Line implementation for the
exact 2006 ER-6n vehicle selection based on iKawa's author-tested source.
Use a K-Line transceiver that supports **10250 baud**, the profile-default
handshake and read-only mode. It sends the source's 25/25 ms wake-up,
addressed StartCommunication, requires the expected `C1 EA 8F`, then sends
`10 80` and the supported `21` sensor requests. Idle keepalive polls RPM rather
than inventing a TesterPresent command. The handler strictly checks addressing,
checksum, response ID and length and refuses other commands. It exposes engine
speed, speed, two temperatures, battery, gear/status and two source-named raw
pressure values. Identification, DTCs, controls, programming and simulation
remain unavailable. ECU identity, market and firmware are not established;
this implementation has **only synthetic tests, no real-hardware validation**.
The source applies decimal weighting to two-byte RPM and speed; it is not a
conventional big-endian integer. The source-tested claim is not independent
verification of this application's UART timing, adapter or electrical wiring.
Do not operate the application while riding.


### Yamaha MT and Bajaj RS200 checksum research copies

The [moto-ecu-checksum source, revision `43ccc5f`](https://github.com/NetworkDir/moto-ecu-checksum/tree/43ccc5f3663e2a175b7217f802bc302830e6862b) reports Yamaha MT checksum repairs matching a commercial tool for listed MT-25, MT-07 and MT-09 SP images, and the Dell'Orto algorithm for three 2024 Bajaj RS200 calibrations. Its README states MIT; see `LICENSES/Moto-ECU-checksum-MIT.txt`. The GuzziOnBoard integrations have **synthetic tests only**; no real images are bundled or independently tested here.

* The explicitly selected Yamaha MT scope requires exactly 1 MiB (target 16-bit big-endian word sum `0x5AA5`) or the source-described 2020 MT-07 896 KiB (`0xE81F`), plus the source's trailer pattern. Inspection reports the stored and proposed word at end minus 8. With explicit confirmation and a mismatching sum, a new research copy may be exported after recalculation and verification; only those two bytes can change. The trailer is not ECU identification and the 896 KiB target is source-confirmed only for that one 2020 MT-07 sample.
* The separately selected Bajaj RS200 tool requires a raw 768 KiB image, the source's DellOrto system signature, and `JL351458010651` exactly at `0x80000`. The extra exact-label gate is our conservative interpretation of the source-reported part and placement; it has not been checked on a real image and may reject applicable reads. It computes the one's complement of the byte sum from `0x80000` through `0x921FD`, stored big-endian at `0x921FE`. The preview shows both hashes and the word difference. Explicit confirmation allows a new research copy, verified before export, changing at most those two bytes.

Files remain local; desktop export uses the authenticated local host and never overwrites an existing file. Neither tool establishes ECU identity, map definition correctness, complete checksum or signature coverage, tuning safety, legality, or flash readiness. They do not alter map-builder gates, generate a matched XDF, read/write an ECU, or modify the input file. Do not flash outputs based on these checks. The upstream source describes real comparisons; our tests do not reproduce those real-image comparisons.

### CFMoto MSE6 record inspection

The local/browser Tools page applies the source's Bosch MSE6 record search to a
user-supplied image (NK250 2024 and 450SR 2023 are the upstream examples). The
fixed `0x140000–0x140400` scan looks for start/end and checksum/complement
records, and sums big-endian words whose starting offsets are less than the
end, following the code rather than its inconsistent inclusive-end comment.
It limits input and work, reports all candidate records and SHA-256, and never
repairs, saves or flashes the image. Random bytes can look like records. The
source says even running, untouched 450SR images can fail the calculation;
neither a match nor mismatch establishes fitment, integrity or flash safety.
The implementation is tested with synthetic data, not real ECU images.


### Triumph Daytona 675 2012 read-only OBD

The desktop/local workstation adapts [daytona-kline](https://github.com/andrewwilke/daytona-kline/tree/d37e96718f5cd82ebde3297c1181c687a922ea32)
(Copyright 2026 Andrew Wilke, GPL-3.0-or-later; see `LICENSES/Daytona-Kline-GPL-3.0.txt`)
for a strictly selected **2012 Triumph Daytona 675** with a K-Line adapter.
It uses the source's 196 ms five-baud `0x33` slow init (up to six tries),
requires `08 08` keywords and address complement, checks the mode 01 supported-PID
bitmap, then reads only the listed OBD PIDs and mode 03 stored codes. It uses
the source's `01 00` as keepalive. ISO frames are lengthless and are collected
as bounded bursts with a quiet-gap and additive checksum. Pending codes, lamp
state, ECU identification, unlock, clearing, outputs, maps and programming
are not implemented. The source says the gauges' SAE formulas were **not
compared with the bike's dash**; the UI marks them unverified. The author
reports one bike and cable tested; this implementation has only synthetic
protocol tests and no real-hardware validation. Do not use it while riding.

Additional review: [ECU Forge](https://github.com/MrAnnix/ecu-forge-app/tree/1099842e7088c4f1b242f8ede02d7bc8dcdcddfc), AGPL-3.0-or-later, is an Android continuity/architecture project whose own README lists end-to-end diagnostics and hardware promotion as next steps. It does not provide an exact matching motorcycle ECU tuning definition for this increment; no code or maps were imported.

## Additional tuning sources

- [HondaECU](https://github.com/roccofz1/HondaECU/tree/dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109), GPL-3.0: 2012 US CBR1000RR XDF, 2012–2013 A01 image example and whole-image checksum algorithm. The definition and scoped offline checksum are integrated as described in `XDF_LIBRARY.md`; the source image is not redistributed.
- [DensoToXDF](https://github.com/tientuk3/DensoToXDF/tree/15fdf85a8c1042c928a9e65ab5a68e354887226a) claims XDF generation for listed Suzuki/Kawasaki Denso ECUs (roughly 2002–2010). It has no detected license; no source code or definitions were copied. Operator-supplied XDFs can be rendered and research-previewed.
- [Performance-Harley-Davidson-Tuning](https://github.com/aaronlumen/Performance-Harley-Davidson-Tuning/tree/a3250e460e1781b8f594e1b400e5a05058d23534), GPL-3.0: source reports Harley Delphi dyno-tuned Technoresearch tunes; the inspected files use `.ori`, not a generic XDF. Customer/VIN-labelled material was not imported.

- [HarleyECUTool](https://github.com/rob9206/lawflo/tree/6255518dc9118d960efa42d6d9dc975926bbd579/ZOOSH_ECU-main/HarleyECUTool) describes a Delphi calibration/tune memory mapping and CAN read/write workflow. A repository example's extracted region matches the documented offset. The mapping is now available in the offline workspace; programming is not enabled. The source's license text also says personal/educational only, so no code or firmware was copied. See `HARLEY_TUNING.md`.

- [HarleyDroid EVO](https://github.com/QuickosssLabs/HarleyDroidEVO/tree/668b63efc05977eb65cb8e84e597ae2205355d4c), GPL-3.0-or-later, copyright 2010–2012 Stelian Pop and 2026 Quickosss: J1850 diagnostics and explicitly best-effort model/year-dependent HDLAN telemetry. Adapted for offline frame/capture analysis and a restricted read-only J1850 ELM327 serial session, synthetic tests only; source and implementation discrepancies and license are recorded in `HARLEY_TUNING.md`.

## Kawasaki Ninja 7 Hybrid read-only CAN diagnostics

[Matt Githens' Kawasaki CAN research](https://github.com/mgithens1/kawasaki-can-hack/tree/26820ddf88d682c7071b0825252c7fa0b82c709a), MIT (notice `LICENSES/Kawasaki-CAN-Hack-MIT.txt`), reports live observations of a Ninja 7 Hybrid, described as 2024+. GuzziOnBoard now exposes a **source-scoped read-only** profile in the desktop/local workstation: choose Kawasaki → Ninja 7 Hybrid → year, CAN SocketCAN channel, read-only mode. It uses the source's 500 kbit/s, request `0x764`, response `0x746`, zero-padded ISO-TP and KWP service payloads, not K-Line headers. The source does not establish applicability to every market/year/software. Verify the motorcycle and adapter independently; this implementation has **synthetic tests only**, not physical validation. Stop the engine, secure the motorcycle, and do not operate the app while riding.

The implemented allowlist is `10 80` session start, `1A 80` raw identification, `18 01` fault read, `3E` keepalive, and a fixed list of source-described `21` live PIDs. The source confirms a zero-DTC response; our strict interpretation of nonzero records follows its candidate parser and is not confirmed with a real nonzero capture. Raw identity is displayed as an ASCII candidate, not treated as a verified hardware or software identifier. Invalid, negative, wrong-ID and truncated responses are not promoted into readings. Gear, alternate speed and DTC status interpretation are explicitly uncertain. Different CAN IDs, service mode, simulator, security access, fault clears, routines, memory reads/writes and flashing remain blocked. Neither this profile nor its observed ECU IDs validates an XDF, checksum, security key, ECU image or calibration.

For tuning, [DensoToXDF](https://github.com/tientuk3/DensoToXDF/tree/15fdf85a8c1042c928a9e65ab5a68e354887226a) describes SuperH/M32R research across numerous 2002–2010 Kawasaki/Suzuki ECUs, not the Ninja 7 Hybrid. [M32R bootloader research](https://github.com/tientuk3/m32r-bootloader-protocol/tree/3bffab1ac370773de12bc144566d9559f012b128) describes bench read/write for at least Suzuki M32R ECUs and boot-pin/unlock requirements; it does **not** establish a Kawasaki fitment, compatible security code, checksum, recovery or this application's protocol. Neither repository has a detected license, so code, example firmware and definitions were not bundled. The Ninja 7 source reports its security algorithm unresolved and download unsupported, so it cannot substantiate a full tuning/flash unlock. User-supplied maps can be examined only through existing research-preview gates. Further unlock requires an exact ECU/firmware match, licensed definition and checksums, a documented memory protocol and safe recovery, and integration validation.

### Opt-in generic OBD-II over 11-bit CAN

The desktop workstation includes **Generic OBD-II 11-bit CAN (read-only,
ECU-only)** as an explicitly chosen profile for an ECU that actually supports
standard OBD-II/ISO 15765-4. This is not a model fitment claim, including for
the 2026 Ninja 650. It uses one selected 11-bit physical request/response pair
(`7E0`–`7E7` / corresponding `7E8`–`7EF`), zero padding and 500 kbit/s via a
compatible python-can adapter, **not** an ELM327 serial dongle. Configure the
adapter and correctly wired motorcycle connector for the vehicle; physical
CAN rate and connector wiring cannot be inferred from a plug. The default pair
is only a standard starting point, not evidence of a particular ECU's address.
No automatic address or bitrate scan is performed. On SocketCAN, configure the
interface's bitrate separately before connecting.

The connection requires a valid mode `01 00` supported-PID response. Only the
supported subset of a short standard mode 01 PID list and mode 03 stored
emission-related faults are requested. Only the selected responding ECU is
represented; an empty mode 03 answer does not establish that other modules,
pending faults or manufacturer-specific faults are clear. A timeout or
invalid response is an error, not a clean bill of health. This opt-in profile
can optionally query Mode 09 PID 00 and, only when advertised by its bitmap, read a 17-character VIN (PID 02) and/or up to four 16-byte calibration identifiers (PID 04) from that selected ECU. Unsupported fields are not requested. This vehicle-information response is not ECU identity or proof of vehicle fitment, and does not set the identified safety gate. VIN and raw responses can appear in session logs; treat logs as sensitive. Mode 09 is not supported by all ECUs; an unsupported or malformed response is an error. Standard command/decoder reference: [python-OBD at a378bdd8](https://github.com/brendan-w/python-OBD/tree/a378bdd81d58c67d08050e4244173a9a7dbda73d). This integration is not copied from that source and has only synthetic tests. It has no confirmed ECU identity, ECU image read, memory access, security, fault clear,
actuator control or writing. It cannot bypass a manufacturer's protocol or
security. GuzziOnBoard has only synthetic and virtual-CAN tests, no motorcycle
validation for this implementation.

Standard SAE mode 01 PID scaling is reused from our 2012 Daytona profile,
adapted from [daytona-kline](https://github.com/andrewwilke/daytona-kline/tree/d37e96718f5cd82ebde3297c1181c687a922ea32), copyright 2026 Andrew Wilke, GPL-3.0-or-later; see `LICENSES/Daytona-Kline-GPL-3.0.txt`. [RyoheiHashimoto/obd2](https://github.com/RyoheiHashimoto/obd2) describes standard OBD CAN physical addressing and supported-PID discovery; it is a protocol reference, not a bike-fitment source and no code was copied from it.

## 2012 Versys 650 and 2011 GSX-R600 K-Line

[Aster94's Keyword-Protocol-2000, revision 94c4ff06](https://github.com/aster94/Keyword-Protocol-2000/tree/94c4ff0675cc24d7b21c98da0fca2d14b892d5f3), reports successful tests of **2012 Kawasaki Versys 650** and **2011 Suzuki GSX-R600**. Its `ISO.h`, `KWP2000.cpp` and `KWP2000.h` contain Aster94's MIT notices; the repository also contains a GPL-3.0 license. Both notices are included in `LICENSES/Keyword-Protocol-2000-source-MIT.txt` and `LICENSES/Keyword-Protocol-2000-GPL-3.0.txt`. This desktop adaptation has synthetic protocol tests only; no motorcycle, market, ECU part number, software revision, or calibration has been validated by GuzziOnBoard. Do not extend the selections to other model years, models or the 2026 Ninja 650. Stop the engine and secure the motorcycle before connecting; never operate the workstation while riding.

Select the exact make/model/year, an appropriate isolated K-Line-to-USB adapter and bike-specific diagnostic harness, read-only mode, and the profile-default handshake. Both profiles use 10400 baud, 1-second idle, 25/25 ms fast init, source address F1, ECU address 11 (Versys) or 12 (GSX-R), and require an addressed `C1 EA 8F` wake response. They use source-described, explicitly length-prefixed KWP frames with checksum/address/response validation. Other key bytes are rejected rather than inventing negotiated formats; a real ECU using different keys will not connect. The Versys starts `10 80`, reads the fixed `21 04/05/06/07/09/0B/0C` list, and polls `21 0B` for keepalive. The GSX-R queries `21 08` once per live-data poll and expects the emulator's full 50-byte sensor-data block; `3E 01` is its source keepalive. Only these exchanges are permitted, not DTC, clear, security, memory, write or programming services. No ECU identification or simulator is claimed.

These numbers are **candidate source conversions**, not independent calibrations. The source's C++ stores several results in integer types; the workstation shows fractional arithmetic in some cases rather than reproducing every truncation or unsigned wrap. For Versys speed and throttle it displays the first source byte (up to two response bytes accepted), and for GSX-R battery it deliberately displays the raw byte: the source labels its `byte*100/126` output as voltage but its units are unclear. The GSX-R displayed fields all carry the actual local ID `08`; raw samples contain the individual source-offset bytes, not the full snapshot. The older SV650 source uses materially different conversions and explicitly warns that some are inaccurate; its 2007 profile remains offline-only. Missing, truncated, unexpected, wrong-address or invalid-checksum data is rejected. Uncertain values do not drive the workstation's engine/battery safety state.

### Honda flash-reader research, not an enabled feature

[WiseNoodle/honda-moto-ecu-suite at 85431bd8](https://github.com/WiseNoodle/honda-moto-ecu-suite/tree/85431bd831b2c50a640fac35dccf36c09df20c07), GPL-3.0, describes a Honda K-Line tool for 2007–2018; its README explicitly marks **EEPROM read/write and flash writing broken**. Its flash-read code has an ignition cycle, two security messages, then `82 82 00` reads in decreasing block sizes until a read fails. Its checksum table is not an exact, verified per-ECU read geometry or an assurance that failure means an image is complete. Its protocol has now informed the separate, explicitly confirmed MGZ-A03 research reader below. Its generic open-ended read is not enabled: precise ECU identity, bounds and response semantics are not established for the other supported models. An ECU checksum listing, security exchange or partial file is not proof of a complete memory dump, and this source does not establish Kawasaki support.


## Honda CB500F DashBle: ECU-only read-only K-Line

[DashBle at 9c65818d](https://github.com/atoid/DashBle/tree/9c65818d13dde39b8d8203736b43109eb84a9651) and [Dash at 532d0f4f](https://github.com/atoid/Dash/tree/532d0f4fef1b2e11a15f1c6663fb5351757f87b8), copyright 2018 atoid, MIT (`LICENSES/DashBle-MIT.txt`), describe a CB500F and include complete checksum-valid table 11 and D1 examples. **The source does not identify the bike's year, market, ECU part or software.** The desktop offers an explicit **ECU-only** `Honda CB500F DashBle` profile, not an automatic model/year association or a claim that all CB500Fs or any particular MGZ-A03 use this protocol. The underlying integration has synthetic tests and tests against the source's published bytes only; GuzziOnBoard has not tested it on hardware. Select the profile via the ECU override, physical K-Line adapter and read-only mode. Stop the engine, secure the motorcycle and never use the app while riding.

The source's 10400-baud wake uses 70 ms low, 130 ms high, `FE 04 FF FF`, 50 ms delay and `72 05 00 F0 99`; the workstation requires the corroborated Honda `02 04 00 FA` init response. It restricts requests to `72 05 71 11 07`, `72 05 71 D1 47`, and `72 05 71 00 18` for a candidate raw ECM ID. The latter interpretation comes from a separate HondaECU source and is not confirmed for the DashBle bike. Table 11 is exactly 25 bytes and D1 exactly 11 bytes, unlike the 2005 CBR600RR's table layouts. Response address, table, length and checksum are checked. Each selected table is requested once per poll; sensor and status failures are isolated. The TPS byte and D1 engine byte are displayed **raw**; the source notes several D1 engine-byte values, so these are not binary engine-state determinations. Gear/clutch text is a candidate, not confirmed gear position. Unknown bytes and guessed AFR/consumption are not decoded. These values cannot satisfy safety-state checks. The five-byte table-00 value is a raw candidate, not a confirmed part number or programming identity. No fault memory, arbitrary request, ECU flash writing or simulator is provided. A separate experimental read attempt is available only for an exact live MGZ-A03 candidate, as described below.


### Experimental MGZ-A03 ECU-image read attempt

The `Honda CB500F DashBle` ECU-only profile has a **separately confirmed, read-only research attempt** for exactly the HondaECU-reported ECM ID `01 01 25 05 01`, associated by that source with `38770-MGZ-A03` / CB500F and CBR500R 2013–2016. The source's example image is 256 KiB and its ECM-ID table records offset `0x17FC7` and checksum location `0x3FFF8`; our existing offline MGZ-A03 provider implements the source-reported whole-image 8-bit sum. These claims do not prove a particular attached bike is this ECU. The session re-queries table 00 and **requires the five-byte match before any security or memory request**. It then sends the fixed two-message security exchange from [WiseNoodle/honda-moto-ecu-suite at 85431bd8](https://github.com/WiseNoodle/honda-moto-ecu-suite/tree/85431bd831b2c50a640fac35dccf36c09df20c07), GPL-3.0 (`LICENSES/Honda-Moto-ECU-Suite-GPL-3.0.txt`), and fixed sequential `82 82 00` block reads using the response/address framing documented by [PhatDatPQ/eculib at 7921cc46](https://github.com/PhatDatPQ/eculib/tree/7921cc46551fd26d487ec778e8822ace4777899e), MIT (`LICENSES/eculib-PhatDatPQ-MIT.txt`). We include both licenses; no ECU firmware was bundled.

This project has **not tested the security exchange, transport, timing or read against a real ECU**. The source tool explicitly reports its EEPROM read/write and flash writing broken; its flash-read loop does not by itself prove completeness. An incorrect/unsupported security sequence could be rejected or cause a lockout; **there are no automatic retries**, and the attempt stops on the first mismatch, bad checksum, truncated block, or error. It sends no erase, write, EEPROM, actuator or arbitrary-address command. The read is available only in physical K-Line read-only mode after a separate acknowledgement in the Firmware view. Keep engine stopped, ignition and adapter powered, use stable battery/bench power, and disable computer sleep. Progress is source-based, not a duration guarantee.

The program reads only the fixed 0–`0x3FFFF` range in blocks of at most 12 bytes, checks each framed reply, then requires the source-reported ECM ID at `0x17FC7` and the whole-image sum. Failure produces no output file. Success writes a uniquely named **research file** and metadata with `verified_backup: false`; a checksum and matching bytes are not independent proof of completeness, provenance, fitment or flash safety. The implementation deliberately cannot create a verified backup or base map for this profile, and ECU writing remains blocked. This is not support for other MGZ IDs, other Hondas, or the 2026 Ninja 650.


## BRT Juken 5 aftermarket ECU map research

[cfbird/juken5 at 8585b947](https://github.com/cfbird/juken5/tree/8585b94715e5db01eb37bdd81c7b0a0a91c1d739), copyright 2026 Charles Bird, MIT (`LICENSES/Juken5-MIT.txt`), reverse-engineers an aftermarket Juken 5 PC application. It explicitly reports **no testing against real hardware**, unconfirmed sensor field order/scaling, guessed bulk map encoding and unconfirmed cell orientation. The desktop/hosted Tools panel accepts only a user-supplied exactly 10,248-byte candidate raw core block and interprets the source's five consecutive 1,281-cell arrays: signed little-endian 16-bit FuelBase, unsigned 16-bit InjTmg and IgnTmg, and 8-bit FuelCor1 and FuelCorTB1. It reports ranges and can export one table as a **linear-index, raw-value CSV**. No data leaves the browser, and the original is not changed. Size, byte order and plausible values do not identify a controller or establish encoding, orientation, units, calibration safety or completeness. This is not an ECU connection, an ECU flash image, an edit/build tool or a flash-ready tune. Bulk protocol, live data and ECU programming are not implemented here.

### Further source leads: CCM / Husqvarna and Mikuni

[gobftald/CCM450-diag at 43104d2c](https://github.com/gobftald/CCM450-diag/tree/43104d2cfca93368b3eac2f396e65754e1493728) reports the author's own CCM 450 Adventure Keihin KMSK16 investigation and reports the Husqvarna 449/511 community subsequently confirmed the same ECU, software and access code. The repository describes a diagnostic gateway as a planned milestone and includes job notes; no repository-level license was found. We have not incorporated its code, job tables or keys, and have not established the precise wake, tested read-only requests, or ECU image geometry needed for a GuzziOnBoard session. Those motorcycle connections therefore remain unimplemented; this is a lead for future investigation, not a negative claim about the author's results.

[f6hic/iBeatRedux at 01f4bade](https://github.com/f6hic/iBeatRedux/tree/01f4bade90f394d8a2c6474d8c8ff13a5cb0e5a0) describes work around Mikuni iBeat but contains decompiled and original application files with no repository-level reuse license identified. No code or binary assets from it have been incorporated, and no motorcycle connection is claimed from it. The separate [Suzuki-SDL-Viewer at fcba84e1](https://github.com/lostconsequently/Suzuki-SDL-Viewer/tree/fcba84e18f0ae674967dd7f9488866f4d313d890) reports testing its SDL protocol on a 1997 Suzuki Swift car; that does not establish motorcycle fitment.

## Yamaha MT-03 660 (2010) dashboard-stream observation

The local Linux workstation's **Discovery → Yamaha MT-03 660 (2010)** panel
listens for two seconds at 16064 baud on an explicitly selected FTDI `/dev/ttyUSB*`
port. It follows [smiddelkoop/yamaha-kline-ubuntu at 0f7fef82](https://github.com/smiddelkoop/yamaha-kline-ubuntu/tree/0f7fef82d1987923198b53ffa001d09ed1ceae4e),
copyright 2026 Sven Middelkoop, MIT (`LICENSES/Yamaha-KLine-Ubuntu-MIT.txt`).
The source credits terrafirma2021's Yamaha K-Line Tool and Sniffer, reports
real-log validation and MT-03 660 2010 testing, and describes other pre-2015
Euro 3 bikes as possible applications. This integration is intentionally scoped
to the explicitly selected, source-tested MT-03; it has **synthetic tests only**.
It requires the bike's instrument panel to already be polling the ECU and the
operator to verify the FTDI KKL interface, diagnostic connector and wiring.
Selecting the tool does not identify a bike or establish compatibility with
another Yamaha. Opening a serial adapter can change modem/electrical control
lines; verify its K-Line interface before connecting.

The app uses a bounded sliding checksum synchronizer for source-described five-
or six-byte frames, excludes a couple of source-described noise patterns, and
shows the last candidate in the current window with its raw bytes. It reports
RPM as a candidate, speed and temperature bytes raw, `0xFF` temperature as a
source-reported unavailable candidate, and the status byte raw. No fault-code
meaning or temperature scaling is asserted. A matching additive checksum does
not prove alignment or that a frame is telemetry: immobilizer and other traffic
can accidentally match. An empty window clears the result. The app sends no
request bytes, wake-up, ECU command or immobilizer operation; it cannot read a
memory image, clear faults or tune the ECU. This is not a safety instrument.

### More standard OBD channels across compatible motorcycles

The opt-in generic OBD CAN profile also offers engine runtime (PID `1F`), fuel
level (`2F`), barometric pressure (`33`), control-module voltage (`42`), oil
temperature (`5C`) and fuel rate (`5E`), using standard OBD response lengths and
scaling. These channels are disabled by default and will only be queried if the
selected ECU advertises them. Additional support bitmaps (`20`, then `40`)
are queried lazily and only when the previous bitmap advertises continuation;
a malformed bitmap does not authorize a subsequent value request. Neither
support bits nor standard formulas prove a particular motorcycle's fitment or
that its sensors are accurate. [python-OBD at a378bdd8](https://github.com/brendan-w/python-OBD/tree/a378bdd81d58c67d08050e4244173a9a7dbda73d)
is a standard command reference. A separate [KTM-OBD project at cc0e7a23](https://github.com/ktmrc3902022/KTM-OBD/tree/cc0e7a23802f4796361a0138fd4d96f642580f27)
targets the 2022 RC 390 using an OBDLink Bluetooth adapter, but does not
establish that this project's SocketCAN integration or any specific PID works
on that motorcycle; no code was copied and no model-specific connection was
enabled from it.
