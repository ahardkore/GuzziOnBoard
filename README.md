# GuzziOnBoard

**A multi-brand motorcycle diagnostics, calibration research and workshop workstation.**

GuzziOnBoard brings a motorcycle garage, diagnostic sessions, ECU map tools and
workshop utilities into one open-source application. It started with Moto Guzzi
and now includes information and workflows for other makes, including Ducati,
Aprilia, Honda, Kawasaki, Triumph, Suzuki, BMW and Harley-Davidson. Coverage is
specific to the ECU, software and operation—not a promise of full support for
every motorcycle from those manufacturers.

[Try the browser demo](https://ahardkore.github.io/GuzziOnBoard/web/index.html) ·
[Visit the project site](https://ahardkore.github.io/GuzziOnBoard/) ·
[Desktop releases](https://github.com/ahardkore/GuzziOnBoard/releases) ·
[Documentation](#documentation)

> **Know the limits before connecting.** The hosted demo is simulated and
> cannot connect to a motorcycle. GuzziOnBoard's hardware integrations have
> not been validated by this project on a physical motorcycle. A supported
> source, a catalog entry or a matching identifier is not proof of compatibility.
> Physical ECU writing remains blocked pending the required evidence and bench
> confirmation. No OEM firmware is included.

## What you can do

- **Explore diagnostics:** select a motorcycle or ECU profile, review the
  evidence and available capabilities, and use supported identification, live
  data, fault or service workflows where the selected profile permits them.
- **Practice without a bike:** use the simulator for diagnostics, fault
  injection, guided tests and a simulated backup/write/verify cycle. The
  hosted workstation runs in the browser with labelled virtual fixtures and
  offers no real-bike transport.
- **Review calibration data:** render and compare bundled or user-supplied
  TunerPro XDF definitions, inspect maps, stage edits, visualize tables and
  analyze logs. Research-only definitions allow preview but block image builds.
  Building an offline file is not the same as writing an ECU.
- **Cross-reference ECU families:** browse model/year entries sharing a catalog
  profile across makes, and source-labelled XDF families, without assuming the
  exact part number or calibration is interchangeable.
- **Investigate ECU numbers:** compare part, hardware and software identifiers
  against a small attributed reference set or a local list. Optional
  MotoBinFiles search links open only when requested; no ECU image is uploaded
  by GuzziOnBoard.
- **Work with captures and records:** inspect CAN and K-Line captures, use
  offline multi-brand decoders, record and compare sessions, and produce
  reports. Workshop tools include service-interval arithmetic, manual-text
  search, gearing, log conversion and a bench signal generator.
- **Use the desktop or browser interface:** the installed desktop shell and
  local browser workstation share the same application. The static hosted
  demo is useful for exploring the interface without installation.

## Coverage: what is and isn't enabled

| Area | Current scope |
| --- | --- |
| Marelli profiles | A catalog of Moto Guzzi and selected Ducati/Aprilia applications, with capability and confidence gates. The 5AM path has published capture evidence; GuzziOnBoard's physical integration has not been validated on a bike. |
| Kawasaki, Suzuki and Triumph | Source-informed read-only paths for the 2006 Kawasaki ER-6n, 2012 Versys 650, 2011 Suzuki GSX-R600, a raw snapshot attempt for the 2004 GSX-R1000, Ninja 7 Hybrid 2024+ (CAN), and 2012 Triumph Daytona 675. Another 37 source-listed Kawasaki model labels can attempt raw KDS reads; compatibility is not guaranteed. Sensor interpretations can be uncertain; the GuzziOnBoard integrations have synthetic tests, not physical validation. |
| Kawasaki ZX-6R and 650 | 2024–2026 ZX-6R (636), 2023–2026 Ninja 650 and Z650 research entries and source-labelled ECU-number leads. The Z650 vendor year descriptions conflict. No live diagnostics or flashing are enabled for these entries. |
| Harley-Davidson | Read-only J1850/ELM327 and Delphi CAN identity/raw-DID research profiles; 121 J1850 and 80 CAN source-listed Harley model labels can select those attempts from Garage, plus offline J1850 and best-effort HDLAN capture analysis. Linux SocketCAN can also observe source-scoped Harley HDLAN broadcasts without application CAN transmissions. These live integrations are synthetic-tested only; they do not provide fault clearing, memory reading or flashing. Delphi region comparison and user-XDF research editing/export (including operator-declared file ranges) are offline and not flash-ready. |
| Honda | A source-listed PGM-FI K-Line read-only attempt for 76 Honda model labels (tables and compatibility vary; no hardware validation); source-scoped, synthetic-tested live data for the 2005 CBR600RR and an ECU-only CB500F DashBle option (source year/ECU unspecified), with unverified raw ECM ID candidates. An explicitly confirmed experimental MGZ-A03-only image-read attempt is available, but has no hardware validation and cannot create a verified backup; other Honda profiles use offline K-Line response decoding and XDF research. Two narrowly scoped offline checksum builders cover exact Honda CBR1000RR A01 and CB500/CBR500R MGZ-A03 source-image/XDF combinations. The MGZ byte order is inferred; neither builder identifies an ECU or enables flashing. |
| Ducati broadcast observation | A bounded receive-only Linux SocketCAN observer uses existing Ducati Mitsubishi source mappings for the Panigale, Multistrada 1200 and Diavel models named by that source. No diagnostic requests, identification, memory or flashing; synthetic-tested only. |
| Other research | A source-scoped Linux Yamaha MT-03 660 (2010) K-Line dashboard-stream observer is live receive-only. Selected Suzuki and BMW capture decoders, CFMoto checksum inspection, and Yamaha MT and Bajaj RS200 checksum-corrected copies are offline research—not universal diagnostic or tuning support. These integrations have only synthetic tests in this project and do not authorize flashing. |
| CAN and J2534 | Passive capture analysis and virtual CAN rehearsal are available. An opt-in ECU-only generic OBD-II 11-bit CAN profile reads supported standard live PIDs, stored emissions codes and optional Mode 09 VIN/calibration IDs on ECUs that answer it; it is not a vehicle fitment claim and has synthetic/virtual tests only. It cannot read ECU images. Physical MIU G4/11MP sessions remain blocked; J2534 is driver inventory only, not a transport. |

The catalog describes **individual** ECU profiles and their permitted actions.
Vehicle selection, shared ECU families, file sizes and hashes do not by themselves
establish fitment, a safe tune, or permission to program. See
[physical validation](docs/PHYSICAL_VALIDATION.md),
[Harley scope](docs/HARLEY_TUNING.md), and the
[XDF library](docs/XDF_LIBRARY.md) for the details.

## Get started

### Try the browser demo

Open the [hosted workstation](https://ahardkore.github.io/GuzziOnBoard/web/index.html),
select a simulator-supported bike in **Garage**, and connect. The demo runs
locally in the page; its virtual motorcycle, adapter and memory operations are
simulated. Local research tools can process files you choose in the browser.
It cannot communicate with real hardware or run the desktop checksum providers.

### Install the desktop app

Find the available platform builds on the
[releases page](https://github.com/ahardkore/GuzziOnBoard/releases). Releases
may lag the current source branch. Windows, macOS and Linux packaging differ;
Linux builds may open the system browser if a window engine is unavailable.
See [Desktop setup](docs/DESKTOP.md) for installation, exports, troubleshooting
and the installation self-test.

### Run from source

Python 3.11 or newer is required. From a checkout:

```bash
python3 run_server.py
```

Open `http://127.0.0.1:8000`, choose a simulator-supported motorcycle such as
**Moto Guzzi → Griso 1200 8V → 2012**, and connect in simulator mode. The
server binds to localhost by default.

For the desktop shell or optional hardware transport dependencies:

```bash
python3 -m pip install -e '.[desktop]'   # desktop window, where supported
python3 -m pip install -e '.[hardware]'  # pyserial and python-can
guzzionboard-desktop                     # or: guzzionboard --desktop
guzzionboard-desktop --selftest         # installation check
```

Installing hardware dependencies does not enable unsupported protocols or
validate an adapter. Check the exact profile, wiring, operating conditions and
capability gates before connecting.

## Working with maps

In **ECU memory → Maps & tables**, select the applicable definition and a
user-supplied image. Review the displayed fitment, address base, table layout,
unsupported items and checksum requirements before interpreting values. XDF
files are third-party definitions, not firmware; their presence does not prove
they match a particular image. Local XDFs can also be placed in
`~/.guzzionboard/xdfs/`.

The editor supports staged cells, axes, comparisons, portable projects and
review-only log-derived proposals. Where an offline build is allowed, the
workflow requires evidence, a reviewed preview and applicable checksum
handling. Honda's built-in providers are explicitly selected and locked to
specific source images and definitions. Research-only XDFs cannot build
images. None of these steps enables a physical write or validates the tune.
See [XDF library and Honda limitations](docs/XDF_LIBRARY.md),
[checksum providers](docs/CHECKSUM_PLUGINS.md), and
[programming gates](docs/PROGRAMMING.md).

## Safety and privacy

- Do not operate diagnostic or tuning controls while riding. Use suitable
  ventilation, stable power, the correct wiring and qualified supervision.
- Review each capability's evidence and the exact ECU hardware/software; stop
  on unexpected identity, communication, power or checksum results.
- Physical flashing is blocked in this build. The simulator's successful write
  does not change that. Back up and independently verify original data before
  any future ECU programming.
- Research tools process selected files locally. External links, including
  identifier searches, are optional and send information to the destination
  when opened. Avoid putting VINs or other personal data in search queries.
- Backups, session logs and calibration files may contain sensitive or
  proprietary data. Keep them out of public repositories unless authorized.

## Development and tests

```bash
python3 -m pip install -e '.[hardware,dev]'
python3 -m pytest -q
python3 scripts/build_demo_data.py --check

npm ci
npm run test:browser
npm run test:browser:desktop
```

Run the two Playwright suites sequentially: they share the test-results
folder. After changing catalog data, regenerate the hosted snapshot with
`python3 scripts/build_demo_data.py`. See
[architecture](docs/ARCHITECTURE.md), [desktop packaging](packaging/README.md)
and the [source review](docs/USER_SOURCE_REVIEW.md).

## Documentation

| Topic | Guide |
| --- | --- |
| Desktop setup and exports | [Desktop application](docs/DESKTOP.md) |
| ECU coverage, evidence and protocols | [Protocol notes](docs/PROTOCOL_NOTES.md) · [Physical validation](docs/PHYSICAL_VALIDATION.md) · [Hosted read sharing](docs/HOSTED_READ_SHARING.md) · [Cloudflare deployment](docs/CLOUDFLARE_DEPLOYMENT.md) |
| XDFs, maps and checksum providers | [XDF library](docs/XDF_LIBRARY.md) · [Checksum plugins](docs/CHECKSUM_PLUGINS.md) |
| ECU number and vehicle research | [ECU number research](docs/ECU_NUMBER_RESEARCH.md) |
| Harley diagnostics and Delphi research | [Harley tuning](docs/HARLEY_TUNING.md) |
| Programming and recovery boundaries | [Programming](docs/PROGRAMMING.md) |
| Workshop utilities and multi-brand sources | [Workshop tools](docs/WORKSHOP_REFERENCE_TOOLS.md) · [External research](docs/EXTERNAL_MOTORCYCLE_RESEARCH.md) · [Source review](docs/USER_SOURCE_REVIEW.md) |
| Project design and contributions | [Architecture](docs/ARCHITECTURE.md) · [Prior art](docs/PRIOR_ART.md) |

## License and acknowledgements

GuzziOnBoard is licensed under [AGPL-3.0-only](LICENSE). Bundled third-party
code, data and definitions have their own provenance and applicable terms; see
[`LICENSES/`](LICENSES/), [`vendor/`](vendor/) and
[`guzzionboard/xdfs/PROVENANCE.json`](guzzionboard/xdfs/PROVENANCE.json).
Upstream contribution is not required, but applicable source-distribution and
network-use obligations still apply. This independent project is not affiliated
with the motorcycle or ECU manufacturers or the authors of GuzziDiag.


**Suzuki SV650 research:** The desktop includes source-scoped read-only K-Line polling for the 2007 SV650AK7 (candidate sensor conversions) and the 2003–2005 SV650 (raw snapshot only). The upstream AK7 author warns that some conversions are inaccurate; neither integration has been physically tested here. Neither provides ECU memory reading or tuning. See `docs/EXTERNAL_MOTORCYCLE_RESEARCH.md` for sources and limits.
