"""Turning a recorded session back into data you can look at.

A session file is a newline-delimited log of frames, samples, decisions and
actions. Two things are wanted from it afterwards:

* **CSV**, because the moment somebody wants to plot a channel against time
  they want it in a spreadsheet, and because a CSV with the raw bytes in it is
  still provenance;
* **replay**, so a session can be scrubbed through after the fact - with the
  derived channels and the plausibility checks recomputed at each point, the
  same way they would have appeared live.

Samples are grouped into *sweeps*: one pass of the polling loop. The grouping
is purely by timestamp gap, because that is all the log records.
"""
from __future__ import annotations

import csv
import io

from .derived import Analyzer

#: Samples closer together than this are considered one polling sweep.
SWEEP_GAP_S = 0.35


def sweeps(events, gap: float = SWEEP_GAP_S) -> list[dict]:
    """Group ``sample`` events into polling sweeps, oldest first."""
    out: list[dict] = []
    current: dict | None = None
    for event in events:
        if event.get("kind") != "sample":
            continue
        t = float(event.get("t", 0.0))
        if current is None or t - current["t_last"] > gap or event["key"] in current["values"]:
            current = {"t": t, "t_last": t, "values": {}}
            out.append(current)
        current["t_last"] = t
        current["values"][event["key"]] = {
            "key": event["key"],
            "value": event.get("value"),
            "unit": event.get("unit", ""),
            "raw": event.get("raw", ""),
            # The session log writes "lid"; older files and the in-memory
            # ring use "local_id".
            "local_id": event.get("local_id", event.get("lid")),
        }
    for sweep in out:
        sweep.pop("t_last", None)
    return out


def channels(sweep_list) -> list[str]:
    """Every channel that appears, in first-seen order."""
    seen: list[str] = []
    for sweep in sweep_list:
        for key in sweep["values"]:
            if key not in seen:
                seen.append(key)
    return seen


def to_csv(events, include_raw: bool = True) -> str:
    """One row per sweep, one column per channel (plus its raw bytes).

    The first row is the header, the second carries the units, so the file
    says what its numbers mean without a separate legend.
    """
    sweep_list = sweeps(events)
    keys = channels(sweep_list)
    units = {}
    for sweep in sweep_list:
        for key, entry in sweep["values"].items():
            units.setdefault(key, entry.get("unit", ""))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    header = ["time_unix", "elapsed_s"] + keys
    unit_row = ["", "s"] + [units.get(k, "") for k in keys]
    if include_raw:
        header += [f"{k}_raw" for k in keys]
        unit_row += ["bytes"] * len(keys)
    writer.writerow(header)
    writer.writerow(unit_row)

    t0 = sweep_list[0]["t"] if sweep_list else 0.0
    for sweep in sweep_list:
        row = [f"{sweep['t']:.4f}", f"{sweep['t'] - t0:.3f}"]
        row += [sweep["values"].get(k, {}).get("value", "") for k in keys]
        if include_raw:
            row += [sweep["values"].get(k, {}).get("raw", "") for k in keys]
        writer.writerow(row)
    return buffer.getvalue()


def frames(events, profile=None) -> dict:
    """Replayable snapshots, with derived values and findings recomputed.

    The analyzer is fed the *recorded* timestamps rather than wall-clock
    time, so its sixty-second window means the same thing on replay as it did
    live.
    """
    sweep_list = sweeps(events)
    analyzer = Analyzer(profile)
    t0 = sweep_list[0]["t"] if sweep_list else 0.0

    out = []
    for sweep in sweep_list:
        samples = [
            {"key": entry["key"], "name": entry["key"],
             "local_id": entry.get("local_id") or 0,
             "raw": entry.get("raw", ""), "value": entry.get("value"),
             "unit": entry.get("unit", ""), "text": "", "error": ""}
            for entry in sweep["values"].values()
        ]
        analysis = analyzer.update(samples, at=sweep["t"])
        out.append({
            "t": round(sweep["t"], 4),
            "elapsed": round(sweep["t"] - t0, 3),
            "values": sweep["values"],
            "derived": analysis["derived"],
            "findings": analysis["findings"],
        })

    return {
        "frames": out,
        "channels": channels(sweep_list),
        "duration_s": round(out[-1]["elapsed"], 3) if out else 0.0,
        "note": (
            "Replayed from the recorded samples. Derived values and findings "
            "are recomputed now, from the bytes that were recorded then."
        ),
    }
