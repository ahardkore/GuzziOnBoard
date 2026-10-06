"""Zeitronix ZT-2 CSV logs -> Innovate LogWorks DIF.

Covers the reference tool ``ZT2CSVToLogWorksDIF_V0.71`` mirrored in
``vendor/guzzidiag/tools/``. Its own description on the archive page it
ships from states the one caveat of that conversion: "the timeline is
incorrect by factor 4, since the ZT-2 logs 4 times more data". This
converter *corrects* that factor instead of passing it on; pass
``timeline_factor=1.0`` to reproduce the reference tool's output exactly.

Formats
-------
Input is the CSV the Zeitronix ZDL logger exports: a header row of channel
names, then one record per sample. Both comma- and semicolon-delimited
exports are accepted (the ZDL era spans German locales), as are comma
decimal separators. Channels are matched case-insensitively
(AFR/Lambda, RPM, TPS, MAP/Boost, EGT, USER1); unrecognised columns pass
through untouched.

Output is a LogWorks DIF file: the spreadsheet-table interchange the manual
describes (tab-separated text, one header row of channel labels, first
column the time axis), readable by LogWorks and by any spreadsheet.
"""
from __future__ import annotations

#: ZT-2 per-input sampling rate from the published product specification
#: ("65 samples per second per input").
DEFAULT_SAMPLE_RATE = 65.0

#: The reference tool documents its own timeline error: the ZT-2 logs four
#: times more data than its nominal timeline accounts for. We correct by
#: this factor by default; 1.0 reproduces the reference tool's output.
DEFAULT_TIMELINE_FACTOR = 4.0

#: Canonical output labels, matched against lowercase header fragments.
_CHANNEL_LABELS = [
    ("afr", "AFR"),
    ("lambda", "Lambda"),
    ("rpm", "RPM"),
    ("tps", "TPS (%)"),
    ("throttle", "TPS (%)"),
    ("map", "MAP"),
    ("boost", "Boost"),
    ("egt", "EGT"),
    ("user", "USER1"),
]


class LogConvertError(ValueError):
    """The input is not a usable ZT-2 CSV log."""


def _canonical(label: str) -> str:
    # A source label that already carries a unit, e.g. "EGT (C)", is kept
    # verbatim; otherwise the fuzzy-matched canonical name wins.
    if "(" in label:
        return label.strip()
    low = label.strip().lower()
    for fragment, canon in _CHANNEL_LABELS:
        if fragment in low:
            return canon
    return label.strip()


def _num(token: str) -> float:
    t = token.strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise LogConvertError(f"not a number: {token!r} in a data row") from None


def convert_z2csv_to_dif(
    text: str,
    *,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    timeline_factor: float = DEFAULT_TIMELINE_FACTOR,
) -> dict:
    """Convert one ZDL-exported ZT-2 CSV document to LogWorks DIF text.

    Returns a dict with the DIF text, the channel labels, row count and the
    timeline parameters used, so a caller can show exactly what happened.
    """
    if sample_rate <= 0:
        raise LogConvertError("sample_rate must be positive")
    if timeline_factor <= 0:
        raise LogConvertError("timeline_factor must be positive")

    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if len(lines) < 2:
        raise LogConvertError("need a header row and at least one data row")

    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    header = [h.strip() for h in lines[0].split(delimiter) if h.strip()]
    if not header:
        raise LogConvertError("the header row has no channel names")
    named = [h.lower() for h in header]
    if not any("afr" in h or "lambda" in h for h in named):
        raise LogConvertError(
            "no AFR/Lambda column in the header - this does not look like a "
            "ZT-2 (ZDL) export"
        )

    channels = [_canonical(h) for h in header]
    has_time = any("time" in h for h in named)

    rows: list[list[float]] = []
    for ln in lines[1:]:
        parts = [p for p in ln.split(delimiter) if p.strip()]
        if len(parts) != len(header):
            raise LogConvertError(
                f"row {len(rows) + 2} has {len(parts)} fields, "
                f"expected {len(header)}"
            )
        rows.append([_num(p) for p in parts])

    # The time axis is rebuilt from the row index, honouring the documented
    # "logs four times more data" over-density: a source Time column (if any)
    # is kept as a data channel, not used as the axis.
    step_s = timeline_factor / sample_rate
    out_lines = ["\t".join(["Time (s)"] + channels)]
    for i, row in enumerate(rows):
        cells = [f"{i * step_s:.3f}"] + [f"{v:g}" for v in row]
        out_lines.append("\t".join(cells))
    dif = "\r\n".join(out_lines) + "\r\n"

    return {
        "dif": dif,
        "channels": channels,
        "rows": len(rows),
        "duration_s": round((len(rows) - 1) * step_s, 3) if rows else 0.0,
        "sample_rate": sample_rate,
        "timeline_factor": timeline_factor,
        "time_column_in_source": has_time,
        "note": (
            "Time axis rebuilt from the row index: row N sits at "
            f"N * {timeline_factor:g}/{sample_rate:g} s (the reference "
            "converter's documented factor-4 timeline error, corrected; "
            "timeline_factor=1.0 reproduces its output). DIF is LogWorks' "
            "spreadsheet-table interchange: tab separated, header row, first "
            "column time."
        ),
    }
