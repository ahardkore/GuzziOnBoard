# Twelve-repository code audit

Actual source files were inspected at the pinned commits below, not merely the
README or repository descriptions. Source-reported testing is distinguished
from testing this integration. No motorcycle, adapter or ECU was physically
tested with GuzziOnBoard. A missing feature below means it was not found in
the inspected code, not that the brand or source is unsuitable for tuning.

| Repository and pinned revision | Code and practical findings | License found |
|---|---|---|
| [ecu-forge-app `1099842`](https://github.com/MrAnnix/ecu-forge-app/tree/1099842e7088c4f1b242f8ede02d7bc8dcdcddfc) | Android identify/DTC and protocol plumbing; `feature-map/.../MapFeatureEntry.kt` navigates to a placeholder. No map or flash implementation found. | AGPL-3.0 |
| [obdium `fdaef0a`](https://github.com/provrb/obdium/tree/fdaef0a3bdc293b1621e1b2f96b482fba7e4ee69) | Rust ELM serial connection, OBD modes 01/22, VIN, telemetry and demo serial. No calibration/flash implementation found. Useful diagnostic transport reference. | GPL-3.0 |
| [EcmDroid `2f17d29`](https://github.com/ecmdroid/ecmdroid/tree/2f17d29f5b08f67fb357ee8f2ec21e7ae930343e) | `ECM.java`, `EEPROM.java`, `PDU.java`, `BurnTask.java`, definitions and test resources implement Buell version, runtime, full EEPROM GET, edits and SET burn. Page-zero writes are selective. Strong tuning lead. | GPL-3.0-or-later; database provenance separately described in Buell notes |
| [SquidGame `fe5b767`](https://github.com/WyzeGye/SquidGame/tree/fe5b767517c9974447dc5808d52e1ea5c23d673f) | `cm4head.py` includes per-cylinder fuel maps, adaptive learning and ESP32 actuator control for its own custom engine controller, not a stock ECU read/write protocol. Index/electrical timing require review before control reuse. | MIT |
| [ecmdroid-ios `8bdf530`](https://github.com/gkostolny/ecmdroid-ios/tree/8bdf53090f417be5c74b0761438a0f497f99cea0) | Swift EEPROM GET, editor, burn, definitions and simulator tests. Reads page zero one byte at a time; its `ECM.swift` burn skips page zero, unlike selective handling in original EcmDroid and XBTune. | GPL-3.0 |
| [XBTune `c592b11`](https://github.com/kz6fittycent/XBTune/tree/c592b11b17e1a3cd5f55f8bc726f2890d892d63b) | Rust `xbtune-core/src/{read,burn,tune}.rs`, `xbtune-proto/src/eeprom.rs`, definitions, simulator and tests: image reading, map editing, guarded SET, pre-read and readback. Reports physical BUEIB/2005 XB9SX and other ECM simulator tests. Used for scoped reads, offline maps, and a narrower normal-page map/axis SET writer; page-zero writes are not implemented. | GPL-3.0-or-later code; database GPL-3.0 with provenance caveat, see `BUELL_DDFI_RESEARCH.md` |
| [Honda-Motorcycle-Dash `57edf2c`](https://github.com/sophienyaa/Honda-Motorcycle-Dash/tree/57edf2cf1142aa9740a71d2cbb1986b5753ad53c) | `src/ecu.cpp` implements 10400-baud wake/init, table 11/D1 and checksum for live dashboard data. Useful Honda live diagnostics reference, not ECU map write. | GPL-3.0 |
| [OBDGate `eb47dc1`](https://github.com/fpoussin/OBDGate/tree/eb47dc14ff3885148c849c427cddcc480ea81245) | `board/board_revA.sch`, `.brd` and `.ioc` describe interface hardware. No application firmware/read/write code found. Electrical interface reference. | GPL-2.0 |
| [Motorcycle-Diag-Tool `9105500`](https://github.com/phccoder/Motorcycle-Diag-Tool/tree/9105500f52a021f28051bb9e7d6bf6493d20aa94) | `diagnostics.py` uses Python-OBD gauges and DTC queries plus simulated data. No tuning protocol found. | No root license found |
| [motorcycle-diagnostic `25bc046`](https://github.com/trevor3002/motorcycle-diagnostic/tree/25bc04688b9bc45a842cbf2936e8274e9fbdac96) | `index.html` JavaScript evaluates manually entered compression, spark, battery, fuel and symptoms. No ECU communication code found. | No root license found |
| [IndianErrorCodes-iOS `f4f6fbf`](https://github.com/mlburggr/IndianErrorCodes-iOS/tree/f4f6fbf683cf7225291c0516d42e66d55c659c02) | `ViewController.swift`, `SQLiteDatabase.swift`, bundled `ErrorCodes.db`: code lookup UI, not live ECU reader/writer. | No root license found; DB not copied |
| [Indian-Error-Codes `4a35a6a`](https://github.com/mlburggr/Indian-Error-Codes/tree/4a35a6aee008705415779d454d2ff64b2cc3323c) | Android code and database implement fault-code lookup; repository also tracks build artifacts. No ECU read/write implementation found. | No root license found; DB not copied |

## Work enabled here

The Buell desktop/browser serial tool can now read a complete source-described
EEPROM image for 19 explicit DDFI ECM IDs, without requiring an existing exact
read file. It exports raw XPR bytes with the ECM ID at the start of the name.
Source-derived XDFs now cover four fuel/spark maps and axes for all 19 IDs.
Research-copy export accepts catalogued research-only definitions, and a
separate experimental local writer sends reviewed normal-page map/axis changes
with a fresh pre-write backup, stopped-RPM check and chunk readback. Details,
licensing, usage and limitations: [BUELL_DDFI_RESEARCH.md](BUELL_DDFI_RESEARCH.md).
These integrations are synthetic-tested only, not 19 hardware-tested bikes.
They do not implement full EEPROM burning, stock Harley Delphi memory
reading/writing, full firmware reads, checksum repair or recovery.
