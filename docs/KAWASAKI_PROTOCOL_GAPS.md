# Kawasaki protocol gaps — what `kawasaki.diagsys.com/kdt` is, and where the missing data can actually come from

Written 2026-11-04. This note records an attempt to use the Kawasaki
Diagnostic Tool (KDT) distribution as a source for the Kawasaki families this
project cannot yet talk to. The short version: **it is a different product for a
different ECU family, and it does not contain the missing motorcycle
protocols.** The long version is below, because "the obvious source was a dead
end" is only useful if the next person can see why in one screen.

Confidence vocabulary is the same as `docs/PROTOCOL_NOTES.md`. Nothing in this
document promotes a catalog entry by itself.

---

## 1. What the target actually is

`https://kawasaki.diagsys.com/kdt` is the download page for the Windows build of
the **Kawasaki Diagnostic Tool**, published by Diagnostic Systems Associates,
Inc. (DSA, Kalamazoo MI) for **Kawasaki Engines** — the small-engine division
(FS / FT / FX 730V and 850V-EFI vertical twins), not Kawasaki Motorcycle & Engine
Company's motorcycle diagnostics.

| Observed | Evidence |
|---|---|
| Product is "Kawasaki Engines"; required hardware is a **KEI** (Kawasaki Electronic Interface) module, kit `99969-6490` | [KDT user's guide](https://kawasaki.diagsys.com/kdtusersguide/), [KDT learn-more page](https://kdt.diagsys.com/learn_more/) |
| Stated engine coverage: FS, FT, FX 730V and 850V-EFI | [99969-6490 dealer listing](https://www.propartsdirect.net/kawasaki-99969-6490-kei-efi-bluetooth-diagnostic-tool.aspx), [RR Products listing](https://www.rrproducts.com/kawasaki-efi-diag-kit-bluetooth-rak99969-6490.html) |
| Fault codes are "automotive-style P codes & J1939 trouble codes" | [RR Products listing](https://www.rrproducts.com/kawasaki-efi-diag-kit-bluetooth-rak99969-6490.html) |
| Transport to the vehicle is the KEI module over **USB or Bluetooth**, device name `KEI-####`, one paired module at a time, red LED blinking at 2 s = idle/ready | [PC guide — Connection/Settings](https://kawasaki.diagsys.com/kdtusersguide/), [Android guide](https://kdt.diagsys.com/android/), [iOS guide](https://kdt.diagsys.com/ios/) |
| PC app is Windows/.NET 4.8, self-registering by dealer e-mail, **max 10 runs unregistered**, KEI firmware updated from the About screen | [PC guide — Installation/About](https://kawasaki.diagsys.com/kdtusersguide/) |
| Functions: active/inactive trouble codes + clear, three built-in live-data sets (All / Residency / Main) plus custom sets, actuator tests, "Read Data" ECU info, recordings, printable reports submitted to Kawasaki | [PC guide](https://kawasaki.diagsys.com/kdtusersguide/), [Android guide](https://kdt.diagsys.com/android/) |
| Blog taxonomy distinguishes the mobile apps as **"M3B ECU only"** | [Downloads page](https://kawasaki.diagsys.com/wp/index.php/downloads/) |

The Kawasaki *motorcycle / ATV / PWC* tools are a separate KHI product line —
KDS, KDS2 (`KDS2.exe`) and KDS3 (`KDS3.exe`, `KDS3_KHI.exe`) — with their own
interfaces and the `57001-1725` signal converter for watercraft. KDT shares
nothing with them but the brand name.

## 2. Why that is a dead end for the gaps in this repository

Every Kawasaki entry here is a **motorcycle** profile:

* KDS/K-Line family — `kawasaki_er6n_2006` (iKawa, 10250 baud, addressed
  `80 F1 11 …`), `kawasaki_versys650_2012` (aster94, 10400 baud), plus the two
  raw `kawasaki_kds_*_research` sessions.
* CAN family — `kawasaki_ninja7_hybrid` (`0x764` request / `0x746` response,
  500 kbit/s, ISO-TP + KWP payloads).
* Research-only stubs from commercial fitment lists — `z650`, `ninja650`,
  `zx6r_636`, each with no wire definition at all.

KDT occupies none of that. It is an M3B-class small-engine ECU on a KEI bridge,
diagnosed through a Windows/.NET application whose own data model (cylinder head
temperature in °F, operator-presence switch, blade-clutch torque, J1939-style
P codes) is garden-equipment shaped. Its public data-item list (§ Appendix A) is
names, units and ranges — there is no local-identifier table, no session
initialization, no bus framing anywhere in it. Even if the tool were fully
understood, it would describe a mower engine's ECU, not a Ninja 650's.

Stated plainly: **KDT cannot supply the missing KDS local-identifier tables, the
post-2020 CAN identifier pairs, or the Denso flash geometry.** Those have to
come from KDS-family evidence or from a capture on the actual vehicle.

## 3. What is still missing, per family

| Profile | Transport | Established (and by what) | Missing |
|---|---|---|---|
| `kawasaki_er6n_2006` | K-Line | 10250 baud, `80 F1 11`, local IDs `02 04 05 06 07 08 09 0A 0B 0C 44`, per-ID lengths and scaling — iKawa, one author-tested ER-6n | ECU part/software ID, DTC read/clear, actuators, memory, any second model confirmation |
| `kawasaki_versys650_2012` | K-Line | 10400 baud, `10 80` session start, `21 04/05/06/07/09/0B/0C` reads — aster94 | Whether those lengths/IDs hold on any other model; DTCs; IDs beyond the seven read |
| `kawasaki_kds_research` / `_generic_research` | K-Line | Framing only, synthetic tests | Everything semantic; deliberately raw |
| `kawasaki_ninja7_hybrid` | CAN 500 kbit/s | `0x764`/`0x746`, identification, live, DTC read — mgithens1 observations | Actuators, routines, memory; security algorithm explicitly unresolved upstream; no second model |
| `kawasaki_z650_2023_2026`, `ninja650_2023_2026`, `zx6r_636_2024_2026` | CAN | Part numbers from commercial flashing vendors | **All** wire detail: bitrate, ID pair, addressing, DIDs/RLIs, scaling, DTC format |

Two things are worth calling out because they are cheap to get wrong:

1. **The K-Line baud is not one number.** The ER-6n profile uses 10250 and the
   Versys research profile uses 10400. Both come from working implementations, so
   both are probably right *for their own ECU*; do not "unify" them.
2. **`0x764`/`0x746` is one observed bike,** a Ninja 7 Hybrid. A different
   2023+ model sharing the 500 kbit/s bus may use a different pair. The three
   stubs above are stubs precisely because nobody has published the pair.

## 4. Where the missing pieces legitimately come from

In rough order of cost:

1. **Public prior art you can re-read.** iKawa, aster94's Keyword-Protocol-2000,
   `mgithens1/kawasaki-can-hack`, `HerrRiebmann/KDS2Bluetooth`,
   `uronour/suzuki-Kawasaki-ecu-tool` — all already cited in
   `EXTERNAL_MOTORCYCLE_RESEARCH.md`, and the first three are already integrated.
   New value here comes from *additional captures*, not from re-reading them.
2. **Your own bike, your own adapter** — the honest, high-value path. Section 5.
3. **Kawasaki service documentation** you have lawful access to (a genuine
   service manual for your model often prints the diagnostic connector pinout,
   the DTC list, and sometimes the sensor table).
4. A KDS/KDS2/KDS3 install you are licensed for, used to *observe your own
   vehicle*. Note that the catalog consequences of any of these are identical:
   nothing is promoted past `inferred` without a capture.

## 5. Capture recipes

None of this needs anything cracked. All of it observes a bus between hardware
you own.

### 5.1 KDS / K-Line (roughly 2003–2012)

Adapter: any KKL 409.1-style USB K-line interface (the same part 5AM and 7SM
work uses), or a bench logic analyzer.

```
# what to record, per transaction
#   host -> ECU : 80 F1 11 <len> <svc> <local id> <sum>
#   ECU  -> host: 80 F1 11 <len> 61 <local id> <data...> <sum>
```

* Set the line to the baud your ECU answers at: 10250 for the ER-6n family,
  10400 for the Versys family. Sweep 4800/9600/10250/10400 if unknown — a
  wrong baud gives framing garbage, never plausible data.
* Capture raw bytes **with timestamps and inter-byte gaps**, not decoded values.
  The `inter_byte_delay` (currently 5 ms) and tester-present interval are
  repeatedly the difference between a session that holds and one that drops.
* Sweep local IDs one at a time (`21 00` … `21 7F`) at a fixed session and log
  the length of every answer. Unknown IDs that answer are the interesting ones;
  unknown IDs that time out are equally information.
* Record the ignition-on → crank → idle transition, because several IDs only
  answer in one of those states.

### 5.2 KDS2 Bluetooth module

The KDS2-era wireless module is a serial bridge; the app is the only thing that
knows the framing, and you can watch it on your own phone.

```
adb shell setprop persist.bluetooth.btsnooplogmode full
# pair the module, run one session, then
adb bugreport          # or pull /data/misc/bluetooth/logs/btsnoop_hci.log on rooted
```

Open the `btsnoop_hci.log` in Wireshark: note the GATT service/characteristic
UUIDs actually used, the ATT handle writes and notifications, and then the
byte-for-byte payloads inside them. The payload is the KDS framing of §5.1 with
whatever extra byte the bridge adds — that delta is the thing nothing in public
prior art documents, and it is worth writing down.

### 5.3 CAN era (2020+)

```
sudo ip link set can0 type can bitrate 500000
candump -L can0 > kawasaki-can.log      # log format, timestamps in seconds
```

* Log **both directions**: your tester-present frames and the ECU's replies,
  plus every broadcast ID that appears when the ignition changes.
* Start from the known pair (`0x764`/`0x746`) and sweep services one at a time:
  `10 01/03`, `1A 80/90/9x`, `21 xx`, `22 xx xx`, `2E`, `27 01`, `31`, `3E 00`.
  Expect SecurityAccess before anything interesting, and expect it to be
  unresolved — the Ninja 7 source says the same.
* Watch for 29-bit extended IDs. A profile written only for 11-bit IDs will
  silently see nothing.
* Sniff a *dealer or vendor tool* session on your own vehicle if you have one;
  a single captured KDS3 conversation is worth fifty swept guesses.

### 5.4 KEI / KDT (Kawasaki Engines) — only if small engines are in scope

This project has no Kawasaki Engines profile, so this is optional. If one is
ever wanted: on Windows, USBPcap + Wireshark on the USB link between the KDT
application and the KEI, or the Android HCI snoop of §5.2 for the Bluetooth
path. Enable "Show Comm Log" on the About screen first — the tool logs its own
conversation, which tells you which framing questions to ask of the capture.

## 6. Turning a capture into a catalog entry

The mapping is mechanical, and `docs/BRAND_TOOLS.md` gives a worked decoder
table to imitate.

| Capture fact | Catalog field |
|---|---|
| Transport (K-Line / CAN / BLE bridge) | `transport` |
| Init bytes, baud, addresses, gaps | `kline.init`, `kline.baud`, `kline.address`, `kline.tester_address`, `kline.inter_byte_delay` |
| Service + local ID | `parameters[].local_id` |
| Answer width | `parameters[].length` — **reject** wrong-width answers rather than decoding them |
| Raw-to-unit arithmetic | `parameters[].digits`, `unit`, plus the formula in the decoder |
| Which service answers with what | `capabilities` (`live`, `dtc_read`, …) |
| Everything else | stays out |

Rules that have already saved this project from publishing wrong numbers:

* **Confidence is earned, not assigned.** A successful capture is
  `verified-capture`; a vendor list or a sibling ECU is `inferred`/`unknown`,
  and `session.physical_supported: false` must stay set for those.
* **A frame with the wrong length or checksum is rejected, never trimmed.**
  A checksum byte read as data is the standard failure mode.
* A simulator or `cansim` session proves the application, not the vehicle, and
  is refused by the confirmation workflow — see
  `.github/ISSUE_TEMPLATE/protocol-confirmation.yml`.
* Submit via that template with the frozen `.session.jsonl` so a reviewer can
  recompute every claim.

## 7. Boundaries — what was *not* done, and why

* **No portal extraction.** The KDT distribution is behind a dealer
  registration. I did not create, borrow, or work around an account, and I did
  not attempt to pull the installer or the applications from the stores.
* **No license or registration circumvention.** The 10-run registration limit
  and the KEI firmware update path are part of a licensed product; defeating
  either is not research.
* **No decompilation dump published.** Reverse-engineering a binary you are
  licensed to run, in order to interoperate with your own equipment, is a
  defensible activity in several jurisdictions, but *republishing* extracted
  proprietary tables, DTC text or embedded documentation is not, and this
  project has nowhere to put such material that would not poison its licensing.
* **No vendor tables transcribed into the catalog.** Appendix A below records
  *what kinds of data* the tool exposes. It deliberately contains no wire
  mapping, because the public documentation contains none — inventing one would
  be exactly the silent misread this project's confidence vocabulary exists to
  prevent.
* **Also:** `kawasaki.diagsys.com` is not reachable from this development
  sandbox (TLS connection refused), so everything in §1 comes from the mirrored
  pages DSA serves on `kdt.diagsys.com`, plus dealer listings, and is cited
  per row rather than asserted.

If the actual goal is a specific bike, say which one. A capture from *that*
bike is worth more than any amount of tool archaeology.

---

## Appendix A — KDT public data items (names/units only, no wire mapping)

Transcribed facts (name, unit, range) from the vendor's public
[PC data-items list](https://kawasaki.diagsys.com/kdtusersguide/parameters.html)
and the [mobile list](https://kdt.diagsys.com/android/parameters.html). This is
the *shape* of an M3B-class engine ECU's data model, and it is useful only as a
reminder of how different it is from a motorcycle KDS sensor table.

| Item | Unit | Range |
|---|---|---|
| Engine RPM | RPM | 0–18000 |
| Cylinder Head Temperature | °F | −40–420 |
| Cylinder Head Temperature Voltage | V | 0–5 |
| Intake Air Temperature / Voltage | °F, V | −40–420, 0–5 |
| Ignition Key Battery Voltage | V | 10–17 |
| Relay Battery Voltage | V | 4–20 |
| Manifold Air Pressure (sensor voltage / value) | V, InHg | 0.5–4.5, 0–75 |
| Ambient Air Pressure (voltage / value) | V, InHg | 0.5–4.5, 0–75 |
| Mass Air Flow | mg/tdc | 0–1023 |
| Throttle Position Sensor 1 / 2 voltage | V | 0–5 |
| Throttle Position (blade angle) | °TPS | 0–85 |
| Hand Throttle Input Sensor Voltage | V | 0–5 |
| TPS 1 / 2 lower adaption values | V | 0–5 |
| Advance Spark | °CRK | −30–90 |
| Injection Time | ms | 0–262 |
| Injection Mode / Ignition Timing / Engine State / CPS Sync / MIL / Fuel Pump / Main Relay / Cut-out | enumerated states | — |
| Electronic Throttle Control PWM | % | −100–100 |
| ECU Reference Voltage 1 / 2 | V | 0–5 |
| Engine Run Time | h | — |
| Engine Torque Static At Clutch | ft-lb | — |
| RPM Limit, Idle RPM, Engine Speed Operating Limits 1–6, Load Operating Limits 1–7 | RPM, % | factory values |
| Low Oil Pressure Switch State / Counter | On-Off, count | — |
| Operator Presence Switch Voltage | V | 0–5 |
| Engine Speed Range / Load Range minute counters 1–6/7 | min | — |
| Max/Min recorded CHT, IAT, battery voltage | °F, V | — |
| Number of Clear Failure Memory | count | — |

Note what is absent: no identifiers, no request/response examples, no DTC
numbers, no scaling integers. That absence *is* the finding.

## Appendix B — sources

Primary (public vendor documentation):

* <https://kawasaki.diagsys.com/kdt> — Windows installer download page (target of the original request; unreachable from the dev sandbox)
* <https://kawasaki.diagsys.com/kdtusersguide/> — PC application user's guide
* <https://kdt.diagsys.com/learn_more/>, <https://kdt.diagsys.com/android/>, <https://kdt.diagsys.com/ios/> — app guides, KEI pairing
* <https://kawasaki.diagsys.com/wp/index.php/downloads/> — distribution page and "M3B ECU Only" taxonomy
* <https://kawasaki.diagsys.com/kdtusersguide/parameters.html> — public data-items list

Corroborating (commercial):

* <https://www.propartsdirect.net/kawasaki-99969-6490-kei-efi-bluetooth-diagnostic-tool.aspx>
* <https://www.rrproducts.com/kawasaki-efi-diag-kit-bluetooth-rak99969-6490.html> — engine coverage, P/J1939 code support

Separating the two product lines:

* KDS / KDS2 / KDS3 are KHI motorcycle/ATV/PWC tools (`KDS2.exe`, `KDS3.exe`,
  `KDS3_KHI.exe`) — <http://en.informer.com/kawasaki-diagnostic-system-ver-3/>,
  <https://kawasaki-diagnostic-system-3.software.informer.com/>,
  <https://kawasaki-diagnostic-system.software.informer.com/>; the watercraft
  signal converter is `57001-1725` —
  <https://rivaracing.com/i-17283303-kds-3-signal-converter.html>.
* KDT is DSA's Kawasaki **Engines** tool on a `KEI` interface, kit `99969-6490`.

Third-party downloadable-installer catalogues are weaker evidence than the
vendor's own pages; they are cited here only for the product-line separation,
which does not depend on their version details.

In-repo cross-references: `docs/EXTERNAL_MOTORCYCLE_RESEARCH.md` (§ Kawasaki
KDS, § Ninja 7 Hybrid CAN), `docs/BRAND_TOOLS.md` (§ Kawasaki — KDS / K-Line),
`docs/ECU_NUMBER_RESEARCH.md` (§ Ninja 7, § 2026 cross-reference),
`docs/PROTOCOL_NOTES.md` (confidence vocabulary), `docs/PRIOR_ART.md` (gap map).
