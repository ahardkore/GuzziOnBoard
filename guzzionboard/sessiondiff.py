"""Compare two recorded sessions: what actually changed between them.

Session logs already keep every sample with its raw bytes (the provenance
rule), which makes a second session the cheapest baseline there is: sweep a
bike cold, ride it, sweep it again, and the comparison names the channels
that moved. Same idea as the K-Line discovery sweep's baseline, but across
whole recorded sessions and after the fact.

What is compared:

* **live channels** - first/last/min/max/mean of every sampled key in each
  session, side by side, with the delta of the means (sessions are not
  aligned in time, so means are the honest comparison, not point-by-point);
* **fault codes** - the codes each session saw on its last ``read_dtcs`` and
  which side each code belongs to;
* **session facts** - vehicle, ECU, transport, span, frame and sample counts.

Nothing is guessed: a channel sampled in only one session is reported as
such, not interpolated.
"""
from __future__ import annotations

from pathlib import Path

from .sessionlog import SessionLog


class SessionDiffError(Exception):
    """A session could not be read or compared."""


def _stats(values: list[float]) -> dict:
    return {
        "count": len(values),
        "first": round(values[0], 2),
        "last": round(values[-1], 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "mean": round(sum(values) / len(values), 2),
    }


def summarise(path: str | Path) -> dict:
    """One session distilled: per-channel stats, final DTC set, facts."""
    path = Path(path)
    meta: dict = {}
    samples: dict[str, list[float]] = {}
    units: dict[str, str] = {}
    dtcs: list[dict] = []
    dtc_context: dict = {}
    counts: dict = {}
    span: list[float] = []

    try:
        events = list(SessionLog.read(path))
    except (OSError, ValueError) as exc:
        raise SessionDiffError(f"cannot read {path.name}: {exc}") from exc

    for event in events:
        kind = event.get("kind")
        if kind == "session_start":
            meta = event.get("meta", {})
        elif kind == "session_end":
            counts = event.get("counts", {})
        elif kind == "sample":
            key = event.get("key", "")
            value = event.get("value")
            if key and isinstance(value, (int, float)):
                samples.setdefault(key, []).append(float(value))
                units[key] = event.get("unit", "")
            span.append(float(event.get("t", 0)))
        elif kind == "action" and event.get("name") == "read_dtcs":
            detail = event.get("detail") or {}
            dtcs = detail.get("dtcs", [])
            dtc_context = detail.get("context", {})

    return {
        "name": path.name,
        "meta": meta,
        "channels": {
            key: {**_stats(values), "unit": units.get(key, "")}
            for key, values in samples.items()
        },
        "dtcs": [d.get("code") for d in dtcs if d.get("code")],
        "dtc_context": dtc_context,
        "counts": counts,
        "span_s": round(span[-1] - span[0], 1) if len(span) > 1 else 0.0,
    }


def compare(path_a: str | Path, path_b: str | Path) -> dict:
    """Two sessions side by side, channel by channel."""
    a = summarise(path_a)
    b = summarise(path_b)

    channels = []
    for key in sorted(set(a["channels"]) | set(b["channels"])):
        ca = a["channels"].get(key)
        cb = b["channels"].get(key)
        entry = {
            "key": key,
            "unit": (ca or cb or {}).get("unit", ""),
            "a": ca,
            "b": cb,
            "delta_mean": (
                round(cb["mean"] - ca["mean"], 2)
                if ca and cb else None
            ),
        }
        channels.append(entry)

    codes_a, codes_b = set(a["dtcs"]), set(b["dtcs"])
    return {
        "a": {k: a[k] for k in ("name", "meta", "counts", "span_s")},
        "b": {k: b[k] for k in ("name", "meta", "counts", "span_s")},
        "channels": channels,
        "channels_only_in_a": [
            c["key"] for c in channels if c["a"] and not c["b"]
        ],
        "channels_only_in_b": [
            c["key"] for c in channels if c["b"] and not c["a"]
        ],
        "dtcs": {
            "both": sorted(codes_a & codes_b),
            "only_a": sorted(codes_a - codes_b),
            "only_b": sorted(codes_b - codes_a),
        },
    }
