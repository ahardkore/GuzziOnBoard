# Additional motorcycle sources: live diagnostic review

Reviewed 2026-10-30. GitHub links below pin the reviewed snapshots. Source
claims and GuzziOnBoard tests are different: all new GuzziOnBoard integration
in this review is **synthetic-tested only**, with no physical motorcycle or
adapter test. Source-listed features are not automatically implemented here.

| Source | License | Findings and application |
|---|---|---|
| [TrECU](https://github.com/singular0/trecu/tree/2969212aa4628d4e207c2858a29224cde53e6222) | GPL-3.0 | Author reports live OBD on one 2009 Triumph Bonneville 865 EFI. Added separately selected desktop K-Line read-only profile using the existing Daytona ISO 9141 implementation, support bitmaps, Mode 01 and stored Mode 03 only. Added optional O2 and module-voltage PIDs with lazy advertised bitmap-page discovery. TrECU includes further identity, pending and clear functions; those are **not** added here. Source states no tuning or programming. |
| [MOTOHUD](https://github.com/eldonjakee08/MOTOHUD_Project/tree/2ec879d8c3392764e6e3c72d8a2009ddbf482e8d) | No license found | HUD prototype; application firmware and hardware fabrication are listed as pending. No motorcycle ECU read/write recipe imported. |
| [MotoRemap Pro](https://github.com/grayjin850/motoremap-pro/tree/afd90e78dd41a7cd27db6f3d42a433ecbec61f31) | No license found | Honda Click 125i and Yamaha Aerox concepts, protocol, read/write and presets; earlier skeleton was later replaced by Android USB code. Registry explicitly calls map offsets approximate, and documentation calls for hardware validation. Hardware-proven fitment, checksum, recovery and specific memory read/write sequences are not established by this review; no source code, flash recipe or estimated offsets imported. |
| [Moto_CAN](https://github.com/P-Ramos16/Moto_CAN/tree/b137175b6b71a9f25e7beb2d31e3a91dda0ef6e0) | No license found | Experimental translator between AIM Taipan aftermarket ECU and Bosch screen, described for 2023 KTM SX-F 250. Not a factory ECU flash protocol. |
| [Project Hayabusa](https://github.com/Ka1y0/Project_Hayabusa/tree/6ab4b88529b4d8b826c4a1b187cb5b69f46eab44) | Apache-2.0 | Research UI for local data; explicitly no vehicle communication layer or ECU writer, no production decoder. |
| [Sigma Racer EFI](https://github.com/sigmatactical-org/sigma-racer-efi/tree/5670390da62e64a2b87351c46ebad28695d2dfc4) | MIT OR Apache-2.0 for code; branding excluded | Separate aftermarket microRusEFI firmware, Yamaha CP3 profile, stage-1 characterization log. Sensor logs use defmt, not an ordinary text serial ECU interface; source says tuning CAN/USB is future work and several engine values are placeholders. Not the stock Yamaha ECU or the existing rusEFI protocol. |
| [837622923/diagnostic](https://github.com/837622923/diagnostic/tree/d340907758d2a9253e78b6ea774ea2ee1a950e5d) | MIT | GitHub metadata describes a Honda display, but this pinned default-branch content is a graph-neural-network research repository, not Honda diagnostic code. No Honda protocol inferred from metadata. |
| [moto-service-tool](https://github.com/slava-fm/moto-service-tool/tree/ac39e456fdc9e93c1a0c64c426c8b6d0e1385e45) | MIT | Previously reviewed Panigale V2 ELM diagnostics/service resets. Source scope and status in `EXTERNAL_MOTORCYCLE_RESEARCH.md`; no service-reset commands imported into unrelated profiles. |
| [Cut-policy audit](https://github.com/d3sd1/2026-cut-policy-audit-jfi/tree/117157a44e22fdbf43bf61527729de4019f074b0) | MIT | Analysis of logged broadcast racing ECU cut channels. Data are external; analysis isn't a diagnostic memory-read or tuning interface. |
| [RACCOON-V2](https://github.com/siddharthathula/RACCOON-V2/tree/2975a972f9d0f6cf84e17611d8ec035013566806) | No license found | Previously reviewed standalone aftermarket ECU and tuner; source says never run on an engine. No stock ECU read/write path derived. |
| [daytona-kline](https://github.com/andrewwilke/daytona-kline/tree/d37e96718f5cd82ebde3297c1181c687a922ea32) | GPL-3.0-or-later | Previously adapted ISO 9141 mode 01 and stored fault reader; new Bonneville profile reuses this implementation, whose upstream attribution and license are in `EXTERNAL_MOTORCYCLE_RESEARCH.md` and `LICENSES/Daytona-Kline-GPL-3.0.txt`. |
| [ecu_diagnostics](https://github.com/rnd-ash/ecu_diagnostics/tree/45df8bce561b66e66225a65e17340fd7f3f26749) | GPL-3.0 | General Rust UDS/KWP/OBD library, not a motorcycle-specific security algorithm or map; source lists ISO-TP, LIN, J1850 and DoIP as work in progress. No code imported. |
| [MotoLink](https://github.com/fpoussin/MotoLink/tree/7879a8567dd43d467506aa8c613f310f0deb2fdb) | GPL-3.0 | Previously reviewed GPL motorcycle tool and fuel-mapper project; no new stock ECU flash path added. |
| [ktm-can](https://github.com/blalor/ktm-can/tree/299b4e080168986ab535b81b81e2a9196f0c8c66) | No license found | KTM broadcast CAN decoder with Super Duke 1290 references and tests. No source copied; no model-independent CAN or ECU write claim. |
| [MOTO-HUB](https://github.com/vincenzobpt/MOTO-HUB/tree/33829314b91ce607146ed87b7405fd1a19b83f74) | AGPL-3.0 core | Motorcycle dash projection and controls. The README says the OBD feature is in a separate **closed-source** ADV-SOLO release, not the open core; no ECU diagnostic protocol imported. AGPL source reuse remains an option where useful with corresponding-source and notice obligations. |
| [Honda K-Line KWP2000](https://github.com/andreibaw/Honda_K-Line_KWP2000/tree/f3bd42ff438e840e4da3802dd5038a195f3d67be) | GPL-3.0 | Already integrated separately for source-tested 2005 CBR600RR live tables. Synthetic-only GuzziOnBoard tests and scope are documented in `EXTERNAL_MOTORCYCLE_RESEARCH.md`. |
| [SuSoDevs](https://github.com/Xmanu12/SuSoDevs/tree/8096bd122478859959264ea213d945857e6c4e88) | No license found | Previously reviewed electric motorcycle RS485/CAN subsystem dashboard, not a generic stock ECU read/write protocol. |
| [Tenere700](https://github.com/random1781/Tenere700/tree/9a221af139597b796870cf024ee7acad311e39ee) | GPL-2.0 | Mechanical modifications and mounts, not an ECU communications implementation. |
| [SV-650 GearPositionIndicator](https://github.com/RaysceneNS/SV-650-GearPositionIndicator/tree/0ac10e79eb009ecc00a5b35bf04504b19fa8b222) | No license found | Wired analog gear-position display for 2003–2009 SV650; 2004–2011 V-Strom 650 explicitly untested. It is not an ECU diagnostic interface. |
| [Dyno-ChiptuningFiles original ECU database](https://www.dyno-chiptuningfiles.com/original-ecu-files-database/) | Commercial website; data/file rights not granted here | Database lists vehicle, hardware, software, size and reader, but is not a protocol implementation. For example, its [2012 KTM Superduke 990 listing](https://www.dyno-chiptuningfiles.com/original-ecu-files-database/faulty-keihin-sh7055-452135/) describes Denso SH70xx, software KM611EU1102001, 499712 bytes, Dimsport Genius; its [2021 KTM Duke 390 listing](https://www.dyno-chiptuningfiles.com/original-ecu-files-database/bosch-bosch-mg1ca094-521744/) describes Bosch MG1CA094, software 069947, 1572864 bytes, Autotuner Bench. These are listing claims, not proof of the protocol, image region, checksum, tuning maps or GuzziOnBoard compatibility. No files were downloaded or bundled. |

## New Triumph profile and limitations

Select **Triumph → Bonneville 865 EFI → 2009**, physical K-Line and read-only
mode with a properly wired FTDI KKL-type interface. The profile reuses the
existing slow-init address `0x33`, accepts the `08 08` handshake, and expects
`48 6B D1` responses as seen on the TrECU author's tested bike. The internal
protocol name still refers to Daytona because that was its original application;
model/year binding is checked independently. Supported PIDs are filtered by the
ECU's reported bitmap. Sensor 0x14 voltage uses the first of two response bytes;
0x42 control-module voltage lazily discovers advertised 0x20 and 0x40 support
pages. These gauges are optional, not asserted to exist on every bike. A failed
or unadvertised page does not authorize polling the voltage PID.

TrECU's source-reported physical test does not test this integration. No
manufacturer-specific DTC dictionary was copied. The profile does not implement
TrECU's ECU identification, pending DTCs, DTC clear, KWP, memory reads, memory
writes or tuning. The source warns Triumph protocol and addressing can differ by
model, year and ECU supplier; no other fitment is claimed. No safety or
programming gates were relaxed.
