# ECU number research and external catalogs

The **Tools → ECU number & bike research** worksheet works in both the installed
workstation and hosted demo. Enter a part/ECM type, hardware ID, software ID,
or a combination. The fields are compared separately against a **small**
source-labelled set of examples and any local list you load. Matching ignores
ASCII case, spaces, dots, underscores, slashes and hyphens, but preserves all
letters and digits, including leading zeros. Because punctuation might be
significant in some numbering systems, compare the original identifiers too.
An entry appears when at least one corresponding field matches; a different
entered field is explicitly marked **DIFFERENT**, and missing source fields are
marked unknown. This prevents shared hardware from being confused with matching
software. Results are research leads, not vehicle identification or build,
checksum or flashing authorization. They do not change workstation selection.

The worksheet makes one opt-in [MotoBinFiles](https://motobinfiles.com/)
product-search link per supplied identifier. Clicking a link opens the vendor's
site and sends the identifier as a URL query; avoid personal data and VINs.
Results, availability, pricing, matching rules and data completeness are the
vendor's responsibility. No search results or commercial XDF/BIN files are
copied into GuzziOnBoard. Its separate [binary identifier](https://motobinfiles.com/identify/)
requests an upload, which GuzziOnBoard never performs. Do not upload a file
unless you choose to share it. The lookup does not scrape or mirror the vendor's
entire catalog and may not find every listing. For example, its
[MGZ-A03 listing](https://motobinfiles.com/product/38770-mgz-a03-cbr500r-cb500f-2013-2015-xdf/)
reports 2013–2015, whereas HondaECU-1 describes the relevant family as
2013–2016; keep the sources' claims separate and verify the particular ECU.

## Local reference lists

Load an authorized UTF-8 JSON list in the worksheet. It stays in tab memory,
is not uploaded, and is removed on refresh or **Remove local list**. Up to
512 KiB and 1,000 entries are accepted; `vehicle` and `source` and at least
one of the three identifier fields are required. Source is displayed as text,
not executed as a link or HTML. Example:

```json
{
  "records": [
    {
      "part": "38770-EXAMPLE",
      "hardware": "HW123",
      "software": "SW456",
      "vehicle": "Example bike, model years and market",
      "source": "Example: workshop record or source URL, date accessed"
    }
  ]
}
```

Records may be incomplete and may contradict one another. No range expansion,
VIN decoding, automatic ECU detection, network retrieval, database syncing, or
OEM part interchangeability is implied.

## Other supplied sources reviewed

* [BlackFlag ECU, commit ac68bf5](https://github.com/bad-antics/blackflag-ecu/tree/ac68bf5e2fcb4700d9b0baf4d6a009c923aaed46)
  is an MIT-licensed Windows automotive suite. The public tree contains an
  executable LFS pointer, documents and automotive model data, but not the C#
  source implementing its advertised scanner, tuner, unlock or flash features.
  These claims cannot by themselves establish motorcycle protocols or add
  those features here; no executable, automotive data or code was imported.
* [TuneECU Austrian custom maps](https://tuneecu.net/AustrianCustomMapList.html)
  lists configuration-specific 990-family examples. Its custom maps warning
  calls for dyno evaluation; a filename or tune number is not an ECU identifier.
* [TuneECU Triumph twin custom tunes](https://tuneecu.net/Twin_Custom_Tune_list.html)
  distinguishes VIN ranges, instruments and intake/exhaust configurations.
* [TuneECU obsolete Triumph three-/four-cylinder tunes](https://tuneecu.net/ObsoleteTune_List.html)
  distinguishes VIN ranges, markets and exhausts and lists replacement tunes.
* [TuneECU obsolete Triumph twin OEM tunes](https://tuneecu.net/Twin_OEM_obsolete_Tune_list.html)
  lists historical tune numbers and replacements, not universal fitments.
  The pages say current OEM maps are available through TuneECU, and the author
  does not support the individual tunes. We provide source links, not copied
  maps, automatic tune recommendations, map downloads or flash support.
* [EcmSpy supported ECMs](https://www.ecmspy.com/supported.shtml) gives Buell
  ECM type/model examples and EcmSpy-specific capabilities. Four source-labelled
  examples are available in the worksheet; see the source for its full list.
  It warns that files from different ECM types are not interchangeable. EcmSpy
  support does not establish a GuzziOnBoard Buell live or flashing protocol.

Catalog references and byte sizes cannot prove fitment, ECU identity, software
compatibility, checksum correctness, tune safety, permissions or legality.

## Shared ECU family cross-reference

**Tools → Shared ECU family cross-reference** uses the live local workstation
catalog (or the generated hosted-demo snapshot) and XDF catalog. Select a
profile to see the associated model/year entries with their confidence and
notes, then the explicitly mapped XDF family labels and source-listed fitments.
Select a standalone XDF family label to browse its source-listed motorcycles
without assuming an equivalent vehicle profile. For example, the existing
`5am` profile groups Moto Guzzi, Ducati and Aprilia model entries, while the
`15P` XDF catalog includes Aprilia and Piaggio source labels. They are
cross-references, not interchangeable ECU part numbers. Catalog fitments can
overlap; source years, markets and software must be reviewed individually.
`HONDA-RESEARCH` is an umbrella for unrelated research XDFs and is deliberately
not offered as one shared family.

Vehicle catalog provenance is listed in `guzzionboard/catalog/vehicles.json`;
XDF source URLs are shown per result and in `guzzionboard/xdfs/PROVENANCE.json`.
Family groups and XDF labels do not establish a matching software calibration,
allow a map build or change the selected vehicle. Use exact identifiers and
independently verify the definition and checksums for the image.

## Kawasaki Ninja 7 Hybrid source examples

The [Ninja 7 Hybrid CAN research](https://github.com/mgithens1/kawasaki-can-hack/tree/26820ddf88d682c7071b0825252c7fa0b82c709a) reports current ECU part `49245-2655` and software `2102D11220244156`, plus broadcast identifiers reported as ECU part `49245-230500000` and hardware `26105-0001`. The source explicitly notes the broadcast ECU part differs from the KWP result; they must not be collapsed into a single exact part. Both examples in the identifier worksheet retain their own source labels. These are observations from the source's researched motorcycle, not proof that all Ninja 7 hybrids share an ECU or calibration, and not authorization for programming.

## Kawasaki 2026 ZX-6R / Ninja 650 / Z650 cross-reference

The commercial flashing vendor groups years and markets and does not say
which listing row is fitted to each model year. Check the ECU label, market and
revision before drawing a conclusion. The Z650 source has an internal year
conflict: the product title says **2023–2025**, but its feature list says
**2023–2026**. Confirm 2026 Z650 applicability with the vendor.

* [2024–2026 ZX-6R (636)](https://www.woolichracing.com/products/kawasaki/zx6r-636/2026/2026-kawasaki-zx6r-636-ecu-flashing.aspx): the grouped list includes `21175-1916` and several other numbers. A separate [FT ECU listing](https://ftecu.com/shop/2024-kawasaki-zx636-data-link-ecu-flashing-kit/) specifically identifies `21175-1916` as a **2024 US** example; it does not establish the installed ECU on every 2026 bike.
* [2023–2026 Ninja 650 / EX650](https://www.woolichracing.com/products/kawasaki/ninja-650-ex650/2026/2026-kawasaki-ninja-650-ex650-ecu-flashing.aspx): the grouped list includes `21175-1910` with source codes `TMQ2KQE0`, `TMQ2KQE1`, and `TMQ2KQEA`, plus `21175-1952 TMQ2KQL0` and other parts.
* [Z650 grouped source](https://www.woolichracing.com/products/kawasaki/z650/kawasaki-z650-ecu-flashing.aspx): its 2023–2026 feature list also includes `21175-1910 TMQ2KQE1`, but lists `21175-1952 TMQ2KQL1` rather than the Ninja listing's `TMQ2KQL0`. Its product title's year range is narrower as noted above.

For a **2026 Ninja 650 ABS EX650PTFAN** lead, the [Tri County Cycle fuel-injection parts viewer](https://www.tricountycycle.com/Parts/Parts-Finder/kawasaki/motorcycles/2026/ninja-650-ex650ptfan/fuel-injection/ccbd210d-4ff6-483a-a78f-31f4fc69adbb) lists `21175-1952` as an electronic control unit. [J.D. Power](https://www.jdpower.com/motorcycles/2026/kawasaki/ex650ptfan-ninja-650-abs-649cc/values) identifies EX650PTFAN as a 2026 ABS model; other US ABS model codes exist. This dealer listing is a candidate, not confirmation of a particular motorcycle's original or current ECU, calibration, reference code or emissions specification. The Woolich grouped list includes `21175-1952 TMQ2KQL0`, but does not assign this reference to EX650PTFAN specifically. Verify the installed label or ask a dealer to check the bike privately.

For a narrower **2026 non-ABS EX650RTFNN** lead, the [SRS Motorsports fuel-injection parts diagram](https://www.srsmotorsports.com/Parts/Parts-Viewer/kawasaki/motorcycles/2026/ninja-650-ex650rtfnn/fuel-injection/c8be47ab-2e32-492a-8d75-a6012da9b6f1) lists both `21175-1951` and `21175-1952` as electronic control units; the displayed diagram does not distinguish their applications. It does not identify a particular installed ECU or establish an ECU reference code. Do not assume the same parts apply to ABS or other markets. Kawasaki's [2025 EX650PSFAN diagram](https://www.kawasaki.com/en-us/OwnerCenter/DownloadDiagramPdf/332332?modelcode=EX650PSFAN&modelyear=2025) also lists both; its model and year are different.

A commercial [OldSkullTuning XDF](https://oldskulltuning.com/kawasaki-ninja-650-versys-650-z-650-denso-1mb-tunerpro-xdf/) is advertised for **2023** Ninja 650 Denso 1 MB files, among other 2023 models. The vendor notes that available maps vary by software and calibration and that a separate tool is needed to read or write the ECU. This does not establish ECU size, definition compatibility or checksum behavior for a 2026 bike; the definition is not bundled.

The local ECU worksheet lists each part and its source code separately; it
allows searching the code as an **unclassified source reference**, rather than
assuming it is a software version. `21175-1910 TMQ2KQE1` is the strongest
shared **listed combination** between those Ninja 650 and Z650 groups; it does
not prove identical calibration, present fitment, interchangeability or
flashability. `21175-1952` appears in both groups with **different** listed
codes. The ZX-6R group is separate and the listings do not establish that the
ZX-6R and 650 share an ECU. A match against one field is reported as a lead;
other supplied fields can still conflict.

The desktop garage contains distinct research-only model entries. Their
existence does not grant diagnostic, memory, image-build or flashing
capabilities. A user-provided binary and definition can be examined using
the existing non-writing, hash-locked research preview; neither compatibility
nor checksum correctness is established by that preview. The commercial
vendor advertises read/write capability using its own paid interface, harness
and software. Its products do not document an interoperable GuzziOnBoard
protocol and their licensed maps, definitions and binaries are not bundled.
