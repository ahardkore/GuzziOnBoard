# Documentation index

GuzziOnBoard's docs fall into four groups. Start with the first one.

## 1. Start here

| Guide | Read it for |
| --- | --- |
| [README](../README.md) | What the project is, what it refuses to do, how to run it |
| [Architecture](ARCHITECTURE.md) | How the layers fit together, and where the trust boundaries are |
| [User workflows](USER_WORKFLOWS.md) | What a session actually looks like |
| [HTTP API](API.md) | Every route, its handler and the error contract |
| [Desktop application](DESKTOP.md) | The installed app: window, exports, self-test, logs |

## 2. Safety and evidence

| Guide | Read it for |
| --- | --- |
| [Programming](PROGRAMMING.md) | What is enabled, what is blocked, and the acknowledgements in between |
| [Physical validation](PHYSICAL_VALIDATION.md) | What counts as evidence, and what a validation record must contain |
| [Checksum & decoder evidence](CHECKSUM_AND_DECODER_EVIDENCE.md) | Sources and pins behind each decoder |
| [Prior art](PRIOR_ART.md) | What this project learned from, and what it did not copy |
| [DynoAI and uploads](DYNOAI_AND_UPLOADS.md) | Why research binaries are in the repository and never served |
| [ECU number research](ECU_NUMBER_RESEARCH.md) | Part, hardware and software identifiers, with attribution |

## 3. Protocols and hardware

| Guide | Read it for |
| --- | --- |
| [Protocol notes](PROTOCOL_NOTES.md) | The KWP2000 / K-Line / CAN behaviour per family |
| [Handshake protocols](HANDSHAKE_PROTOCOLS.md) | Slow-init and fast-init, and where each is used |
| [KMSK16 on K-Line](KMSK16_KLINE.md) · [Brand tools](BRAND_TOOLS.md) | Brand-specific decoders |
| [Intrepid hardware](INTREPID_HARDWARE.md) · [J2534 and projects](J2534_AND_PROJECTS.md) | Adapter support and its licensing |
| [7SM workflow](7SM_WORKFLOW.md) · [Harley tuning](HARLEY_TUNING.md) | The two most-developed families |

## 4. Maps, tools and research

| Guide | Read it for |
| --- | --- |
| [XDF library](XDF_LIBRARY.md) · [Checksum plugins](CHECKSUM_PLUGINS.md) | Calibration definitions and the plugin contract |
| [Recommendation packages](RECOMMENDATION_PACKAGES.md) | The evidence format a map change must carry |
| [Protocol updates](PROTOCOL_UPDATES.md) · [Hosted read sharing](HOSTED_READ_SHARING.md) · [Cloudflare deployment](CLOUDFLARE_DEPLOYMENT.md) | The signed-update and opt-in sharing paths |
| [Offline toolkit](OFFLINE_TOOLKIT.md) · [Format tools](FORMAT_TOOLS.md) · [Bench calculators](BENCH_CALCULATORS.md) | Tools that never touch a motorcycle |
| [Help module](HELP_MODULE.md) | The in-app help content and how it is tested |
| [Workshop reference tools](WORKSHOP_REFERENCE_TOOLS.md) | The external tools each utility was checked against |
| [External motorcycle research](EXTERNAL_MOTORCYCLE_RESEARCH.md) | The source review behind the cross-brand coverage |
| [Tool expansion research](TOOL_EXPANSION_RESEARCH.md) | Candidate tools, brand by brand |
| [Honda VFR research](HONDA_VFR_RESEARCH.md) | Source-scoped reads and what remains unimplemented |
| [Buell DDFI research](BUELL_DDFI_RESEARCH.md) | The Delphi-derived Buell path |
| [BikeStudio reference](BIKESTUDIO_REFERENCE.md) · [ECUbus Pro research](ECUBUS_PRO_RESEARCH.md) · [rusEFI and Power Vision](RUSEFI_AND_POWERVISION_RESEARCH.md) | Third-party tool references and their limits |
| [Atlas-inspired workspace](ATLAS_INSPIRED_WORKSPACE.md) | Where the workspace layout came from |

## Research snapshots (dated, do not treat as current)

[Audit, 2026-10-07](AUDIT-2026-10-07.md) · [Capture search, 2026-11-03](CAPTURE_SEARCH_2026-11-03.md) · [ECU protocol sweep, 2026-11-04](ECU_PROTOCOL_SWEEP_2026-11-04.md) · [Source re-audit](SOURCE_CODE_REAUDIT.md)

These record what was known on a date. Where a snapshot and the code disagree,
the code and its tests are current; the snapshot explains why a decision was
made, not what the app does today. Anything still load-bearing has been folded
into one of the guides above.

[Capability parity](CAPABILITY_PARITY.md) is a live table rather than a
snapshot: it is meant to be updated as capabilities move.
