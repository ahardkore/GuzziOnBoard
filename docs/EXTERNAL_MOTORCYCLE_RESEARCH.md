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
| [moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum), `43ccc5f3663e2a175b7217f802bc302830e6862b` | Its README says MIT and documents useful model-specific checksum verification and pre/post examples. | README evidence covers its listed Bosch, Yamaha, Honda and other profiles—not an exact Guzzi profile. The Yamaha checksum layout and Bosch MSE6 record heuristic are adapted as offline research inspections only; no plugin or auto-enabled checksum repair. A matching Guzzi image, licensed provenance and independent test vectors are prerequisites for any Guzzi plugin. |
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

## Honda 2005 CBR600RR: offline research only

Source: [andreibaw/Honda_K-Line_KWP2000](https://github.com/andreibaw/Honda_K-Line_KWP2000/tree/f3bd42ff438e840e4da3802dd5038a195f3d67be), commit `f3bd42ff438e840e4da3802dd5038a195f3d67be`, Honda ECU Manager, Copyright (C) 2025 andreibaw, GPL-3.0-or-later. `web/honda-offline.js` adapts the response table byte offsets, scaling and two's-complement checksum from `src/HondaKWP2000.cpp`. The upstream GPL license is preserved in `LICENSES/Honda-KLine-GPL-3.0.txt`; source and attribution must accompany distribution of the combined AGPL application in accordance with the applicable licenses.

The author reports testing on a **2005 Honda CBR600RR**, but does not establish an ECU part number, all variants/markets or compatibility with other years/models. The catalog entry is an inferred research placeholder, not a confirmed ECU family. This application does not implement Honda initialization, requests, a Honda simulator, identification, live reading, or any physical diagnostic operations. The research entry blocks both physical and simulated connections. Other catalog entries and tools do not establish Honda compatibility.

The shared browser/desktop Tools page accepts pasted complete hex responses, validates exact table lengths and the source's checksum, and presents table 10/D1 results as **candidates** together with the original bytes. D1's combined neutral/clutch flag is not a confirmed gear. Results must not be used as safety measurements or treated as fitment proof. No capture, data or model selection is uploaded by the decoder. There is no stream reconstruction, frame pairing or diagnosis.

Important source limitation: the two example received frames in the upstream README do **not** satisfy its own checksum algorithm (their byte sums modulo 256 are `0x71` and `0x0d`). They are not used as validated captures. Tests instead create clearly synthetic checksum-valid frames and verify that those published examples are rejected. A valid checksum establishes only internal frame consistency, not real-world correctness. GuzziOnBoard has not tested this decoder on a real motorcycle; independent captures and corroboration are needed before adding bike-side support.

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

- [moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum/tree/43ccc5f3663e2a175b7217f802bc302830e6862b) reports CFMoto NK250 2024 (`F01R00DG1Z_X10A04B228`) and 450SR 2023 (`F01R00DKAI_X10G04A120`) Bosch MSE6.0 examples, Yamaha MT and Honda X-ADV/ADV350 checksum research. The README declares MIT but provides no license file or copyright notice. Untouched running 450SR factory images reportedly fail two computed records; the Yamaha 896 KiB target is reported only for one 2020 MT-07 example. The listed software strings do not themselves establish the exact binary trailer signature expected by its detection code. The Yamaha word-sum and trailer check is adapted for an explicit, local-only research inspection in `web/yamaha-checksum.js`; the declared MIT notice and missing copyright attribution are recorded in `LICENSES/Moto-ECU-checksum-MIT.txt`. No firmware, binary, repair or programming code is imported. Tests use synthetic files only. A checksum match is not a firmware signature, fitment, calibration approval or flash authorization.
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
