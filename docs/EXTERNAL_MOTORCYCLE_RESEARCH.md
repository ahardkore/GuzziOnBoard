# External motorcycle and calibration research

Reviewed 2026-10-28. These sources are useful references, not evidence that a
Moto Guzzi ECU supports a particular service, memory layout or checksum. Code,
calibration data, images and firmware can have different rights; a public file
is not automatically licensed for redistribution. Links are research leads,
not endorsements or safety approvals.

| Source and inspected revision | What is useful here | Limitations / disposition |
|---|---|---|
| [motorcycle-service-db](https://github.com/ramblenride/motorcycle-service-db), `3d21b582720e18c9f80e254bfdaf3875cf443990` | CC BY-SA service data and a JSON service-template shape. The independently written worksheet can review user-selected templates and calculate from documented service anchors. | No Guzzi data is present at the inspected revision; no database contents bundled. Templates are unverified for the user's vehicle, have separate license terms, and initial/severe-use rules need manual review. |
| [OpenRaceTelemetry](https://github.com/brendisurfs/OpenRaceTelemetry), `3daf1322dee956f77bdd838978c5d5b962572dec` | GPL-3.0 motorcycle telemetry project and a direction for possible GPS/IMU workflows. GuzziOnBoard already provides an independently implemented read-only live timeline. | Upstream firmware and desktop UI are incomplete, with hardware functions marked TODO. No firmware, telemetry hardware driver, sensor math, or code imported or claimed to be working with GuzziOnBoard. |
| [manual-rag-assistant](https://github.com/SRodriguezSpina/manual-rag-assistant), `972b8c7c2db28aea6018d367489caf14c07f6cc9` | MIT-licensed, source-attributed manual-excerpt search workflow informed the independent local text search and service arithmetic. | Upstream uses a Kotlin MCP server, local embedding models, and separate copyrighted PDFs; none are bundled or ported. Our tool only searches user-supplied text literally, without AI, PDF extraction, or page validation. |
| [motorcycle-canbus-info](https://github.com/talss89/motorcycle-canbus-info), `b65a4a8d58bbf60c6d9bf5823d1df5a0f4d4cccc` | MIT-licensed, incomplete sniffing notes for the 2017–2021 Triumph Tiger 1200 Gen 3, including switch and TPMS observations. The general research workflow informed the independent raw-byte summary in CAN discovery. | Triumph observations are not Guzzi protocol evidence; parts are explicitly uncertain and the pressure-change status descriptions conflict. No IDs, signal definitions, commands or code were imported. |
| [DucatiPanigaleCanBus](https://github.com/renatobo/DucatiPanigaleCanBus), `03e7127c69ee3398c03076352ac93bbd3f795ce2` | MIT-licensed source for selected Mitsubishi Ducati CAN broadcasts. Adapted as an **opt-in offline** decoder, retaining raw frames; upstream credits and MIT notice are in `LICENSES/DucatiPanigaleCanBus-MIT.txt`. | Upstream names specific Ducati models. No automatic vehicle detection, live capture, transmission or Guzzi compatibility. The adaptation reports below-zero temperatures as signed integers rather than allowing unsigned wrap. Test vectors are synthetic; interpretation is not independently bike-validated. |
| [moto-service-tool](https://github.com/slava-fm/moto-service-tool), `ac39e456fdc9e93c1a0c64c426c8b6d0e1385e45` | MIT-licensed Ducati Panigale V2 service workflow and ELM327 research reference. | Reset routines write to the ECU and are reported validated only for the author's stated Ducati fitments. No reset commands or IDs imported into Guzzi profiles; Guzzi operations remain gated. |
| [Ducati-Desmo-Shim-Calculator](https://github.com/EhrenTheMan/Ducati-Desmo-Shim-Calculator), `146d2e93261d9978f15258af1739751e327aed07` | The idea of a clearance worksheet informs the independent, manual-only worksheet in Tools. | No license was found in the repository metadata when reviewed. No code, presets, specifications or shim data copied. Guzzi engines may use screw adjusters; the user must verify the mechanism and specs. |
| [Engine Tune Repository](https://github.com/Snoman002/Engine-Tune-Repository-TunerPro-EFIlive-TunerCat), `61136c6d0d59506d60a01b4ff7176679d9903fd4` | Example of organizing definitions and calibrations by ECU and software identity; the existing project format already locks image and XDF hashes. | Aggregates files from various authors and says validity is unverified; no overall license found. No definitions or binaries copied or assumed compatible. The duplicate user link refers to the same repository. |
| [ZedSuite](https://github.com/LeZed97/ZedSuite), `77d75fb9e28df04379fd6d1912197947f1cce0c0` | GPL-3.0 local editing, versioning and positive ECU-identification design reference. Existing map editor provides staged edits, undo and hash-locked projects. | Automatic detection targets specific VAG Bosch ECUs; its identification patterns and checksums are not Guzzi evidence. No code imported. |
| [CBR250RR ECU binary definition](https://github.com/kelvinvalencio/cbr250rr-ecu-binary-definition), `8be351c718205843c842c7abe62eafa51bdac218` | Documented example of hardware/software-specific XDF layout and uncertainty. | Honda MC51 Keihin, not a Guzzi definition; no repository license found. No binary, XDF, offsets or scales imported. |
| [moto-ecu-checksum](https://github.com/NetworkDir/moto-ecu-checksum), `43ccc5f3663e2a175b7217f802bc302830e6862b` | Its README says MIT and documents useful model-specific checksum verification and pre/post examples. | README evidence covers its listed Bosch, Yamaha, Honda and other profiles—not an exact Guzzi profile. No checksum implementation copied or auto-enabled. A matching Guzzi image, licensed provenance and independent test vectors are prerequisites for any plugin. |
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
