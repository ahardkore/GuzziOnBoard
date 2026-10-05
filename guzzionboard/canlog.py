"""Passive CAN capture analysis: find the diagnostic id pair in a log.

The CAN-era Guzzi ECUs (MIU G4, Marelli 11MP) wrap KWP2000/UDS payloads in
ISO-TP over CAN, and the request/response identifiers are the one thing this
project has never been able to confirm without a bike (PRIOR_ART §7 item 2).
The capture method is settled, though: passively log the bus while a
GuzziCanDiag laptop talks to the bike, then look for the pair that behaves
like diagnostics.

This module reads the three capture formats that matter and finds that pair:

* **candump** (socketcan): ``(1700000000.123456) can0 7E0#023E00AAAAAAAAAA``
  and the verbose ``7E0  [8]  02 3E 00 ...`` layout;
* **SavvyCAN native CSV** (GVRET), both headers - the legacy
  ``Time Stamp,ID,Extended,Bus,LEN,D1..D8`` and the current V2 with a ``Dir``
  column. Timestamps are microseconds, ids hexadecimal;
* **CRTD** (busware/TI): ``1320745424.002 R11 402 FA 01 ...``.

What counts as evidence, strongest first:

1. **ISO-TP flow control answers a first frame.** Whoever sends a flow
   control (PCI 0x3) is the receiver of a multi-frame message, so an FC on
   id B answering a first frame (PCI 0x1) on id A is a directed edge between
   exactly two ids - no bus knowledge required.
2. **Diagnostic service ids.** A payload that starts with a known request
   SID (0x10 session, 0x1A read id, 0x27 security access, 0x3E tester
   present...) marks a sender as the tester; a response SID (request + 0x40)
   or a negative response (0x7F) marks the ECU.
3. **Periodic tester present** and a constant padding byte - confirmation,
   never proof on their own.

The result is a ranked list of candidate pairs with the evidence attached,
so a human can check the reasoning, plus a note comparing each pair against
the standard ISO 15765-4 pairs this workstation assumes by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: The pairs the workstation assumes until a capture says otherwise.
STANDARD_PAIRS = {
    (0x7E0, 0x7E8): "the 11-bit ISO 15765-4 pair this workstation assumes",
    (0x18DA10F1, 0x18DAF110): "the 29-bit ISO 15765-4 pair",
}
FUNCTIONAL_ID = 0x7DF

#: Known KWP2000 + UDS service ids, request side (responses are +0x40).
SID_NAMES = {
    0x10: "start diagnostic session",
    0x11: "ECU reset",
    0x14: "clear diagnostic information",
    0x18: "read DTC by status",
    0x19: "read DTC information",
    0x1A: "read ECU identification",
    0x21: "read data by local identifier",
    0x22: "read data by identifier",
    0x23: "read memory by address",
    0x27: "security access",
    0x28: "communication control",
    0x2C: "dynamically define identifier",
    0x2E: "write data by identifier",
    0x2F: "input/output control by identifier",
    0x30: "input/output control (KWP)",
    0x31: "routine control",
    0x34: "request download",
    0x35: "request upload",
    0x36: "transfer data",
    0x37: "request transfer exit",
    0x3B: "write data by local identifier",
    0x3D: "write memory by address",
    0x3E: "tester present",
    0x83: "access timing parameter",
    0x84: "secured data transmission",
    0x85: "control DTC setting",
    0x86: "response on event",
    0x87: "link control",
}


class CanLogError(Exception):
    """A capture could not be read or understood."""


@dataclass(frozen=True)
class CanFrame:
    timestamp: float        # seconds; 0.0 when the log has no clock
    id: int
    extended: bool
    data: bytes
    direction: str = ""     # "" unknown | "Rx"/"Tx" | "R"/"T"

    @property
    def pci(self) -> str:
        """ISO-TP frame type from the first byte."""
        if not self.data:
            return "empty"
        nibble = self.data[0] >> 4
        return {0: "sf", 1: "ff", 2: "cf", 3: "fc"}.get(nibble, "other")

    def payload_sid(self) -> int | None:
        """The first service id byte of the ISO-TP payload, if visible."""
        if not self.data:
            return None
        if self.pci == "sf":
            length = self.data[0] & 0x0F
            if 1 <= length and 1 + length <= len(self.data):
                return self.data[1]
            return self.data[1] if len(self.data) > 1 else None
        if self.pci == "ff":
            return self.data[2] if len(self.data) > 2 else None
        return None


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_HEX = set("0123456789abcdefABCDEF")


def _hex_id(token: str) -> int | None:
    token = token.strip().lower().removeprefix("0x")
    if not token or any(c not in _HEX for c in token):
        return None
    try:
        return int(token, 16)
    except ValueError:  # pragma: no cover - guarded above
        return None


def _dec_id(token: str) -> int | None:
    try:
        return int(token.strip(), 10)
    except ValueError:
        return None


def _parse_timestamp(token: str) -> float | None:
    """candump ``(1699999999.123456)`` or ``(0:00:12.345678)``; CSV handled
    separately because its clock is microseconds."""
    token = token.strip().strip("()")
    if not token:
        return None
    if ":" in token:                      # candump -tz relative clock
        parts = token.split(":")
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except (ValueError, IndexError):
            return None
    try:
        return float(token)
    except ValueError:
        return None


def _parse_candump_line(line: str, index: int) -> CanFrame | None:
    #   (ts) ifname ID#DATA      |    ifname ID#DATA      |    ID#DATA
    #   (ts) ifname ID  [8] B B B ...   (verbose console output)
    tokens = line.split()
    if not tokens:
        return None
    timestamp = 0.0
    if tokens[0].startswith("(") and "#" not in tokens[0]:
        stamp = _parse_timestamp(tokens.pop(0))
        if stamp is None:
            return None
        timestamp = stamp

    # drop the interface name: a token without # and without brackets
    if tokens and "#" not in tokens[0] and not tokens[0].startswith("["):
        if _hex_id(tokens[0]) is not None or tokens[0].rstrip("0123456789") == "can":
            tokens.pop(0)
    if not tokens:
        return None

    head = tokens[0]
    if "#" in head:                       # compact: ID#DATA (or ID##DATA for FD)
        ident_hex, _, data_part = head.partition("#")
        ident = _hex_id(ident_hex)
        if ident is None:
            return None
        if data_part.startswith("#"):     # CAN-FD: not diagnostics-shaped
            return None
        if data_part.upper().startswith("R"):
            data = b""                    # remote frame
        else:
            data = bytes.fromhex(data_part) if data_part else b""
        return CanFrame(timestamp, ident, ident > 0x7FF, data)

    # verbose: ID [n] B1 B2 ...
    ident = _hex_id(head)
    if ident is None or len(tokens) < 2:
        return None
    rest = tokens[1:]
    if rest[0].startswith("["):
        rest = rest[1:]
    if not rest:
        return None
    data = bytes.fromhex("".join(t for t in rest if _hex_id(t) is not None))
    return CanFrame(timestamp, ident, ident > 0x7FF, data)


def _parse_crtd_line(line: str, index: int) -> CanFrame | None:
    #   1320745424.002 R11 402 FA 01 C3 A0 96 00 07 01
    tokens = line.split()
    if len(tokens) < 3:
        return None
    stamp = None
    if tokens[0][0].isdigit() or tokens[0][0] in ".-":
        stamp = _parse_timestamp(tokens[0])
        tokens = tokens[1:]
    if len(tokens) < 2:
        return None
    kind = tokens[0].upper()
    if kind not in ("R11", "R29", "T11", "T29", "R", "T"):
        return None
    extended = "29" in kind
    direction = "Tx" if kind.startswith("T") else "Rx"
    ident = _hex_id(tokens[1])
    if ident is None:
        return None
    data = bytes.fromhex("".join(t for t in tokens[2:] if _hex_id(t) is not None))
    return CanFrame(stamp or 0.0, ident, extended, data[:8], direction)


def _parse_savvycan_csv(text_lines: list[str]) -> list[CanFrame]:
    """SavvyCAN native (GVRET) CSV, both the V1 and V2 headers."""
    header = [c.strip().lower() for c in text_lines[0].split(",")]
    if "id" not in header or "time stamp" not in header:
        raise CanLogError("CSV header has neither 'Time Stamp' nor 'ID' columns")
    col = {name: i for i, name in enumerate(header)}
    id_col = col["id"]
    ext_col = col.get("extended")
    dir_col = col.get("dir")
    len_col = col.get("len")
    data_cols = [col[f"d{n}"] for n in range(1, 9) if f"d{n}" in col]

    # SavvyCAN writes ids in hex; be honest about files that are not.
    id_tokens = []
    for line in text_lines[1:]:
        cells = line.split(",")
        if len(cells) > id_col:
            token = cells[id_col].strip()
            if token:
                id_tokens.append(token)
    has_hex_letters = any(any(c in "abcdefABCDEF" for c in t) for t in id_tokens)

    frames: list[CanFrame] = []
    for line in text_lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        if len(cells) <= id_col or not cells[id_col]:
            continue
        raw_id = cells[id_col]
        ident = _hex_id(raw_id) if has_hex_letters else _dec_id(raw_id)
        if ident is None:
            ident = _hex_id(raw_id)
        if ident is None:
            raise CanLogError(f"bad id column value {raw_id!r}")
        stamp = 0.0
        if "time stamp" in col and len(cells) > col["time stamp"]:
            try:
                stamp = float(cells[col["time stamp"]]) / 1_000_000.0
            except ValueError:
                stamp = 0.0
        extended = bool(ident > 0x7FF)
        if ext_col is not None and len(cells) > ext_col and cells[ext_col]:
            extended = cells[ext_col] in ("1", "true", "True", "TRUE")
        direction = cells[dir_col] if dir_col is not None and len(cells) > dir_col else ""
        length = None
        if len_col is not None and len(cells) > len_col and cells[len_col]:
            try:
                length = int(cells[len_col])
            except ValueError:
                length = None
        data = bytearray()
        for i, c in enumerate(data_cols):
            if len(cells) <= c or not cells[c]:
                continue
            if length is not None and i >= length:
                break
            try:
                data.append(int(cells[c], 16))
            except ValueError:
                raise CanLogError(f"bad data byte {cells[c]!r}") from None
        frames.append(CanFrame(stamp, ident, extended, bytes(data), direction))
    return frames


def parse_capture(text: str) -> tuple[list[CanFrame], str, list[str]]:
    """Read a capture in any supported format.

    Returns ``(frames, format_name, warnings)``.
    """
    if not text or not text.strip():
        raise CanLogError("the capture is empty")

    lines = text.splitlines()
    warnings: list[str] = []
    first_meaningful = next((l for l in lines if l.strip()), "")

    if first_meaningful.lstrip().startswith(("Time Stamp", "time stamp")) and "," in first_meaningful:
        frames = _parse_savvycan_csv(
            [l for l in lines if l.strip()]
        )
        if not frames:
            raise CanLogError("the CSV has a header but no frames")
        return frames, "savvycan-csv", []

    fmt = "candump"
    frames: list[CanFrame] = []
    skipped = 0
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith(("#", "//", "$", ";", "I ")):
            continue
        frame = _parse_candump_line(line, i)
        if frame is None:
            frame = _parse_crtd_line(line, i)
            if frame is not None:
                fmt = "crtd"
        if frame is None:
            crtd = _parse_crtd_line(line, i)
            if crtd is not None:
                frames.append(crtd)
                fmt = "crtd"
                continue
            skipped += 1
            continue
        frames.append(frame)
    if skipped and frames:
        warnings.append(
            f"{skipped} line(s) did not look like frames and were skipped"
        )
    if not frames:
        raise CanLogError(
            "no frames recognised - expected candump, SavvyCAN CSV or CRTD"
        )
    return frames, fmt, warnings


def parse_capture_file(path: str | Path) -> tuple[list[CanFrame], str, list[str]]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CanLogError(f"cannot read {path}: {exc}") from exc
    return parse_capture(text)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _classify_payload(frame: CanFrame) -> str:
    """request | response | negative | '' for nothing diagnostic-looking."""
    sid = frame.payload_sid()
    if sid is None:
        return ""
    if sid == 0x7F:
        return "negative"
    if sid in SID_NAMES:
        return "request"
    if sid - 0x40 in SID_NAMES:
        return "response"
    return ""


@dataclass
class _Traffic:
    frames: int = 0
    requests: int = 0
    responses: int = 0
    negatives: int = 0
    first_frames: list[float] = field(default_factory=list)
    flow_controls: list[float] = field(default_factory=list)
    tester_presents: list[float] = field(default_factory=list)
    padding: dict[int, int] = field(default_factory=dict)


def analyze_frames(frames: list[CanFrame]) -> dict:
    """Rank the id pairs that behave like a tester and its ECU."""
    if not frames:
        raise CanLogError("no frames to analyse")

    stamps = [f.timestamp for f in frames]
    span = (max(stamps) - min(stamps)) if len(set(stamps)) > 1 else 0.0
    by_id: dict[int, _Traffic] = {}
    for frame in frames:
        traffic = by_id.setdefault(frame.id, _Traffic())
        traffic.frames += 1
        kind = _classify_payload(frame)
        if kind == "request":
            traffic.requests += 1
        elif kind == "response":
            traffic.responses += 1
        elif kind == "negative":
            traffic.negatives += 1
        if frame.pci == "ff":
            traffic.first_frames.append(frame.timestamp)
        elif frame.pci == "fc":
            traffic.flow_controls.append(frame.timestamp)
        sid = frame.payload_sid()
        if frame.pci == "sf" and sid == 0x3E:
            traffic.tester_presents.append(frame.timestamp)
        if len(frame.data) == 8:
            filler = frame.data[-1]
            traffic.padding[filler] = traffic.padding.get(filler, 0) + 1

    # Directed edges: a flow control answers the *nearest preceding* first
    # frame from another id (that is how the protocol works - the FC is a
    # direct reply). Loose windowing would happily pair an FC with unrelated
    # bus chatter that happens to start with 0x1X.
    ff_events = sorted(
        (f.timestamp, f.id) for f in frames if f.pci == "ff"
    )
    edges: dict[tuple[int, int], int] = {}      # (sender_of_ff, sender_of_fc)
    fc_times_by_id: dict[int, list[float]] = {
        ident: t.flow_controls for ident, t in by_id.items() if t.flow_controls
    }
    import bisect

    for fc_id, fc_times in fc_times_by_id.items():
        for fc_time in fc_times:
            pos = bisect.bisect_right(ff_events, (fc_time, 1 << 62)) - 1
            while pos >= 0 and fc_time - ff_events[pos][0] <= 0.1:
                ff_time, ff_id = ff_events[pos]
                if ff_id != fc_id:
                    edges[(ff_id, fc_id)] = edges.get((ff_id, fc_id), 0) + 1
                    break                       # nearest match wins
                pos -= 1

    # A first frame nobody answered with a flow control is (probably) not
    # ISO-TP at all - bus noise that happens to start with 0x1X.
    answered_ff = {ident: 0 for ident in by_id}
    for (ff_id, _), count in edges.items():
        answered_ff[ff_id] += count

    # Candidate tester ids must look like a tester at all.
    candidates = [
        ident for ident, t in by_id.items()
        if t.requests or t.tester_presents
        or any(a == ident for (a, _) in edges)
    ]
    pairs: list[dict] = []
    for tester_id in candidates:
        tester = by_id[tester_id]
        for ecu_id, ecu in by_id.items():
            if ecu_id == tester_id:
                continue
            ff_to_ecu = edges.get((tester_id, ecu_id), 0)   # tester sends, ecu FC
            fc_to_tester = edges.get((ecu_id, tester_id), 0)  # ecu sends, tester FC
            if not (tester.requests or ff_to_ecu or tester.tester_presents):
                continue
            if not (ecu.responses or ecu.negatives or fc_to_tester
                    or answered_ff.get(ecu_id)):
                continue

            evidence = {
                "request_frames": tester.requests,
                "response_frames": ecu.responses + ecu.negatives,
                "multi_frame_to_ecu": ff_to_ecu,
                "multi_frame_from_ecu": fc_to_tester,
                "ecu_first_frames": len(ecu.first_frames),
                "ecu_answered_first_frames": answered_ff.get(ecu_id, 0),
            }
            score = (
                3 * min(evidence["request_frames"], 5)
                + 3 * min(evidence["response_frames"], 5)
                + 5 * min(ff_to_ecu, 2)
                + 5 * min(fc_to_tester, 2)
                + 4 * (len(tester.tester_presents) >= 3)
                + 2 * min(evidence["ecu_answered_first_frames"], 3)
            )
            if score < 4:
                continue

            # tester-present cadence, when the log has a clock
            interval = None
            if len(tester.tester_presents) >= 3 and span:
                times = sorted(tester.tester_presents)
                deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
                if deltas:
                    deltas.sort()
                    interval = round(deltas[len(deltas) // 2], 3)

            padding = None
            counts = tester.padding
            if counts:
                byte, hits = max(counts.items(), key=lambda kv: kv[1])
                if hits >= 3 and hits >= 0.5 * tester.frames:
                    padding = f"0x{byte:02X}"

            extended = any(
                f.extended for f in frames if f.id in (tester_id, ecu_id)
            )
            request_sids = sorted({
                f"0x{f.payload_sid():02X} {SID_NAMES[f.payload_sid()]}"
                for f in frames
                if f.id == tester_id and _classify_payload(f) == "request"
            })
            response_sids = sorted({
                f"0x{f.payload_sid() - 0x40:02X} "
                f"{SID_NAMES[f.payload_sid() - 0x40]}"
                for f in frames
                if f.id == ecu_id and _classify_payload(f) == "response"
            })

            strong = (ff_to_ecu or fc_to_tester) and (
                evidence["request_frames"] or evidence["response_frames"]
            )
            confidence = "strong" if strong else (
                "likely" if evidence["request_frames"]
                and evidence["response_frames"] else "weak"
            )

            pairs.append({
                "request_id": f"0x{tester_id:X}",
                "response_id": f"0x{ecu_id:X}",
                "request_id_value": tester_id,
                "response_id_value": ecu_id,
                "extended": extended,
                "score": score,
                "confidence": confidence,
                "evidence": evidence,
                "request_sids": request_sids[:8],
                "response_sids": response_sids[:8],
                "tester_present_interval_s": interval,
                "padding_byte": padding,
                "frames_on_request_id": tester.frames,
                "frames_on_response_id": ecu.frames,
            })

    pairs.sort(key=lambda p: -p["score"])
    seen_unordered: set[frozenset] = set()
    deduped = []
    for pair in pairs:
        key = frozenset((pair["request_id_value"], pair["response_id_value"]))
        if key in seen_unordered:
            continue                    # the same two ids, weaker orientation
        seen_unordered.add(key)
        deduped.append(pair)
    pairs = deduped
    for pair in pairs:
        key = (pair["request_id_value"], pair["response_id_value"])
        pair["matches"] = STANDARD_PAIRS.get(key)
        pair.pop("request_id_value", None)
        pair.pop("response_id_value", None)

    functional = [
        f"0x{FUNCTIONAL_ID:X}" for _ in [1]
        if FUNCTIONAL_ID in by_id and by_id[FUNCTIONAL_ID].requests
    ]

    notes: list[str] = []
    if functional:
        notes.append(
            f"Requests were also seen on {functional[0]} - the functional "
            "(broadcast) address. Ignore it: the physical pair above is what "
            "the workstation needs."
        )
    if span and span > 120:
        notes.append(
            f"The capture spans {span / 60:.0f} minutes; a minute or two of a "
            "live diagnostic session is enough."
        )
    if not pairs:
        notes.append(
            "No ISO-TP diagnostic traffic was recognised. Either the log has "
            "no diagnostic session in it (start one with GuzziCanDiag while "
            "capturing), or the pair does not speak ISO-TP the standard way - "
            "in which case this project wants to hear about it."
        )

    return {
        "frames": len(frames),
        "span_seconds": round(span, 3) if span else None,
        "bus_ids": [f"0x{i:X}" for i in sorted(by_id)],
        "pairs": pairs[:5],
        "notes": notes,
        "diagnostic_traffic_found": bool(pairs),
    }


def analyze_capture_file(path: str | Path) -> dict:
    frames, fmt, warnings = parse_capture_file(path)
    result = analyze_frames(frames)
    result["format"] = fmt
    if warnings:
        result["notes"] = warnings + result["notes"]
    return result


def analyze_capture_text(text: str) -> dict:
    frames, fmt, warnings = parse_capture(text)
    result = analyze_frames(frames)
    result["format"] = fmt
    if warnings:
        result["notes"] = warnings + result["notes"]
    return result


#: For docs and the UI: how to take the capture in the first place.
HOW_TO_CAPTURE = """\
Passive capture, no bike-side changes:

1. Connect a CAN adapter to the bike's OBD socket and your laptop
   (nothing else should be talking on the bus).
2. Start logging:
   - SavvyCAN: connect, File > Log To File, then run a GuzziCanDiag session
     (identify + live data is plenty). Stop logging and export as CSV.
   - socketcan: candump -tz can0 > capture.log (or candump -L can0).
3. Point the analyzer at the file. A minute of a live session is enough.
The analyzer only ever reads a file; nothing here touches the bike."""
