# Capture search — 2026-11-03

Deep search for wire-level captures (K-Line session transcripts, CAN candump
logs, DBCs) that could unlock placeholder ECU families or add live-data
evidence. Searched 2026-11-03 via GitHub repository/code search and web
search; reachable surface is github.com / api.github.com / codeload.github.com
plus pypi/npm. Every source below is pinned to the commit inspected.

## Motorcycle-relevant captures found

| Source (pinned commit) | License | What it actually contains | What it can unlock |
| --- | --- | --- | --- |
| [DeziderMesko/motocan](https://github.com/DeziderMesko/motocan/tree/acdb1464e327363a7be52a53134f34d0ca2d4e62) `acdb146` | code MIT; `analysis/captures/` + `r9.dbc` **CC BY 4.0** | Yamaha R9 (2026) diagnostic-connector CAN, 500 kbps: 6 session folders with `capture.log.xz` (one 465k-frame candump log), `ref.csv` marks, per-session write-ups; 20 decoded signals on 23 IDs (rpm 0x27C, gear, TCS/PWR, wheel speeds 0x756/0x765, brake 0x383, temps 0x512, throttle 0x758…), each with dash/photo anchors; `analysis/r9.dbc`. Passive only — the capture adapter never transmits. | Offline CAN decoder + DBC for R9-class Yamahas. **No diagnostic request/response session** (nothing was ever sent to the ECU), so it does not unlock a physical diagnostic profile. This repo already references `r9.dbc` via `yamaha_r9_can.py`. |
| [JackHat1/MT07_CAN_Project](https://github.com/JackHat1/MT07_CAN_Project/tree/fec86c3da7a05b099e9259b1142980f339b3fa92) `fec86c3` | MIT (© 2024 Andreas Panagiotakis) | ESP32/MCP2515 decoder for a **Yamaha MT-07 (2014)** at 500 kbps: speed, RPM, temperatures, gear, with example output. No raw capture files, no diagnostic session. | Corroborates that 2014-era MT-07 broadcasts decodable 11-bit CAN. Same boundary: broadcast frames only, no tester dialogue. |
| [billyjack2/CAN-DBC-Collection](https://github.com/billyjack2/CAN-DBC-Collection/tree/6e2f88fd6cd9c1f47d0db7bd022711b106f27027) `6e2f88f`, path `DUCATI/Marelli_IAW59M_C/` | **no root license detected** — check per-file before bundling | `can1v2`/`can1v3` DBC+XML for a Ducati 998/999 IAW 59M **broadcast** CAN bus (the "enable CAN-bus on the 59M" mod: RPM, coolant, TPS…). 789 DBCs across 155 makes, mostly cars. | A signal layout for 59M CAN-broadcast decoding (offline). Not a K-Line diagnostic definition — the 59M placeholder's blocked status is unchanged. |
| [SchwarzeLanzenreiter/MotoRecoLogger](https://github.com/SchwarzeLanzenreiter/MotoRecoLogger/tree/30e08e034ac2f58ce6c3e5ba930bfa4b1108f4da) `30e08e0` | MIT | BMW Motorrad CAN logger/viewer **tooling** (Raspberry Pi canlogger + analyzer). No capture files in the repo. | Nothing new for BMW beyond the existing EasierCan R1300GS decoder. |
| [emanuelemerlo/marelli-iaw-ecu-studio](https://github.com/emanuelemerlo/marelli-iaw-ecu-studio) | see repo | Fiat/Lancia/Alfa **car** IAW tools with K-Line line traces ("every byte on the K-Line saved to a text file") and OBD-II over K-Line. | Car-scoped; the vendored IES2 snapshot already covers the automotive IAW-04K/16F implementation evidence. Not motorcycle 59M/15M. |

## Leads that are NOT usable as wire evidence

- **diagcode.com** (commercial) documents MIU G4 / 11MP CAN diagnostics and MIU G3 K-Line read/write for Piaggio-group bikes — feature-existence claims only; no IDs, frames or transcripts. Compatibility is not a protocol definition (same rule as PROTOCOL_NOTES.md).
- **ducati.ms forum thread "Ducati 998/999 IAW59M Canbus"** describes the 59M KWP services (`0x21` readDataByLocalIdentifier, `0x1A` ID) with an ID map (20–2F EEPROM, 30–7F RAM, 98/99 tester/date, A0–BF snapshots) — a genuine lead, but forum prose, not a pinned capture; also write-path claims. Recorded as a lead, not integrated.
- **Sirawit45/josave-tuner** (Honda flash, already reviewed), **reset-moto-reminders** Tiger 900 GT Pro 2021 (PolyForm Noncommercial — excluded), **gobftald/CCM450-diag** KMSK16 (already reviewed; contains write-path exploratory code — excluded), **NetworkDir/moto-ecu-checksum** (checksums only, already integrated offline).
- Car-focused tools found but not motorcycle captures: ddt4all, CanLab, cantools, uds-decoder, can-bus-lab, CANopener (J1939 machines), ECUPrint (car CAN skew dataset), BretStateham gist (generic OBD-II candump scripts — generic, no motorcycle).

## Negative result (the important one)

No public **motorcycle K-Line session transcript** (init + request/response
pairs with checksums) was found for the placeholder families: P8, 15M, 15RC,
59M, MIU G3/G4, 11MP, Mana TCU. No UDS/KWP-on-CAN diagnostic capture for
MIU G4/11MP or Triumph Tiger 900 either. Therefore **no placeholder family
changes status in this pass** — `physical_supported` stays false and no live
data is enabled for them. The signed protocol-update path remains the only
route from field confirmations to promoted read-level capabilities.

## Round 2 — deeper pass (forums, per-family leads)

License note per user direction: sources below are recorded for research /
off-road use only; no capture files are vendored into this repo, so no
license grant is needed for anything checked in — only citations.

| Source (pinned) | What it adds |
| --- | --- |
| ducati.ms thread 627217 "Ducati 998/999 IAW59M Canbus" (2016, confirmed again 2026-11-03) | 59M KWP2000 diagnostic layout: service `0x21` readDataByLocalIdentifier + `0x1A` readEcuIdentification; ID map **20–2F EEPROM (2 bytes each), 30–7F RAM (2 bytes), 98 tester code, 99 program date, A0–BF snapshots**; CAN-broadcast mod is separate from the diagnostic path. Forum prose — a lead, not a pinned capture. |
| ApriliaForum "Guzzidiag for RSV4" (t-282399, archived) | IAW7SMReader_V0.03 writes a full session `.log` per map download, but logs are shared by PM/email only — none on GitHub. Real 7SM identification strings seen: `IAW 7SM CM281702 IAW7SMHW320 7613HB12 7SM3EA DP2P0SK1T WLoad` (identity evidence only). |
| wildguzzi topic 116961 (2022) | IAWMIUG3Reader_V0.05 logs contain timestamped `FAST INIT` lines — MIU G3 reader exists and logs sessions, but again forum-local, no public file. |
| [digitwolf/w230](https://github.com/digitwolf/w230/tree/c4e11d7dc54bf76470512da18361faab00e72dcf) `c4e11d7` (LICENSE present) | **Kawasaki W230 (2024–26) KDS over ISO-14230 K-Line, read-only**: fast init (25 ms wake = one `0x00` at 360 baud), then `startCommunication` + `startDiagnosticSession`, polls RPM (register `0x09`, quarter-rpm) and speed (`0x0C`, km/h) ~3–4×/s. Concrete service/register evidence for Kawasaki KDS. No capture files committed. |
| [RyanHope/HondaECU](https://github.com/RyanHope/HondaECU) + 1000rr.net thread 247922 (2018) | **Honda CBR1000RR K-Line session hex**, forum-hosted: init at 10400 baud (`FE 04 FF FF`, `72 05 00 F0 99`, `02 04 00 FA`), info request `72 07 72 11 00 14 F0` → 26-byte reply decoding RPM/TPS/ECT/IAT/MAP/BATT/SPEED. A genuine tester-transmitted session trace for a Honda motorcycle; repo carries code, forum carries the bytes. |
| bimmerfest / pcmhacking.net BMW CAN threads | BMW **car** UDS on 0x7E0/0x7E8 with full ISO-TP examples — nothing motorcycle-specific; BMW Motorrad remains tooling-only (MotoRecoLogger) plus this repo's EasierCan R1300GS decoder. |

Round-2 verdict: public K-Line *session bytes* do exist for **Kawasaki
(W230)** and **Honda (CBR1000RR)** — both families already have read-only
catalog entries at honest confidence, so this corroborates them rather than
unlocking anything new. For the blocked placeholder families
(59M / 15M / 15RC / P8 / MIU G3 / MIU G4 / 11MP / Mana TCU) the only
session material is forum-PM'd reader logs and prose — no pinned public
transcript, so `physical_supported` stays false everywhere it is false today.

## Round 3 — full enumeration across makes

| Make / family | Public evidence found (pinned) | Kind | Unlocks |
| --- | --- | --- | --- |
| Yamaha R9/MT | motocan `acdb146` (CC BY 4.0 captures) + MT07_CAN_Project `fec86c3` (MIT) | raw candump broadcast captures + decoders | offline only; journal confirms listen-only ("a trip to listen-only lasts the key cycle") — no tester session exists |
| Kawasaki KDS | [digitwolf/w230](https://github.com/digitwolf/w230) `c4e11d7` (LICENSE); aster94/Keyword-Protocol-2000 (already integrated, 41 KDS models); HerrRiebmann/KDS2Bluetooth (KDS+SDS) | code with concrete frames: fast init, startCommunication, startDiagnosticSession, RPM reg `0x09`, speed reg `0x0C` | corroborates existing read-only Kawasaki entries |
| Suzuki SDS | gixxer.com threads 850165 / 830784 + Arduino forum 229761: SDS channel map (RPM `0x11`, TPS `0x0D`, MAP `0x0E`, ECT `0x0F`, gear `0x14`, fan `0x7A`), raw KWP response `8012F12218AE80F1…` (GSX-R600 K6), .pds save-file format | forum hex + format docs | corroborates existing read-only Suzuki entries (aster KWP2000) |
| Honda | RyanHope/HondaECU + 1000rr.net thread 247922: full K-Line hex session for CBR1000RR (init @10400, `72 05 00 F0 99`, `72 07 72 11 00 14 F0` → 26-byte reply) | code + forum hex | corroborates existing Honda read-only entries |
| BMW Motorrad | MotoRecoLogger `30e08e0` (MIT, tooling); GS-911 is commercial, no public logs; BeeEmUu/ediabasx are car-side | tooling only | nothing new; EasierCan decoder stands |
| Ducati 59M | ducati.ms 627217 (LDI map) + CAN-DBC-Collection `6e2f88f` 59M broadcast DBC; ducati.ms 155657: 1098 broadcast IDs (0x080, 0x020, 0x300, 0x10) | forum prose + broadcast DBC | lead only; 59M stays blocked |
| Ducati modern (Panigale etc.) | MelcoDiag debug logs (ducati.org 98114): OBD-II-style PIDs over CAN via ELM327 (024/080/022/180/018/020/190/680), ECU id `DMH_017511` | forum log snippets | OBD-II-over-CAN already covered by generic profile |
| Triumph | TuneECU (commercial app) works on Daytona 955i / Street Triple 765 / Tiger 900 over OBD (CAN on newer, K-Line on older); map .hex library public; 2021+ Tiger source is PolyForm-noncommercial (excluded) | maps + forum claims, no captures | nothing new |
| KTM | 990/690 = K-Line via TuneECU; 790/890 = Bosch ME17.9.21 CAN OBD; 1290 has no public tool; XDFs for ME17.9.21 public | maps/XDFs, no captures | nothing new |
| Zero | RIAEvangelist/zero-motorcycle-canbus (discovery code); electricmotorcycleforum t-6809 (candump methodology + PID list) | code + forum methodology | offline decode hints |
| Energica | [danieltroger/cool-eva](https://github.com/danieltroger/cool-eva) — BMS CAN 0x660–0x665 decoded (cells/temps/SOC), read-only OBD-II poller (modes 03/07/0A, KWP `0x22`), and **a committed real DTC-response transfer** replayed by `scripts/decode-dtc-response.ts`; full ride captures deliberately kept out (encrypted) | code + one committed diagnostic response | closest thing to a real diagnostic capture found, but single-bike, encrypted logs |
| MV Agusta | Eldor EM-2.0: TEXA/ECUStudio commercial only; old 16M free logger (.log files) — forum-only | forum | nothing new |
| Piaggio/Vespa, Mana TCU, MIU G3/G4, 11MP | IAWMIUG3Reader logs and IAW7SMReader logs exist but are PM/email-only; diagcode.com claims only | forum-PM logs, commercial claims | **no pinned public session — all stay blocked** |
| Generic tools (car-skewed, reusable) | SavvyCAN, CanLab, CANExplorer, can-utils, cantools, ddt4all, uds/udsoncan python libs | tools | methodology only |

### Enumeration verdict

Across ~40 searched sources: **exactly one repo with committed raw motorcycle
CAN captures** (motocan, passive broadcast only), **one repo with a committed
real diagnostic response** (cool-eva, Energica DTC reply), **three repos with
concrete K-Line service/register code** (w230, HondaECU, aster KWP2000 — the
last already integrated), and the rest are DBCs (broadcast), XDF/map libraries,
commercial tools, or forum-hosted hex. **No placeholder family gains a
promotable session transcript.**

## Round 4 — written-form documentation (prose/PDF, no wire bytes)

Yes — written documentation exists for several placeholder families, at a
different evidentiary level than captures: it describes *what* the ECU does
and *which services exist*, but not the motorcycle-specific key bytes, local
IDs, or scalings a physical profile needs.

| Written source (pinned URL) | Family | What it says in words |
| --- | --- | --- |
| [guzzitek.org — "MIU G3 injection V750 Training" PDF](https://www.guzzitek.org/documents/injection/ECU_MIU-G3_Training.pdf) | MIU G3 | Alpha-n strategy on throttle+rpm; self-adaptive air/fuel via two 10×10 cold/hot correction matrices; **adaptive fuel correction is readable by the diagnostic tool**; key-on reads manifold pressure as atmospheric reference; 48-tooth tone wheel (gap of 2 every 24); stepper motor fully open at key-on. Parameters in prose — no K-Line service bytes. |
| [griso.org — "GuzziDiag for V7–V9" PDF](https://www.griso.org/GuzziDiag%20for%20V7-V9.pdf) | MIU G3 (V7/V9) | Written usage manual: Reader backs up the map in ~15 min and writes a plain-text details file; per-model throttle reference values (V7I/V9 0.9–1.0, V7II 1.0–1.2, V7III 0.8–1.0); **no TPS reset on MIU G3**; selectable measurement list (throttle, RPM, air/engine temp). |
| "FIAT STANDARD DIAGNOSTIC PROTOCOL ON K-LINE KWP 2000" (06/07/2000, archived PDF) | all K-Line Marelli | The OEM written standard behind 59M/15M/5AM/7SM: full service list (readDataByLocalIdentifier, dynamicallyDefineLocalIdentifier, writeDataByLocalIdentifier, writeMemoryByAddress, readDTCByStatus, readStatusOfDTC, readFreezeFrameData, clearDiagnosticInformation, inputOutputControl, start/stopRoutine), 5-baud init sync `55h` + two key bytes + complement-of-keybyte2 / complement-of-address handshake. Protocol-level, not bike-specific. |
| [ASW-NEXT user manuals](https://www.immo-tools.lt/site/files/failai/ASW-NEXT/MIUG4_UM.pdf) (MIUG4) and IAW15P UM (scribd) | MIU G4 / 15P | Written internals: EEPROM = M95640; MCU flash range 0x20000–0x7FFFF; read/erase DTC, TPS reset, self-adaptive reset, virgin/immo states, recovery procedure via boot app. Memory-map level, no bus frames. |
| [diagcode.com product pages](https://www.diagcode.com/products/diagnostics-for-piaggio-group/) | MIU G4 / 11MP (HW002) / 7SM | Written per-controller service lists (identification, read/erase DTC, VIN, TPS reset, stored-data download, …), Euro5 = CAN. Commercial claims — existence of services in words, not wire definitions. |
| Aprilia Mana 850 GT ABS shop manual (scribd 75501969) | Mana TCU | Written wiring/diagnostics: transmission ECU pinout incl. **B2 = "Series K line for diagnosis"**, CAN between injection ECU / TCU / dash, U1601 "Mute Node" CAN error semantics. Confirms the TCU has a K-Line diagnostic pin — in prose. |
| UDS/KWP2000 written overviews (gsasindia UDS explainer; Grokipedia KWP2000; scribd protocol comparisons) | generic | UDS service table (0x10/0x11/0x14/0x19/0x22/0x27/0x2E/0x31/0x3E), `7F` NRC shape, ISO-TP single/multi-frame, KWP 8-bit checksum framing, 0x700–0x7FF diagnostic CAN IDs. Standards-level written form. |

### Written-form verdict

Written documentation **can ground offline understanding and safer read-only
defaults** (it tells us which services exist and which parameters the OEM says
are readable — e.g. MIU G3 adaptive fuel correction, Mana TCU K-Line pin),
but it **cannot substitute for a capture** when promoting a family to a
physical session: key bytes, target/source addresses, local identifiers and
scalings for these bikes appear only in captures or in tool binaries. So the
placeholders stay blocked; the written sources above are cited here as the
prose-level evidence layer.

## Catalog touch-ups from this search

- `yamaha_kline_research` notes/sources now cite motocan (R9 captures, CC BY
  4.0) and MT07_CAN_Project (MIT) as broadcast-CAN evidence for MT/R9-class
  Yamahas — offline decoding only.
- `bmw_can_research` sources now cite MotoRecoLogger (MIT tooling).
- Yamaha R9 (2026) noted under the Yamaha placeholder: captures exist but are
  passive broadcast only.

## What would unlock each blocked family

| Family | Capture needed |
| --- | --- |
| 59M / 15M / 15RC / P8 | A pinned K-Line session log: 5-baud or fast init bytes, a `C1` key-byte pair, then numbered `21 xx` / `1A xx` request→response pairs with checksums, on a named bike |
| MIU G3 | init transcript + IOLI/RELI request/response frames with widths |
| MIU G4 / 11MP | CAN ID pair + ISO-TP/UDS request→response frames (e.g. 10 03 → 50 03, 22 F1 90 → 62 …), pinned |
| Mana TCU | complete init + routine frames beyond the two captured `30 02 08` / `30 01 08` |
| Yamaha MT/R9 | a diagnostic (tester-transmitted) session, not just broadcast; K-Line init for pre-2017 MTs |
| BMW | UDS-over-CAN diagnostic ID pair + request/response frames |

## Round 5 — every documented source now has protocol code written (2026-11-03)

Each finding above is backed by a written module in the repo (passive
decoders / source-reported tables; none grants a physical session):

| Source | Written protocol |
| --- | --- |
| motocan R9 captures (`acdb146`) | `guzzionboard/yamaha_r9_can.py` (pre-existing, adapted from motocan) |
| MT07_CAN_Project (`fec86c3`, MIT) | **`guzzionboard/yamaha_mt07_can.py`** — IDs 0x236/0x216/0x23E/0x20A, gear/TPS/temps/RPM/speed candidates |
| CAN-DBC-Collection 59M `can1v3.dbc` (`6e2f88f`) | **`guzzionboard/marelli_iaw59m_can.py`** — 0x020 IAT, 0x100 neutral/speed/RPM/oil, 0x200 water/VBatt |
| cool-eva Energica BMS | **`guzzionboard/energica_bms_can.py`** — 0x200-0x205 + 0x660-0x665 extended frames |
| RyanHope/HondaECU + 1000rr.net 247922 | **`guzzionboard/honda_cbr1000rr_kline.py`** — handshake bytes + info-reply field decode |
| digitwolf/w230 (`c4e11d7`) | **`guzzionboard/kawasaki_w230.py`** — KDS registers 0x09 RPM (×0.25), 0x0C speed, fast-init constants |
| aster94/Keyword-Protocol-2000 (SDS/KDS) | `guzzionboard/protocol/aster_kline.py` (pre-existing) |
| ducati.ms 627217 (59M LDI map) | cited in `59m.json`; facts only, no live profile (no capture) |
| Mana shop manual (TCU K-Line pin B2) | cited in `mana_tcu.json`; physical stays blocked |
| guzzitek MIU G3 training PDF, griso.org manual | cited in `miug3.json` |
| ASW-NEXT MIUG4 UM, diagcode pages | cited in `miug4.json` / `11mp.json` |
| generic standard protocols (ISO 14230 / 14229 written docs) | `guzzionboard/protocol/generic_kwp.py`, `guzzionboard/protocol/uds.py` (generic read-only profiles) |

Tests: `tests/test_capture_search_decoders.py` (9 tests) plus
`tests/test_generic_kwp2000.py` / `tests/test_generic_uds.py` (32 tests).

## Round 6 — Zero decoder written; hunt re-run (2026-11-03)

**New offline decoder:** `guzzionboard/zero_can.py` — the full 31-ID Zero
broadcast table (controller 0x181/0x281/0x381/0x481/0x501/0x205, dash
0x1C0/0x2C0/0x3C0/0x440/0x540, BMS0 0x188–0x508, BMS1/PowerTank +1,
Calex charger 0x192/0x206/0x292/0x306/0x406) plus the library's own field
offsets (throttle u16le @b4 of 0x281, amps u16le @b3 of 0x408/0x409, cell
voltage u32le @b3 of 0x388/0x389, sag adjust u16le @b0 of 0x288/0x289),
from RIAEvangelist/zero-motorcycle-canbus (MIT, 2704ac4/2d9cac6).

**Hunt re-run, still negative for promotable captures:** GitHub code/web
searches for committed motorcycle UDS/KWP session logs (0x7E0/0x7E8 or K-Line
hex) return only car/CTF examples; IAW7SMReader and IAWMIUG3Reader logs exist
but are exchanged by PM/email only (one forum snippet shows the 7SM session
shape: `Serial: FJ0N8GA3W … E1 3E E1 3C … 25 58 A9 74 … Login Ok … Download
Ok` — forum prose, not a pinned file). New corroborating KDS frame-level
source: drowland341/pwc-scan-desktop (Kawasaki PWC KDS:
`81 11 F1 81 04` → `80 F1 11 03 C1 EA 8F BF`, then `… 10 80` → `… 50 80 54`),
consistent with the repo's existing KDS entries. Verdict unchanged: **no
public capture can promote a placeholder family today**; the per-family
unlock table above remains the checklist.

## Round 7 — "ECU Workbench" (allureluoli/ecu-workbench) checked (2026-11-03)

Lead: the free, MIT-licensed open-source **ECU Workbench**
(`github.com/allureluoli/ecu-workbench`, initial release fe60923, Oct 2026)
was audited for promotable wire captures. What it actually ships:
`data/local/ecu-mask.db` (SQLite: 878 versions / 7,834 modules / 755,091
DTCs), ~2,500 raw `.kp` + `.ECFG` attachments and parsed map JSONs
(SCZ 智能标定 install data — calibration map/definition payloads, mostly car
ECUs per its own DATA_POLICY referencing vcxcar.com diesel listings), and
`checksum_profiles.json`. **No K-Line hex transcripts, no CAN 0x7E0/0x7E8
(candump/UDS) session logs — zero wire-level captures.** KP/ECFG are tune
payload/metadata, exactly the "tune file" class that cannot by itself reveal
framing, checksum, or handshake. Its data also carries no clear
redistribution license, so per repo rules it stays citation-only and is not
vendored. Verdict: not a promotable-capture source; hunt continues to require
a real wire-level diagnostic session for a placeholder family.

## Round 8 — FIRST promotable-class capture found: Suzuki SDS (SV650) (2026-11-03)

**`github.com/synfinatic/sv650sds`** (archived 2026-08-25, master
`bacf803a9056241ef270acf0e7e31467961aeba5`) contains a genuine **wire-level
diagnostic session capture**: `data/sds_tool_output.txt` (~12 s of K-Line
traffic between a HealTech SDT clone and a 2003–2005 SV650 ECU
32920-17G2) plus `data/001-basic.csv` (OLS UART capture of the same
session). SDS is KWP-2000 / ISO 14230 at 10400 baud 8N1. Captured exchange:

    tx  81 12 F1 81 05                      init
    rx  80 F1 12 03 C1 EA 8F C0             key bytes C1 EA 8F
    tx  80 12 F1 02 1A 91 30                readDataByLocalId 0x91
    rx  80 F1 12 12 5A 91 "32920-17G2*" …   ECU model as ASCII
    tx  80 12 F1 02 21 08 AE                readDataByLocalId 0x08 (sensor block)
    rx  80 F1 12 34 61 08 <data> 4A          sensor snapshot

Frame rule: fmt byte high bits `10`; if low 6 bits are 0 (fmt 0x80) a
separate length byte follows the 3-byte header, otherwise the low 6 bits
are the data length (e.g. 0x81 = 1 data byte). Checksum = sum of all bytes
except the last, mod 256. Addresses are the 0x12 (ECU) / 0xF1 (tester) pair.
Source quirk: the sensor line is logged as "57:" with length byte 0x34 but
lists 58 bytes; the checksum still validates over all 58.

**New offline decoder:** `guzzionboard/suzuki_sds_kline.py` — frame parser
(fmt/length/checksum/direction), ECU-model reply decoder (ASCII after
`5A 9x`), sensor-block decoder with the source's own field table
(`sds_decode.ino`: rpm @25/26 = a*100+b, tps @27, ect @29, iat @30, iap @31,
batt @32, gear @34, … all marked unverified candidate formulas), and a
passive `decode_capture` summary. Tests in
`tests/test_capture_search_decoders.py` (11 passing). Pinned citations added
to `suzuki_sv650_2003.json`, `suzuki_sds_generic_research.json`,
`suzuki_sds_gsxr_research.json`.

**Verdict change:** this is the first public artifact that meets the
"promotable capture" definition (real K-Line diagnostic session for a
catalogued placeholder family). It supports read-only SDS decoding research
only — per standing rules it does NOT enable flashing/writing, and the
SV650 profile stays synthetic-tested with no memory/programming ops.

## License policy note (applies to Rounds 9–14)

License policy: a source is treated as open for use and modification whether or not a license is stated; if an author later advises that a source is not open, the affected material can be modified or removed at that point. Write-oriented (flash-class) algorithms may be used when the upstream author indicates success (byte-identical output vs. a commercial tool, or flashed-and-running) — see Round 16.

## Round 9 — AutotronicCommunity account swept in depth (155 repos) (2026-11-03)

Full sweep of `github.com/AutotronicCommunity?tab=repositories` (100 + 55
repos; ~45 own repos, the rest forks of generic upstream tools). The own
repos are an Indonesian Honda/Yamaha PGM-FI tuning community.

**Promotable-class captures found (read-only protocol evidence):**
- `Honda_Keihin_KLine_Protocol` — README documents the Keihin K-Line
  procedure (Tx low 70 ms / high 120 ms, 10400 8N1, wake `FE 04 72 8C` →
  `0E 04 72 7C`, init `72 05 00 F0 99` → `02 04 00 FA`, request shape
  `72 NN QQ ZZ CS` with CS = two's complement of the byte sum) **plus a
  real captured K25 request/response transcript**
  (`REQUEST - RESPONSE ECU HONDA K25 901.txt`): ECM ID `71 00`, live table
  `71 17`, current DTCs `74 xx`, past DTCs `73 xx`. Same 0x72/0x71 family
  as RyanHope/HondaECU — second independent public wire capture for the
  Honda placeholder family.
- `ScantoolHonda/ScantoolHonda.ino` and `scantoolHondaEsp32/ESP32_SCANTOOL.ino`
  — table-17 field offsets: RPM = b9*256+b10, TPS1 mV = b11*19.6,
  TPS2 % = b12*1.57, ECT1 mV = b13*19.6, ECT2 C = b14-40, IAT b15-16,
  MAP b17-18, BAT = b19/10, INJ = (b20*256+b21)*3.92, IGT = -64+b22*0.5,
  SPEED = b24.
- `READ-ECM-CODE-DAN-ECM-PART-DENGAN-ESP32` — ECM part decode from `71 00`
  reply bytes [9:14] (e.g. `0102E30F01` → 30400-K81H-N52).
- `DATABASE_KONEKSI_YAMAHA` (HTML) — per-model connection table
  (K-Line vs CANBUS) by Yamaha part code (2PV0 MX King = K-Line, etc.).
- `dtc_honda` / `dtc-yamaha` — manufacturer DTC ↔ OBD2 P-code dictionaries.
- `pinoutECMYamaha` / `pinouECMHonda` / `APP_PINOUT_ECM_HONDA` /
  `PinsipKerjaMapping` / `AnalisaIgnition` — connector pinout references.
- `PGMFI_HONDA_BIKE` (PDF) and `Protokol-*` (PNG protocol-table screenshots).
- `YAMAHA-AEROX-XDF--BIN` — XDF+BIN tune payload (payload class, not wire
  protocol; not vendored).

**Not adopted (standing safety rules):** `YamahaFlasher`,
`YAMAHA-FLASH-TOOL-V6-DEMO`, `YAHAMA-FLASH-VIA-KLINE---BACKDOOR`,
`ShindengenFlasher`, `SoftwareHondaFlasher`, `SIMPLE-REMAP-*`,
`SoftwareHondaECU` (MCU commercial flash installers), `CopyPaste24C02`
(EEPROM write), `hex2id_keihin_keyless` / `ID_TAG_PROGRAM_DEMO` (keyless
ID), `ODOMETER-FILE-GENERATOR`, `APP-EDIT-FLASH-COUNT`,
`License-Tuner-Pro-RT` / `licenseRFPv3` (license cracks),
`ARDUINO_READ_ECU_MX_KING_V1` (read via an unlock-ID sequence — not a
read-only path). None of these grant or inspire any write/flash/unlock
capability here.

**New offline decoder:** `guzzionboard/honda_keihin_kline.py` — checksum
rule, request builder, table-17 live-data decoder (ScantoolHonda offsets,
candidate-flagged), ECM-ID part decode, passive `decode_capture`; the
verbatim K25 transcript frames are embedded as test constants. Tests:
12 passing in `tests/test_capture_search_decoders.py`. Citations pinned
into `honda_pgmfi_research.json`, `honda_pgmfi_flash_research.json`,
`honda_cbr1000rr_2012_us.json`.

**Verdict:** Honda PGM-FI/Keihin now has two independent public wire
captures (RyanHope thread + AutotronicCommunity K25 transcript) — still
read-only research; placeholder profiles stay non-physical until the
repo's own verification gates pass.

## Round 10 — AutotronicCommunity deep-content pass: usable read-only tools extracted (2026-11-03)

Beyond the K25 capture (Round 9), the account's own repos yielded
**read-only tooling/data we can actually use**, even though none of it
unlocks a physical profile:

- **`dtc_honda` + `dtc-yamaha`** (HTML tables): 32 Honda PGM-FI and 21
  Yamaha MIL/dIAG codes with OBD2 P-code cross-references → transcribed
  into **`guzzionboard/catalog/dtc_manufacturer.json`** (53 codes, cited),
  merged into every ECU profile's `dtc_descriptions` by
  `catalog.load_catalog()` exactly like `dtc_sae.json` (optional-file
  load so merged-catalog tests are unaffected).
- **`Protokol-Live-Data-PGM-FI-Honda-Bike` poster (PNG)**: checksum rule
  `CS = 0x100 - (SUM(DATA) & FFh)`, wake Tx low 70 ms / high 120 ms @
  10400, StartComm `FE 04 72 8C`→`0E 04 72 7C`, keep-alive `72 05 00 F0 99`
  →`02 04 00 FA`, and **per-table parameter formulas** for tables
  10/60, 11/61, 13/63, 17/67, 20/70, 21/71, D1 (rpm D9*256+D10, TPS
  D11*5/256 V & D12*0.5 %, ECT D14-40 °C, BAT D19/D21*0.1 V, INJ
  (D20*256+D21)/200 ms, IGT -64+D22*0.5, SPEED D24/D25/D26, O2/STFT, ...)
  → added as `TABLES` + generic `decode_table()` in
  `guzzionboard/honda_keihin_kline.py` (all candidate-grade).
- **`Protokol-Diagnostik-PGMFI-Honda-Bike` poster (PNG)**: DTC queries
  73 (memory) / 74 (current) with 3-byte DTC layout and DTC code table,
  plus PC817 optocoupler K-Line interface schematics (+5 V and +3.3 V
  variants). Its **clear-DTC query 0x60 is a write operation — recorded as
  `CLEAR_DTC_QUERY` and deliberately not implemented.**
- **`DATABASE_KONEKSI_YAMAHA`**: 101-row table mapping Yamaha part codes
  to models/years and **connection type** — K-Line for most 2015–2024
  scooters/sport bikes (2PV0 MX King, B5V0 Sniper V3, 1WD/2WD R25, 2MS R3,
  B74 XMAX 300, 2PW TMAX 530, 3D7 WR250X …), CANBUS for FAZZIO/Grande
  Filano (BRV0/BEJ0/BKF0/BJK0), R15M V4 (BDJ0), newer XMAX (BPV0/B5X0),
  XSR155 V1 (BBS1), MT15 (B8D1). Cited on all suzuki/yamaha/kawasaki
  research profiles; full row list at the source URL.
- **`pinoutECMYamaha` / `pinouECMHonda` / `APP_PINOUT_ECM_HONDA` /
  `PinsipKerjaMapping` / `AnalisaIgnition`**: connector pinout and mapping
  reference pages (cited).
- **`PGMFI_HONDA_BIKE`** (1.5 MB PDF): PGM-FI protocol document (cited).
- **`AT-COMMAND-ELM327`**: generic ELM327 AT command reference (cited).
- Not usable: `racebox2`/`DYNO*` (dyno timers), `ECU_DUINO` (DIY ECU,
  self-marked untested), `SIMULATOR-*.exe` (Windows binaries),
  `TACHOMETER---RPM-METER` (exe), `YAMAHA-AEROX-XDF--BIN` (tune payload),
  and all flash/keyless/license repos listed in Round 9.

Tests: 13 decoder tests + 24 catalog tests green. Full-suite and demo-data
re-sync run after this entry.

## Round 11 — new decoders surfaced in the web UI (2026-11-03)

The two new offline decoders are now usable in the browser's **Multi-brand
offline capture research** panel (`web/multibrand-offline.js` +
`web/index.html`), as independent JS reimplementations of the pinned
sources (sv650sds GPL-3.0 capture; AutotronicCommunity protocol docs, no
license detected — facts cited, code reimplemented):

- `suzuki_sv650_sds` — SDS K-Line frames: fmt/length/checksum validation,
  init/model/sensor-block decode with the source field table (candidates).
- `honda_keihin_k25` — Keihin K-Line: `72` requests and `02` responses with
  two's-complement checksum, table 17/67 live data per the poster formulas,
  ECM-ID part bytes, 73/74 DTC replies; **query 0x60 (clear DTC) is rejected
  as a write operation**.

Covered by `tests/browser/desktop-host.spec.mjs` ("desktop exposes
multi-brand offline research…", passing) using verbatim captured frames.
Sources documented in `docs/EXTERNAL_MOTORCYCLE_RESEARCH.md`.

## Round 12 — Buell XB12X DDFI-2 serial protocol (pacdavid1/buell-xb12x-logger, MIT) (2026-11-03)

Audited `github.com/pacdavid1/buell-xb12x-logger` @ `45a762442fb3018500f9dcc789725d4383de4332` (192 files,
MIT). The repo is a Raspberry-Pi logger for the Buell XB12X IDS DDFI-2 ECU
with a complete, byte-trace-confirmed protocol reference
(`docs/10_DDFI2_PROTOCOL.md`): PDU `01 00/42 .. LEN FF 02 payload 03 XOR-CS`,
9600 8N1; GET 0x52 / VERSION 0x56 / RT_DATA 0x43 / ACK 0x06; BUEIB EEPROM
6 pages / 1206 bytes with map regions (timing 670-869, fuel 870-1205); XPR =
EEPROM + 4-byte footer; full RT field table in `ecu_defs/rtdata.xml`.

**Used (read-only):** new offline decoder `guzzionboard/buell_ddfi2_serial.py`
— PDU validation (envelope, 0x00/0x42 pair, length, XOR checksum), GET
response (EEPROM bytes), RT_DATA response decoded through the 74-entry
DDFI-2 `RT_VARS` table (LE u16, scale+translate, candidate-grade), passive
`decode_capture` summary; plus a `buell_xb12x_ddfi2` option in the web
multi-brand offline panel. 14/14 decoder tests pass.

**NOT used:** CMD_SET 0x57 EEPROM write (the source confirms writes on a
real ECU — deliberately not implemented anywhere here), burn workflow,
ECM def XML tuning surfaces. MIT notice preserved in
`LICENSES/Buell-XB12X-Logger-MIT.txt`; documented in
`docs/EXTERNAL_MOTORCYCLE_RESEARCH.md`.

## Round 13 — AiM YAMAHA/CAN_2015 DBC + R9 Euro5 corroboration (2026-11-03)

**New offline decoder:** `guzzionboard/yamaha_can2015_aim.py` — the AiM
`YAMAHA / CAN_2015` logger protocol (R1/R1M 2015+, R6 2017+) from
`billyjack2/CAN-DBC-Collection` `YAMAHA/CAN_2015/can1v3.dbc` @
`6e2f88fd6cd9c1f47d0db7bd022711b106f27027`. The collection has no root
license, which per the standing policy is treated as open (modifiable/removable
later if advised otherwise); the facts are reimplemented and cited.
DBC messages, all little-endian: 0x205 wheel speeds F/R (bits 8|16,
24|16, ×0.01 km/h); 0x209 RPM (8|16 ×0.4), TCS 25|4, gear 29|3 (0=N..6),
gear-raw 32|3, power mode 38|2; 0x215 throttle valve 8|10 ×0.15° and grip
24|10 ×0.145%, LIFT/LAUNCH/SCS/QSS settings, byte-7 intervention flags
(ABS F/R, launch, lift, SCS, TCS); 0x226 map select 53|3; 0x23E coolant
byte0 / air byte1 (raw×0.66−36 °C); 0x250 accel X/Y (8|16, 24|16,
raw×0.001−7 g); 0x254 gyro 40|16 (300−raw×0.01 °/s, axis unspecified);
0x260 four brake pressures ×0.1 bar — **DBC declares a 9-byte frame, which
classic CAN cannot carry; the decoder accepts 8 or 9 bytes and marks the
last field None when truncated** (the caveat is in the module). 15/15
decoder tests pass.

**Corroborating sources recorded:** r1-forum "CAN Bus Protocol" thread
(SySt's 2015+ R1/R1M work: 500 kbps, ~16 IDs, 0x260 brake pressures,
0x264 wheel speeds, lean angle in 5° steps @ ~100 Hz; forum-only, cited not
vendored — note it puts wheel speeds on 0x264 vs AiM's 0x205, possibly ABS
vs ECU rebroadcast, kept separate) and DeziderMesko/motocan (2026 R9 Euro5
connector: 0x27C/0x383/0x512/0x751/0x756/0x758/0x759/0x765/0x76D/0x76E with
candump captures + r9.dbc — extends the existing `yamaha_r9_can.py`, which
already covers 0x27C/0x512). All broadcast-only; none unlocks a physical
diagnostic profile.

## Round 14 — aollin/racechrono-ble-diy-device deep audit (2026-11-03)

Audited `github.com/aollin/racechrono-ble-diy-device` @
`2b6bd28c6e0ad95c559d23033fd45df8cc8d4808` (15 files, all read: README,
both example sketches, PacketIdInfo). **Verdict: no motorcycle protocol
content — nothing to decode or promote.** The repo is the RaceChrono BLE
DIY *transport API* plus reference firmware (Adafruit nRF52 Bluefruit +
MCP2515 @ 500 kbps + optional GPS): it forwards **raw** CAN frames over
BLE (service 0x1FF8; CAN main char 0x0001 = 4-byte little-endian packet ID
+ up to 16 payload bytes; filter char 0x0002 = DENY_ALL 0 / ALLOW_ALL 1 /
ADD_PID 2 commands; GPS chars 0x0003/0x0004 with the documented 15-bit
altitude/speed wrap encodings). `PacketIdInfo.cpp` is only a
filter/notify-interval hashmap. The example README explicitly says the
user must reverse-engineer each vehicle's packets themselves; the only
bike mentioned is a KTM used for testing (Sumitomo connector photo), with
**no KTM IDs documented** and no captures committed.

License: none detected — treated as open per the standing
policy (modifiable/removable later if the author advises otherwise); the
transport facts above are cited only. Recorded here so the
audit isn't repeated; no decoder, catalog or UI change results.

## Round 15 — terrafirma2021/Yamaha-DataLogger deep audit (2026-11-03)

Audited `github.com/terrafirma2021/Yamaha-DataLogger` @ `d06a80aef95bf97d6e15eef1c1d851fde6cc4975` (38 files,
all read: README, main.cpp, all include/ headers, YDS_Emulator.ino, Torque
CSV, RealDash XML). No license stated — treated as open per the standing
license policy (modifiable/removable later if the author advises otherwise).

**What it is:** an ESP32-S3 bridge that reads the Yamaha **YDS K-Line
broadcast** at **16040 baud 8N1** and re-emits it as ELM327/OBD-II mode-01
for Torque/RaceChrono/RealDash. **Broadcast only — not the SDS diagnostic
session, unlocks no physical profile.**

**Protocol facts extracted:** startup/IMMO burst = `0x3E` + ~60 bytes,
ending `0xCD` (diag menu) or `0xFE` (normal); normal frames are 5 bytes
`[rpm_raw, speed_raw, error_raw, coolant_raw, csum]` with
`csum = sum(data) & 0xFF`; conversions rpm = raw*50 (max 12500), speed =
raw km/h, coolant = raw-30 °C, error = raw code. ELM327 PID map: 010C RPM
int16, 010D speed, 0105 coolant, 01A4 gear, custom 1001-1006 (error/MCU
stats). (Note: the source's speed path sums an 8-frame ring buffer — an
implementation quirk, recorded not adopted.)

**Built:** `guzzionboard/yamaha_yds_kline.py` — frame parser + startup
classifier + passive `decode_capture` + `ELM_PID_MAP` reference. 16/16
decoder tests pass. Citation pinned in `yamaha_kline_research.json`.

## Round 16 — NetworkDir/moto-ecu-checksum deep audit (2026-11-03)

Audited `github.com/NetworkDir/moto-ecu-checksum` @ `43ccc5f3663e2a175b7217f802bc302830e6862b` (17 files, all
read: README, 8 algorithm modules, 3 Python scripts, app.js). No license
stated — treated as open per the standing license policy (modifiable/
removable later if the author advises otherwise).

**What it is:** a verify-**and-repair** checksum tool for motorcycle ECU
images (Bosch MSE6.0/MSE8.0/MG1, Yamaha MT, Honda Keihin, Dell'Orto, QH250,
Italjet/Suzuki-type). Per the standing policy, write-oriented algorithms are usable **because the author indicates success** (byte-identical MD5 vs. commercial flash tools / flashed-and-running on every listed model), so both the *verification* and the *repair* algorithms were extracted — repair is opt-in and labelled; this app still performs no ECU writes itself:

- **Yamaha MT**: whole-image BE16 word sum == 0x5AA5 (1 MB) / 0xE81F
  (896 KB); checksum word at end-8 after the 8-char software ID, followed by 64 02
- **Honda Keihin**: byte at end-8 makes byte sum 0 mod 256 (X-ADV 750: whole
  512 KB image; ADV350: 0x10000..end of 768 KB)
- **Bosch MSE6.0**: structurally-found 16-byte BE records [start][end][cs][~cs]
  (cs^~cs == 0xFFFFFFFF); cs = BE16 word sum of region; self-invariant
  ([cs][~cs] always contributes 0x1FFFE)
- **Bosch MSE8.0**: 256 KB cal block via footer signature; CRC-32 ^ 0xA18AFC77
  stored BE at block+0x3FFF8
- **Bosch MG1**: DEADBEEF blocks on 256 KB boundaries; CRC-32 (init
  0xACC08E37) == zlib.crc32(block, 0x533F71C8) after the 0x15C-byte 12345678 fill
- **Dell'Orto**: BE16 one's complement of byte sum 0x80000..0x921FD at 0x921FE
- **QH250**: BE16 words 0x0000..0x7FEF sum to 0, checksum at 0x7FEE
- **Italjet/Suzuki-type**: LE16 checksum + complement after the AA55CC33
  marker before the part number; byte sum of 0x20000..end
- Out of scope upstream too: signed/keyed images (Royal Enfield Hunter 350)

**Built:** `guzzionboard/ecu_image_checksums.py` — 8 verifiers + `verify_image` dispatcher + opt-in, author-confirmed `repair_*` functions (local file images only; the app never writes to an ECU). 17/17 decoder tests pass.

## Round 17 — refused write-class repos re-audited for the author-success rule (2026-11-04)

Re-audited every repo refused under the old write rule (Round 9/10 list plus
earlier rounds) via the GitHub API: existence, license, README success
claims (works/tested/verified/berhasil/compatible), description.

**Result: none of them meet the "author indicates success" bar.**
- All 15 named AutotronicCommunity repos exist but are license-NONE with
  empty or one-line demo READMEs and **no verifiable success evidence**
  (`YAMAHA-FLASH-TOOL-V6-DEMO` exists only as `...-DEMO-VERSION`, README is
  just "DEMO VERSION: MX KING V1 2PV0 ... ONLY"; `YamahaFlasher`,
  `SIMPLE-REMAP-*` etc. have no README at all).
- `SIMPLE-REMAP-K1ZG_N21_IN01_PCX-160`, `SIMPLE-REMAP-MX-KING-2PV0`,
  `SoftwareHondaECU`, `CopyPaste24C02`, `hex2id_keihin_keyless`,
  `ID_TAG_PROGRAM_DEMO`, `ODOMETER-FILE-GENERATOR`, `APP-EDIT-FLASH-COUNT`,
  `License-Tuner-Pro-RT`, `licenseRFPv3`, `YAHAMA-FLASH-VIA-KLINE---BACKDOOR`,
  `ShindengenFlasher`, `SoftwareHondaFlasher`, `ARDUINO_READ_ECU_MX_KING_V1`
  — same: no author success indication.
- `Sirawit45/josave-tuner` and `gobftald/CCM450-diag` are the only ones with
  success-sounding commercial descriptions, but they are **commercial
  write tooling**, not algorithms with verifiable byte-level evidence —
  recorded as [experimental] citation-only references, no capability added.
- `tientuk3/m32r-bootloader-protocol` (Denso M32R flash read/write via
  factory bootloader) — no success evidence in README; bootloader write
  path stays excluded.

**Verdict:** 0 of the ~18 refused sources qualify under the author-success
rule, so **nothing was added, even behind an experimental flag** — the only
author-confirmed write-class source remains `NetworkDir/moto-ecu-checksum`
(Round 16). Odometer / flash-count / keyless / license-crack repos remain
excluded outright regardless of flags (tampering/cracking, not
write-oriented *algorithms*). The experimental flag mechanism is noted here
for any future source that does publish verifiable success evidence.

## Round 18 — GitHub deep dive under the updated rules (2026-11-04)

Rules applied: no-license = treated as open; documented success = verified;
legitimate-looking but unproven = [experimental] citation-only; write-class
only with author-indicated success. Searched repo API across
motorcycle-ECU / immobilizer / seed-key / bench / tuning angles (~20
queries).

**Verified (documented success, license stated or open-by-policy):**
- `kz6fittycent/XBTune` @ `f474b9401bc4` (GPL-3.0) — Buell DDFI-2/DDFI-3
  diagnostics, logging **and offline tuning with ECM write-back**;
  README: "Tested on a 2005 XB9SX". Complements our read-only DDFI-2 decoder
  (Round 12); its tune-write path is author-confirmed → [verified] reference.
  LICENSES/XBTune-GPL3.txt added.
- `lab-vex/OBDuke` @ `cf51c6325fd5` (no license → open) — Gen1 KTM 390 Duke
  (2013-16) CAN diagnostic tool + app, shipped releases; complements
  ktmrc3902022/KTM-OBD. [verified]
- `singular0/trecu` @ `2969212aa462` (GPL-3.0) — Triumph K-Line
  ISO 9141-2 (5-baud 0x33 init) OBD-II: VIN/cal-ID, stored+pending DTCs
  with a 415-code dictionary, live-data stream; "confirmed on a real
  Triumph". [verified] — strengthens the Triumph Daytona panel entry.
- `lefaton/DDA_to_XML` @ `e90dc42f77cd` (NOASSERTION) — Ducati DDA binary
  telemetry file format → XML, "Tested on a 2014 Streetfighter 848".
  Read-only file parser. [verified]
- `sunsided/suzuki-sds-obdii-gateway` @ `20644c2e21ca` (no license → open)
  — SDS/KWP2000 codec (Rust, host-tested) bridged to OBD-II/CAN for a 2017
  DL650; independent corroboration of the sv650sds SDS work. [verified]
- `oJudgeStore/SmartGauge_for_Honda` @ `2ce31f06ec53` (NOASSERTION) — ESP32
  Honda PGM-FI live-data + DTC read/clear gauge; corroborates the K25
  decoder. [verified]

**[experimental] (legitimate-looking protocol, no documented success):**
- `TanakonKetsakron/Motorcycle-ECU-Diagnostic-Monitoring-System` @
  `dfad01639f2e` (no license → open) — Honda/Yamaha K-Line live data + DTCs.
- `ludwig-v/psa-seedkey-algorithm` @ `5aef5117ac38` (GPL-3.0) — published
  method for extracting UDS 0x27 seed/key algorithms from ECU flash dumps
  (PSA cars). Documents the *class* of ECU-unlock research; no motorcycle
  target; [experimental] reference only — no seed/key or immobilizer-defeat
  capability is implemented here.
- `poozam/HondaKLineFlasherV1` @ `3ec24c436234` (MIT) — Honda K-Line
  flasher, but **no documented success** → write-class without
  author-indicated success: [experimental] citation only, not adopted.
- `tepzraisya028-gif/TepzRaisya-Scanner` @ `bfe2fbf6571e` (no license) —
  2-file stub, no protocol content → skipped.

**Excluded outright:** `AshanDilakshana/NS200-ESP32-Keyless-Immobilizer-Strobe`
— keyless/immobilizer-defeat hardware; not a write-class *algorithm* and not
added even experimentally.

## Round 21 — experimental citations added for previously refused repos (2026-11-04)

Owner clarification: experimental entries ARE allowed, provided they carry an
`[experimental]` tag. The legitimate-looking but unproven write/unlock repos
from the Round 17 refusal list are now added to
`EXTERNAL_MOTORCYCLE_RESEARCH.md` as [experimental] citations: YamahaFlasher,
YAMAHA-FLASH-TOOL-V6-DEMO-VERSION, YAHAMA-FLASH-VIA-KLINE---BACKDOOR,
ShindengenFlasher, SoftwareHondaFlasher, SIMPLE-REMAP (PCX-160, MX King 2PV0),
SoftwareHondaECU, CopyPaste24C02, ARDUINO_READ_ECU_MX_KING_V1,
poozam/HondaKLineFlasherV1 (MIT), tientuk3/m32r-bootloader-protocol, plus
keyless/immobilizer entries (hex2id_keihin_keyless, ID_TAG_PROGRAM_DEMO,
NS200-ESP32-Keyless-Immobilizer-Strobe) with a **legal-use-only disclaimer**
(research / off-road / track vehicles you own or are authorized to race).
All are citation-only — no capability implemented, no payload vendored.
Odometer / flash-count / license-crack repos remain excluded outright.

## Round 20 — scope policy update: research/off-road/track orientation (2026-11-04)

Owner direction: the app is for research and off-road/track use. **Flashing
and unlock routines (UDS 0x27 seed/key for legitimate tuning of owned or
authorized race vehicles) are in scope when legitimate**, ideally with
author-indicated success. **Immobilizer-related material may be cited with an
explicit legal-use-only disclaimer** (track/race immo-off conversions); no
immobilizer-defeat payload is vendored or implemented. **Odometer rollback,
flash-count editing and license cracks remain excluded outright** — fraud
and cracking, not tuning. The Round 17 re-audit result stands: 0 of the
previously refused repos had verifiable success evidence, so nothing new was
added under the wider scope; the Buell DDFI-2 tune-write path (Round 19)
remains the only implemented write capability (local images, token-gated).

## Round 19 — self-audit, experimental Buell DDFI-2 tune-write path, docs cleanup (2026-11-04)

**Repo self-audit:** 921 files / 49 MB; docs 4.8 MB across 49 files. Removed the
four successive source-review docs superseded by `EXTERNAL_MOTORCYCLE_RESEARCH.md`
(`ADDITIONAL_MOTORCYCLE_SOURCES.md`, `TWENTY_SOURCE_REVIEW.md`,
`USER_SOURCE_REVIEW.md`, `TWELVE_REPOSITORY_CODE_AUDIT.md`); references repointed.
Research binaries in docs/ are intentional — `test_static_site_assets.py`
asserts they stay off the CDN.

**Tune capability under the updated write-class rule (author-indicated
success):** `pacdavid1/buell-xb12x-logger` @ 45a7624 (MIT) documents
`CMD_SET 0x57` payload `[0x57, offset, page] + data` as "confirmed 2026-05-31:
write EEPROM page", and `kz6fittycent/XBTune` @ f474b9401bc4 (GPL-3.0) writes
tunes to DDFI-2/3 ECMs, "Tested on a 2005 XB9SX". New module
`guzzionboard/buell_ddfi2_tune.py` (EXPERIMENTAL): builds CMD_SET PDUs with
the correct XOR checksum and patches **local EEPROM images only** — every
function requires an explicit confirmation token, no transport is opened,
and the passive decoder still reports such frames as
`0x57-SET-WRITE-REJECTED`. 19/19 decoder tests pass. No other brand has an
author-confirmed write path, so no other tune capability was added.

## Round 22 — experimental write builders for all decoded protocols (2026-11-04)

Per owner direction ("build it as experimental where absent"), added
`guzzionboard/experimental_writers.py`: token-gated, offline frame builders
that return BYTES only — no transport is ever opened. Coverage:

- **KWP2000/ISO 14230:** 0x3B WriteDataByIdentifier, 0x3D WriteMemoryByAddress
- **UDS/ISO 14229:** 0x27 requestSeed/sendKey (unlock/tuning research),
  0x31 RoutineControl, 0x34 RequestDownload
- **Honda Keihin K-Line (K25):** clear-DTC request `72 02 60 00 CS`
- **Buell DDFI-2:** CMD_SET 0x57 EEPROM write (Round 19 module,
  author-confirmed via MIT logger + GPL XBTune)

Every function raises without the explicit confirmation token
(legal-use-only wording: local research / off-road / track vehicles owned or
authorized). Passive decoders still classify these frames as write-class
(Buell 0x57-SET-WRITE-REJECTED; Honda 0x60 counted as request, never data).
20/20 decoder tests pass.

## Round 23 — search by ECU part number instead of brand (2026-11-04)

Owner note: GitHub repos often name only the ECU ("Bosch ME17", "IAW 5AM",
"Delphi MT05"), not the motorcycle brand. Re-ran the deep dive by ECU part
numbers from the catalog (IAW 5AM/15P/7SM, ME17/ME7/MG1, Delphi MT05,
Shindengen, SIMK43, Denso, ...). Motorcycle-relevant hits:

- **Vasiy/onboard-logger** @ `7caf4e59ae2e` (MIT) — K-Line logger for a
  motorcycle **IAW 5AM HW610** (Moto Guzzi); `docs/PROTOCOL.md` is verified
  against a live capture: KWP2000/ISO 14230, 10400 8N1, addressed (TGT 0x10 /
  SRC 0xF1) and short frames, fast init 25 ms BREAK, 5-baud 0x33 slow init,
  sum checksum. [verified] — corroborates `catalog/ecus/5am.json`.
- **Vasiy/ecu-map-viewer** @ `f454356b84c2` (open by policy) — read-only
  IAW 5AM .bin/.xdf calibration viewer (Ducati / Moto Morini). [verified-class read tool]
- **ajfemia/ECUDelphiMT05** @ `525603936e89`, **WadieBenabdouh/MT05-Terminal** —
  Delphi MT05 CAN readers for small Chinese motorbikes. [experimental]
- **Gabboxl/Ducati_HYM939_MY17** — IAW 7SM.D0 HW210 testing on a Hypermotard
  939; may corroborate the 7SM profile. [experimental]
- **mookiedog/ApriliaGen1ECU** (NOASSERTION) — Aprilia Gen1 ECU schematics. [experimental]
- Remaining hits (VAGFlasher/ME17, SIMK43 Hyundai tools, ME7.9 Toyota) are
  car ECUs — noted, not adopted for motorcycle profiles.

## Round 24 — exhaustive ECU-family/part-number sweep (2026-11-04)

~50 authenticated GitHub repo-search queries by ECU family (Marelli IAW
5AM–P8, Bosch ME/MG/MSE, Delphi MT, Keihin/Shindengen/Denso/SIMK) and by
protocol×brand. Full results in `docs/ECU_PROTOCOL_SWEEP_2026-11-04.md`.

**New motorcycle-relevant sources:** denandz/5am_util @ 73ba1795 (BSD-3-Clause,
IAW5AM KWP2000/UDS firmware reader/writer — proof-of-concept, migrated to
Codeberg) [experimental]; josapratama/SmartFI-Diag-Universal @ 3d365022ab91
(MIT, ESP32 universal SmartFI KWP2000 scanner) [verified-class tool];
phduc775-png Honda Winner 150 K-Line telemetry doc @ a7f56c11b4ae
[experimental]; MarioLange1983/FanticAnalyzer (UDS-over-BLE e-shock)
[experimental]; mattb97267-ai/iaw5am "ducati immo off bin" — legal-use-only
citation, not vendored.

**Confirmed gap:** most motorcycle ECU families (IAW 5SF/7SM/8GM/15M/15P/
15RC/16M/18M/59M/11MP/P8, Bosch ME17/ME9 on bikes, Delphi MT80/86, Denso/
SIMK on bikes) have **no public repo-level protocol docs** — knowledge sits in
forums, XDF/BIN libraries and commercial tools. Public motorcycle protocol
coverage is concentrated in Honda Keihin K-Line, Yamaha K-Line/CAN, Suzuki
SDS, Marelli IAW 5AM/59M, Triumph K-Line and Buell DDFI. Findings documented
first per owner instruction; app integration is a follow-up.
