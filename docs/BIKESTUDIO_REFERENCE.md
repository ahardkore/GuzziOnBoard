# BikeStudio ECU fitment reference

[BikeStudio's public ECU database](https://bikestudio.io/ecu?lang=en),
consulted 2026-10-31, reported **597 ECU entries**, organized under Honda and
Yamaha model pages. Each visible model page provides source-listed part
numbers, years, displacement and market. Individual pages may also mention
ECU maker and MCU type. The site says pinout images, ECM ID, calibration and
flash size are in its separate Partner app. We did not access or bundle the
app, its proprietary data, firmware, pinouts or diagnostic protocols.

The Garage has a local searchable **partial** reference index: 260 source rows
across 32 manually reviewed model pages. Each result links to its particular
model and part page. Source labels, model aliases, raw year strings, cc and
market are preserved; a blank is displayed as not stated. These are individual
public factual references, not a copy of the 597-entry database. The full site can be opened through an explicit external link; offline search
queries are not sent to it.
A separate button in Tools' ECU-number comparison opens this reference with the
part number. Offline searches and Garage matching do not change protocol
capabilities, connect to an ECU, authorize flashing, or identify a motorcycle.

The source contains inconsistencies: for instance, several CBR1000RR and
CBR600RR and CBR650F entries report 150 cc, while another CBR650F row reports
550 cc. Two CT 125 rows and a CB150R row have reversed year ranges. The source
values are shown verbatim, never corrected or silently reordered.
When filtering by year, unknown and invalid years stay visible and are marked
for review; valid nonmatching years are excluded. The optional market filter
matches source wording exactly (case-insensitively) while retaining unstated
markets. It does not infer a country from a region: selecting Indonesia hides
rows labeled Asia, so check both labels before drawing conclusions. A market
such as Asia does not imply compatibility in another market. Verify the label, model, market,
year and other manufacturer references. Matching is not a calibration,
checksum, software version or recovery validation.

Sixteen model labels without an equivalent existing exact catalog label have
reference-only Garage entries: Honda Grom / MSX 125 (2013–2022), CT 125
(2022), ADV 150 (2018–2021), ADV 160 (2022–2023 and 2026), PCX-150
(2017–2020), PCX 160 (2021–2023 and 2025–2026); and Yamaha YZF-R15
(2014–2026), Mio M3 (2015–2021), AEROX 155 (2017–2022), AEROX NEW
(2021–2024), NMAX 155 (2017–2022), NMAX NEW (2021–2026), MT15
(2019–2026), XSR 155 (2019–2026), WR 155 (2021–2026), and XMAX
(2017–2026). Only years covered by at least one valid source row are listed;
gaps and market distinctions matter, and a range is not a promise that a
part fits every model/market. The shared reference-only profile is a neutral
placeholder, **not** a claim that these motorcycles share an ECU family. Its
physical and simulator sessions, memory and programming are all unavailable.
It permits offline vehicle selection only. For existing Honda garage models,
part suggestions remain separate from their existing profiles; notably an MGZ
part listed alongside MGZ-A03 is not treated as an A03. A separate ECU-only
research reader recognizes 60 source-derived Honda ID candidates only after live ID
matching; the BikeStudio listing neither selects it nor establishes support.
Matching source-part results show a text lead to that desktop ECU-only
option, with its synthetic-test disclaimer; it is not a capability change. Other source models not in our catalog can still be searched
but are not automatically added or given a guessed profile.

BikeStudio describes its own HDiag Pro read/write functionality and YDIAG Pro
live diagnostics, but the public listing does not publish an implementable ECU
communication or checksum algorithm. Those vendor capabilities do not become
GuzziOnBoard capabilities by association. Nothing has been hardware-tested in
this integration. The site's published terms forbid copying workshop data for
marketing lists or automated scraping; this work does not access its workshop
listings or scrape them. Consult the source directly for current data and any
applicable terms and permissions before attempting bulk redistribution.


## Optional online model lookup

In the local desktop/browser workstation, open **Garage → Find a bike or ECU
part → Look up more models on BikeStudio**. The first button makes one HTTPS
request to BikeStudio's public model index. Filter its returned labels and
aliases locally, select one source model, then click again to request only that
model's public part table. The selected source model and your network address
are visible to BikeStudio; no VIN, ECU image, local search query, diagnostic
identity or Garage selection is sent. Neither the index nor the model results
are persisted. The local offline subset remains usable without the internet.

The server only permits fixed `bikestudio.io` HTTPS paths, bounded responses,
no redirects, one request at a time and no bulk crawler. Parser failure or a
changed source page reports an error, not guessed entries. External text is
displayed as text, with source URLs constrained to the same site. The optional
year filter retains unknown and malformed ranges for review. This opt-in
lookup has synthetic tests only; the development sandbox could not connect
directly to the site, so live network and HTML behavior in the installed app
have **not** been verified. The static hosted demo does not proxy external
requests; use the explicit source link there. The source's terms and site
availability apply. A returned part never creates a vehicle entry, selects an
ECU, changes fitment gates or enables diagnostics, reading or writing.
