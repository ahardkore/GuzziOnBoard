"""Turning a K-Line capture into a catalog entry.

Only the IAW 5AM has a characterised identifier table in this project, and it
got one the hard way: somebody put a tap on the K-Line while a tool talked to
a real motorcycle, and the bytes were decoded afterwards. Nothing publishable
exists for the other families - the GuzziDiag and IAWDiag changelogs record
*that* a value was corrected, never which identifier it lives on - so every
other family has to be done the same way.

This module is that second half, automated:

1. :func:`parse` reads a capture in any of the shapes a serial tap produces
   and recovers the KWP2000 frames.
2. :func:`characterise` pairs ``21 <rli>`` requests with their answers and
   reports, per identifier, what came back, how long it was, and whether it
   ever moved.
3. :func:`correlate` takes a CSV log written by the closed tool *during the
   same capture* and solves each named column against the raw identifier
   series, which is how a scaling stops being a guess.
4. :func:`draft_catalog` emits a catalog fragment with honest confidence:
   ``verified-capture`` for an identifier whose scaling was solved,
   ``inferred`` for one that was only seen to exist.

Read-only by construction: this touches files, never hardware.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .protocol.kwp2000 import Service

#: A value has to move by at least this fraction of its range before a column
#: and an identifier are called a match rather than two constants.
MIN_VARIATION = 1e-9

#: Below this correlation a solved scaling is not reported at all.
MIN_FIT = 0.999


class KLineLogError(Exception):
    pass


# ------------------------------------------------------------- parsing

@dataclass
class Frame:
    """One decoded KWP2000 frame from the capture."""

    t: float
    direction: str          # "tx" (tester) | "rx" (ECU) | "?"
    raw: bytes
    payload: bytes = b""
    source: int | None = None
    target: int | None = None

    @property
    def service(self) -> int | None:
        return self.payload[0] if self.payload else None

    def as_dict(self) -> dict:
        return {
            "t": round(self.t, 4), "dir": self.direction,
            "raw": self.raw.hex(" "), "payload": self.payload.hex(" "),
            "source": self.source, "target": self.target,
        }


_HEX_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")
_TIME_RE = re.compile(r"^\s*[\[(]?\s*(\d+(?:\.\d+)?)\s*[\])]?\s*[:,]?\s")
_DIR_RE = re.compile(r"\b(tx|rx|tester|ecu|out|in|->|<-|>|<)\b", re.IGNORECASE)

_DIRECTIONS = {
    "tx": "tx", "tester": "tx", "out": "tx", "->": "tx", ">": "tx",
    "rx": "rx", "ecu": "rx", "in": "rx", "<-": "rx", "<": "rx",
}


def _split_frames(blob: bytes) -> list[bytes]:
    """Cut a continuous byte stream into KWP2000 frames by their headers.

    The physical layer is one wire shared by both directions, so a tap often
    produces an undivided stream. The format byte carries the length, which
    is enough to walk it; a frame whose checksum does not add up is skipped a
    byte at a time rather than guessed at.
    """
    out: list[bytes] = []
    i = 0
    while i < len(blob):
        fmt = blob[i]
        length = fmt & 0x3F
        header = 1
        if fmt & 0x80:
            header = 3                       # FMT TGT SRC
        if length == 0:
            if i + header >= len(blob):
                break
            length = blob[i + header]
            header += 1
        size = header + length + 1           # + checksum
        chunk = blob[i:i + size]
        if len(chunk) == size and (sum(chunk[:-1]) & 0xFF) == chunk[-1]:
            out.append(chunk)
            i += size
        else:
            i += 1
    return out


def _frame_from_bytes(t: float, direction: str, raw: bytes) -> Frame | None:
    if len(raw) < 3:
        return None
    fmt = raw[0]
    length = fmt & 0x3F
    header = 3 if fmt & 0x80 else 1
    source = target = None
    if fmt & 0x80:
        target, source = raw[1], raw[2]
    if length == 0:
        length = raw[header]
        header += 1
    payload = raw[header:header + length]
    if not payload:
        return None
    if direction == "?":
        # The tester is 0xF1 and the ECU is 0x10 in every capture of these
        # bikes; fall back to that rather than leaving it unknown.
        if source == 0xF1 or target == 0x10:
            direction = "tx"
        elif source == 0x10 or target == 0xF1:
            direction = "rx"
    return Frame(t=t, direction=direction, raw=raw, payload=payload,
                 source=source, target=target)


def parse(text: str) -> list[Frame]:
    """Parse a capture.

    Understood shapes, in order of preference:

    * **GuzziOnBoard session JSONL** - lines with ``"kind": "frame"``.
    * **Annotated hex lines** - an optional timestamp, an optional direction
      marker (``tx``/``rx``/``->``/``<-``), then hex bytes. One frame a line.
    * **A raw hex dump** - any amount of hex with no structure, split back
      into frames by the header length and the checksum.
    """
    if not text or not text.strip():
        raise KLineLogError("the capture is empty")

    frames = _parse_jsonl(text)
    if frames:
        return frames
    frames = _parse_lines(text)
    if frames:
        return frames
    frames = _parse_blob(text)
    if frames:
        return frames
    raise KLineLogError(
        "no KWP2000 frames found: expected session JSONL, hex lines, or a "
        "hex dump of the K-Line"
    )


def _parse_jsonl(text: str) -> list[Frame]:
    out: list[Frame] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("kind") != "frame":
            continue
        raw = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", event.get("hex", "")))
        frame = _frame_from_bytes(
            float(event.get("t", 0.0)),
            _DIRECTIONS.get(str(event.get("dir", "")).lower(), "?"),
            raw,
        )
        if frame:
            out.append(frame)
    return out


def _parse_lines(text: str) -> list[Frame]:
    out: list[Frame] = []
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t_match = _TIME_RE.match(line)
        t = float(t_match.group(1)) if t_match else float(index)
        rest = line[t_match.end():] if t_match else line

        direction = "?"
        d_match = _DIR_RE.search(rest)
        if d_match:
            direction = _DIRECTIONS.get(d_match.group(1).lower(), "?")
            rest = rest[:d_match.start()] + rest[d_match.end():]

        hex_bytes = _HEX_RE.findall(rest)
        if len(hex_bytes) < 3:
            continue
        blob = bytes.fromhex("".join(hex_bytes))
        chunks = _split_frames(blob)
        if len(chunks) != 1 or len(chunks[0]) != len(blob):
            # Either the checksum does not add up or the line holds more than
            # one frame; a line-oriented reading would be a guess, so let the
            # stream reader have it.
            return []
        frame = _frame_from_bytes(t, direction, chunks[0])
        if frame:
            out.append(frame)
    return out


def _parse_blob(text: str) -> list[Frame]:
    digits = re.sub(r"[^0-9A-Fa-f]", "", text)
    if len(digits) < 6:
        return []
    blob = bytes.fromhex(digits[:len(digits) - len(digits) % 2])
    return [f for f in (
        _frame_from_bytes(float(i), "?", raw)
        for i, raw in enumerate(_split_frames(blob))
    ) if f]


# ------------------------------------------------------ characterisation

@dataclass
class Observation:
    """Everything one local identifier did during the capture."""

    local_id: int
    answers: int = 0
    refusals: int = 0
    nrcs: set = field(default_factory=set)
    lengths: set = field(default_factory=set)
    raws: list = field(default_factory=list)
    times: list = field(default_factory=list)

    @property
    def length(self) -> int | None:
        return max(self.lengths) if self.lengths else None

    def ints(self, signed: bool = False) -> list[int]:
        return [int.from_bytes(r, "big", signed=signed) for r in self.raws]

    @property
    def moved(self) -> bool:
        return len(set(self.raws)) > 1

    @property
    def always_zero(self) -> bool:
        return bool(self.raws) and all(not any(r) for r in self.raws)

    def as_dict(self) -> dict:
        values = self.ints()
        return {
            "local_id": self.local_id,
            "hex": f"0x{self.local_id:02X}",
            "answers": self.answers,
            "refusals": self.refusals,
            "nrcs": sorted(f"0x{n:02X}" for n in self.nrcs),
            "length": self.length,
            "moved": self.moved,
            "always_zero": self.always_zero,
            "distinct": len(set(self.raws)),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "first_raw": self.raws[0].hex(" ") if self.raws else "",
            "samples": len(self.raws),
        }


def characterise(frames) -> dict:
    """Pair ``21 <rli>`` with its answer and report what each identifier did.

    Only read requests are interpreted. Everything else in the capture is
    counted and listed, because a capture of a closed tool is also the only
    public record of which *services* that tool uses on that family.
    """
    frames = list(frames)
    observations: dict[int, Observation] = {}
    services: dict[int, int] = {}
    identification: list[dict] = []
    pending: dict | None = None

    for frame in frames:
        service = frame.service
        if service is None:
            continue
        if frame.direction == "tx":
            services[service] = services.get(service, 0) + 1
            if service == Service.READ_DATA_BY_LOCAL_ID and len(frame.payload) >= 2:
                pending = {"rli": frame.payload[1], "t": frame.t}
            else:
                pending = None
            continue

        # Responses.
        if service == 0x7F and len(frame.payload) >= 3:
            rejected, nrc = frame.payload[1], frame.payload[2]
            if rejected == Service.READ_DATA_BY_LOCAL_ID and pending:
                obs = observations.setdefault(
                    pending["rli"], Observation(pending["rli"]))
                obs.refusals += 1
                obs.nrcs.add(nrc)
            pending = None
            continue

        if service == 0x5A and len(frame.payload) >= 2:
            identification.append({
                "option": frame.payload[1],
                "ascii": _printable(frame.payload[2:]),
                "raw": frame.payload[2:].hex(" "),
            })

        if service == 0x61 and len(frame.payload) >= 2:
            rli = frame.payload[1]
            data = frame.payload[2:]
            obs = observations.setdefault(rli, Observation(rli))
            obs.answers += 1
            obs.lengths.add(len(data))
            obs.raws.append(data)
            obs.times.append(frame.t)
        pending = None

    answered = [o for o in observations.values() if o.answers]
    live = [o for o in answered if o.moved]
    dead = [o for o in answered if o.always_zero]

    return {
        "frames": len(frames),
        "identifiers": [o.as_dict() for o in sorted(observations.values(),
                                                    key=lambda o: o.local_id)],
        "observations": observations,
        "services_seen": [
            {"service": f"0x{s:02X}", "name": _service_name(s), "count": c}
            for s, c in sorted(services.items())
        ],
        "identification": identification,
        "summary": {
            "answered": len(answered),
            "moved": len(live),
            "always_zero": len(dead),
            "refused": len([o for o in observations.values() if not o.answers]),
        },
        "note": (
            "Seen on the wire. An identifier that answered is real; what it "
            "means is only known once a scaling is solved against a reference "
            "log."
        ),
    }


def _service_name(service: int) -> str:
    try:
        return Service(service).name
    except ValueError:
        return "unknown"


def _printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


# ------------------------------------------------------ scaling solver

def _fit(raw_values: list[float], shown: list[float]) -> dict | None:
    """Least-squares ``shown = scale * raw + bias`` with a quality figure."""
    n = len(raw_values)
    if n < 4:
        return None
    if len(set(raw_values)) < 2 or len(set(shown)) < 2:
        return None
    mean_x = statistics.fmean(raw_values)
    mean_y = statistics.fmean(shown)
    sxx = sum((x - mean_x) ** 2 for x in raw_values)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(raw_values, shown))
    syy = sum((y - mean_y) ** 2 for y in shown)
    if sxx <= MIN_VARIATION or syy <= MIN_VARIATION:
        return None
    scale = sxy / sxx
    bias = mean_y - scale * mean_x
    fit = (sxy * sxy) / (sxx * syy)           # r^2
    return {"scale": scale, "bias": bias, "fit": fit, "points": n}


_NICE = (1.0, 0.5, 0.1, 0.01, 0.001, 2.0, 10.0, 100.0, 1000.0, 1 / 256, 1 / 1024)


def _is_nice(value: float) -> bool:
    return any(abs(value - c) < abs(c) * 0.01 for c in _NICE)


def _nice(value: float) -> float:
    """Round a solved coefficient to something a catalog would actually use."""
    for candidate in (1.0, 0.5, 0.1, 0.01, 0.001, 2.0, 10.0, 100.0, 1000.0,
                      1 / 256, 1 / 1024):
        if abs(value - candidate) < abs(candidate) * 0.01:
            return candidate
    return round(value, 6)


def read_reference_csv(text: str) -> dict:
    """Read a CSV log written by the closed tool: ``time, name, name, ...``."""
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 3:
        raise KLineLogError("the reference CSV needs a header and some rows")
    header = [h.strip() for h in rows[0]]

    columns: dict[str, list] = {name: [] for name in header[1:]}
    times: list[float] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        try:
            times.append(float(row[0]))
        except ValueError:
            continue                      # a units row, or a stray line
        for name, cell in zip(header[1:], row[1:]):
            try:
                columns[name].append(float(cell))
            except ValueError:
                columns[name].append(None)
    return {"times": times, "columns": columns}


def correlate(observations: dict, reference: dict, min_fit: float = MIN_FIT) -> list[dict]:
    """Match each named reference column to the identifier that produced it.

    Both series are sampled on their own clock, so they are paired by nearest
    timestamp. A match is only reported when the straight line through the
    points is essentially perfect - these are integer sensor readings put
    through a fixed scaling, so a real match fits almost exactly, and anything
    that does not is a coincidence worth refusing.
    """
    candidates = []
    ref_times = reference["times"]
    if not ref_times:
        return []

    for name, shown in reference["columns"].items():
        for rli, obs in observations.items():
            if not obs.moved or len(obs.raws) < 4:
                continue
            for signed in (False, True):
                raw_series = obs.ints(signed=signed)
                pairs = _pair_by_time(obs.times, raw_series, ref_times, shown)
                if len(pairs) < 4:
                    continue
                fit = _fit([p[0] for p in pairs], [p[1] for p in pairs])
                if fit is None or fit["fit"] < min_fit:
                    continue
                scale, bias = _nice(fit["scale"]), _nice(fit["bias"])
                candidates.append({
                    "channel": name, "local_id": rli, "hex": f"0x{rli:02X}",
                    "signed": signed, "length": obs.length,
                    "scale": scale, "bias": bias,
                    "fit": round(fit["fit"], 6), "points": fit["points"],
                    # Two channels can both fit the same identifier perfectly
                    # when a capture is short and everything moves together.
                    # A scaling a catalog would actually write down - a round
                    # factor and a small offset - is the better reading.
                    "_rank": (round(fit["fit"], 6), _is_nice(fit["scale"]),
                              -abs(bias)),
                })

    out, used_channels, used_ids = [], set(), set()
    for match in sorted(candidates, key=lambda m: m["_rank"], reverse=True):
        if match["channel"] in used_channels or match["local_id"] in used_ids:
            continue
        used_channels.add(match["channel"])
        used_ids.add(match["local_id"])
        out.append({k: v for k, v in match.items() if k != "_rank"})
    return sorted(out, key=lambda m: m["local_id"])


def _pair_by_time(raw_times, raw_values, ref_times, ref_values, tolerance=1.0):
    """Nearest-timestamp pairing of two independently sampled series."""
    pairs = []
    if not raw_times:
        return pairs
    # Normalise both clocks to start at zero: a tap and a tool rarely agree
    # on the epoch, but they do agree on elapsed time.
    t0_raw, t0_ref = raw_times[0], ref_times[0]
    for t, value in zip(ref_times, ref_values):
        if value is None:
            continue
        target = t - t0_ref
        best_i, best_d = None, None
        for i, rt in enumerate(raw_times):
            d = abs((rt - t0_raw) - target)
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        if best_i is not None and best_d is not None and best_d <= tolerance:
            pairs.append((raw_values[best_i], value))
    return pairs


# -------------------------------------------------------- catalog draft

def draft_catalog(result: dict, matches=None, family: str = "unknown") -> dict:
    """A catalog fragment from a capture, with the confidence it has earned."""
    matches = {m["local_id"]: m for m in (matches or [])}
    parameters = []
    for entry in result["identifiers"]:
        if not entry["answers"]:
            continue
        rli = entry["local_id"]
        match = matches.get(rli)
        if match:
            parameters.append({
                "key": _slug(match["channel"]),
                "name": match["channel"],
                "local_id": rli,
                "length": entry["length"],
                "signed": match["signed"],
                "scale": match["scale"],
                "bias": match["bias"],
                "digits": 1,
                "group": "engine",
                "confidence": "verified-capture",
                "source_note": (
                    f"solved against a reference log, r^2 {match['fit']} "
                    f"over {match['points']} points"
                ),
            })
        elif entry["always_zero"]:
            parameters.append({
                "key": f"dead_{rli:02x}", "name": f"Unused 0x{rli:02X}",
                "local_id": rli, "length": entry["length"], "dead": True,
                "confidence": "verified-capture",
                "source_note": "answered, always zero across the capture",
            })
        else:
            parameters.append({
                "key": f"unknown_{rli:02x}",
                "name": f"Unidentified 0x{rli:02X}",
                "local_id": rli, "length": entry["length"],
                "group": "diagnostic", "confidence": "unknown",
                "source_note": (
                    "answered and varied, meaning not established - needs a "
                    "reference log to solve"
                    if entry["moved"] else
                    "answered but never moved during this capture"
                ),
            })
    return {
        "family": family,
        "parameters": parameters,
        "services_seen": result["services_seen"],
        "identification": result["identification"],
        "note": (
            "A draft, not a catalog entry. Channels solved against a "
            "reference log are 'verified-capture'; everything else stays "
            "'unknown' until somebody does the work."
        ),
    }


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "channel"


# ------------------------------------------------------------- top level

def analyze(capture_text: str, reference_csv: str | None = None,
            family: str = "unknown") -> dict:
    """Characterise a capture, optionally solving scalings against a log."""
    frames = parse(capture_text)
    result = characterise(frames)
    matches = []
    if reference_csv:
        reference = read_reference_csv(reference_csv)
        matches = correlate(result["observations"], reference)
    draft = draft_catalog(result, matches, family=family)
    public = {k: v for k, v in result.items() if k != "observations"}
    public["matches"] = matches
    public["draft"] = draft
    return public


def analyze_file(path: str | Path, reference_path: str | Path | None = None,
                 family: str = "unknown") -> dict:
    capture = Path(path)
    if not capture.is_file():
        raise KLineLogError(f"no such capture: {path}")
    reference = None
    if reference_path:
        reference_file = Path(reference_path)
        if not reference_file.is_file():
            raise KLineLogError(f"no such reference log: {reference_path}")
        reference = reference_file.read_text(encoding="utf-8", errors="replace")
    return analyze(
        capture.read_text(encoding="utf-8", errors="replace"), reference, family
    )
