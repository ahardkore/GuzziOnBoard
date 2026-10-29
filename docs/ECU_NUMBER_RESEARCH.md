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
