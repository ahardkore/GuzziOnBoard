# Workshop reference tools

These tools work in the browser and in the desktop host without an ECU
connection. Nothing here changes service indicators, configures an ECU, or
recommends a modification.

## Service interval worksheet

Under **Tools → Service interval worksheet**, enter an interval and the
**documented last completed service**, plus the current odometer and/or the
as-of date. A complete distance group and a complete date group can be used
independently or together. Distance uses kilometres and whole numbers. Dates use
calendar months, clamping to the end of a short month (for example, January 31
plus one month becomes February 28, or February 29 in a leap year). A threshold
is reported due at equality. When both conditions apply, follow the earlier one.
A lower odometer than the last service is rejected rather than silently
assuming a reset.

The worksheet does **not** infer previous work from mileage multiples, save
service records, identify the motorcycle, account for the vehicle's age or
initial-service milestones, severe use, separate inspection/replacement cycles,
or diagnose condition. The operator must verify every interval and procedure
against the exact model/year/market manual and recorded service history.
Input and results are temporary and do not survive a page reload.

### Reviewing local service templates

The optional JSON import accepts a bounded subset of the `motorcycles` /
`tasks` structure in [Motorcycle Service Database](https://github.com/ramblenride/motorcycle-service-db)
(commit `3d21b582720e18c9f80e254bfdaf3875cf443990`). The model and task must be
explicitly selected; initial mileage/age and task notes are displayed but are
not used in calculations. The **Use recurring intervals** button is an explicit
copy into the worksheet, not vehicle matching. Last service history is never
filled automatically. Intervals over 1,200 months remain visible for review but
cannot be copied. Template links and unsupported fields are ignored; this is not
a complete validator or importer for all schema extensions. Files are limited
to 2 MiB, 100 models and 500 tasks per model.

The upstream data is CC BY-SA 4.0, separate from this application's license.
Five unchanged Honda, KTM, Royal Enfield and Suzuki templates are bundled;
see `web/service-templates/README.md` for attribution, hashes and terms.
The upstream Yamaha file is excluded because its model label and manual reference
conflict. Open-ended year claims and all task details still require confirmation
against the correct manufacturer manual. Imported files and selected templates
are processed locally in the browser session. The upstream repository does not
provide a Moto Guzzi entry.

## Search a local manual text

Under **Tools → Search a local manual text**, open a user-supplied UTF-8 `.txt`
export (up to 5 MiB) and search for a literal, case-insensitive phrase. Results
show the original filename and, when Web Crypto is available, the SHA-256 of the
original bytes, with up to 100 short escaped excerpts. Text form-feed characters
are reported as **text segments**, not trusted PDF page numbers. The input and
excerpts remain in tab memory and can be cleared; the tool makes no manual
upload or storage request. Closing or reloading the tab discards them.

There is **no PDF extraction, OCR, semantic search, RAG, AI answer, manual
index, or bundled workshop manual**. A user must obtain a manual legitimately,
export text independently and check every result and its page/table against
the original for the correct motorcycle. A text conversion can scramble tables
or omit content; zero matches is not proof the information is absent. This is a
simple independently written literal-search tool informed by the cited-source
workflow in [manual-rag-assistant](https://github.com/SRodriguezSpina/manual-rag-assistant)
(commit `972b8c7c2db28aea6018d367489caf14c07f6cc9`), not a port of its Kotlin
server, embeddings, extraction or retrieval code.
