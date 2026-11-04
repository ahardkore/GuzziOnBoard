# ECU protocol sweep — 2026-11-04

Exhaustive GitHub repository sweep for ECU protocols **by family and by ECU
part number** (owner note: repos often name only the ECU — "IAW 5AM",
"Bosch ME17", "Delphi MT05" — not the motorcycle brand). Method: GitHub
repository search API (authenticated), ~50 queries across Marelli IAW
families (5AM/5SF/7SM/8GM/15M/15P/15RC/16M/18M/59M/11MP/P8/1.6M), Bosch
(ME7/ME9/ME17/MG1/MSE6/MSE8), Delphi (MT05/MT80/MT86), Continental, Keihin,
Shindengen, Denso (M32R), Mitsubishi, Siemens SIMK, Walbro, Athena, Motec,
plus protocol×brand queries (KWP2000/UDS/ISO 14230 × Yamaha/Suzuki/Kawasaki/
Ducati/Aprilia/KTM/Honda) and generic moto-diag/flash/bench queries.

Caveat: repo search only matches name/description/README text, so "total 0"
does not mean nothing exists — many protocol docs live in issues, forums or
inside code (code search needs different auth). Results below are the
recallable surface.

## New motorcycle-relevant findings (not previously catalogued)

| Repo | Pin | License | Class | Notes |
|---|---|---|---|---|
| denandz/5am_util | 73ba1795 (migrated to codeberg.org/DoI/5am_util) | BSD-3-Clause | [experimental] | IAW5AM firmware reader/writer via KWP2000/UDS over KKL; Ducati 848/1098/1198 et al.; self-described proof-of-concept |
| josapratama/SmartFI-Diag-Universal | 3d365022ab91 | MIT | [verified-class tool] | ESP32 universal SmartFI scanner, KWP2000 fast-init, Honda PGM-FI + Yamaha; 114 files |
| phduc775-png/Honda-Winner-150-2016 K-Line ECU Telemetry Protocol | a7f56c11b4ae | none (open per policy) | [experimental] | Vietnamese RE doc of Keihin K-Line fast-init + live-table decode on a Honda Winner 150 |
| MarioLange1983/FanticAnalyzer | (2026-11-02) | none (open) | [experimental] | BLE/UDS tool for Fantic e-shock module — UDS-over-BLE pattern |
| mattb97267-ai/iaw5am | 889529331ea6 | none (open) | **legal-use-only citation** | "ducati immo off bin" payload — cited with disclaimer, NOT vendored |

## Already known / corroborating
- Vasiy/onboard-logger (MIT, IAW 5AM live-capture PROTOCOL.md) — Round 23
- Vasiy/ecu-map-viewer, ajfemia/ECUDelphiMT05, WadieBenabdouh/MT05-Terminal,
  Gabboxl/Ducati_HYM939_MY17, NetworkDir/moto-ecu-checksum, slava-fm/moto-service-tool,
  aster94/Keyword-Protocol-2000, andrewwilke/daytona-kline, andreibaw/Honda_K-Line_KWP2000

## Car-ECU hits (noted, not adopted for motorcycle profiles)
- dspl1236/VAGFlasher (MIT, ME17/MED9/ME7/EDC17), megawillbot/hyundai-tuning,
  geeroam-crypto/siemens-simk43-decrypt (GPL-3.0), Dante383/GKFlasher (GPL-3.0, SIMK43/41),
  Vittaly/me17.9.71, TomFLV/5eat-tcu (Hitachi M32R), 100bas/Toyota-1KR-FE-ME7.9.52

## Gaps confirmed
Most motorcycle ECU families have **no** public repo-level protocol docs:
IAW 5SF/7SM/8GM/15M/15P/15RC/16M/18M/59M/11MP/P8 (beyond our own docs),
Bosch ME17/ME9 on bikes, Delphi MT80/MT86, Denso/SIMK on bikes. What exists
is dominated by: Honda Keihin K-Line (PGM-FI), Yamaha K-Line/CAN, Suzuki
SDS, Marelli IAW 5AM/59M (Guzzi/Ducati communities), Triumph K-Line, Buell
DDFI. Everything else lives in forums, XDF/BIN libraries, or commercial
tools — which is why the catalog stays research-grade for most families.
