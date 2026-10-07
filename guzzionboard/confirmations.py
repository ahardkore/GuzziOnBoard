"""Field confirmations: what one operator's real session is allowed to prove.

The catalog's confidence levels are a promise about where a byte-level claim
came from. ``verified-bench`` says "exercised against this ECU on a bench or a
bike". Today exactly one family (IAW 5AM) has earned that, because one
capture happened to be published. Everybody else who owns the other nine
families has no way to turn their own working session into evidence that
helps the next person - and the maintainers have no way to check that a
submitted "it works" is real.

This module is the capture half of the answer. It takes the session log that
already exists (raw frames, decoded samples, safety decisions) and freezes it
into a *confirmation bundle*:

* the **frozen capture** - the exact JSONL bytes hashed into the bundle, so a
  reviewer can recompute every claim from the same file the operator attached;
* **claims** - one per operation the session actually exercised on hardware
  (``identify``, ``live``, ``dtc_read``, ``routine:<key>``, ...), each with the
  frame/sample count and a digest over the canonical events that support it;
* the **catalog fingerprint** - SHA-256 of the family definition this session
  ran against, so a promotion can never be applied to a definition that has
  since changed under it;
* an **anonymous install marker** - a hash of a random per-install id, so two
  submissions from one person can be told apart from two independent ones.

Two rules are enforced here, not downstream:

1. **A simulated session confirms nothing.** ``simulator`` and ``cansim``
   sessions are refused at build time, and a bundle whose capture says
   otherwise is refused at validation time. The simulator is honest about
   proving the *software*; it cannot prove a motorcycle.
2. **Writing is not a claimable operation.** Program/erase/write events are
   recorded as observed-but-not-claimable. Enabling writes for strangers on
   the strength of a field confirmation is exactly the kind of promotion this
   project refuses; that path runs through ``docs/PHYSICAL_VALIDATION.md``.

Nothing here uploads anything. A bundle is a file on the operator's disk until
the operator chooses to attach it to a GitHub issue or PR.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from . import __version__

SCHEMA = "guzzionboard.protocol-confirmation/v1"
DEFAULT_DIR = Path.home() / ".guzzionboard" / "confirmations"
INSTALL_FILE = Path.home() / ".guzzionboard" / "install.json"
SIM_TRANSPORTS = ("simulator", "cansim")

#: Every claim name a bundle may carry. The promotion table in
#: :mod:`guzzionboard.protocol_updates` maps these onto catalog changes.
BASE_CLAIMS = (
    "handshake",
    "identify",
    "live",
    "dtc_read",
    "dtc_clear",
    "actuators",
    "routine",
    "memory_read",
    "memory_backup",
    "discover",
)

#: Events that describe an operation the promotion pipeline must never let a
#: field confirmation enable. Kept as an explicit list so ``observed`` can
#: report them without turning them into claims.
NOT_CLAIMABLE = (
    "write",
    "write_session",
    "programming_session",
    "image_validate",
    "erase",
)


class ConfirmationError(ValueError):
    """A confirmation bundle that cannot be trusted or reproduced."""


# --------------------------------------------------------------- install id


def _read_install(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def install_id(path: str | Path | None = None, *, refresh: bool = False) -> str:
    """A random, anonymous, per-install identifier.

    It exists only so a reviewer can tell "two confirmations" from "one
    person who submitted twice". It is not derived from hardware, a serial
    number, a hostname or any account, it never leaves the machine except as
    a truncated SHA-256, and ``--new-install-id`` replaces it.
    """
    path = Path(path) if path is not None else INSTALL_FILE
    record = None if refresh else _read_install(path)
    if record and re.fullmatch(r"[0-9a-f]{32}", str(record.get("install_id", ""))):
        return str(record["install_id"])
    value = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "guzzionboard.install/v1",
                "install_id": value,
                "note": (
                    "Random and anonymous. Used only to tell independent field "
                    "confirmations apart; delete this file to get a new one."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return value


def install_marker(value: str) -> str:
    """The only form of the install id that ever goes into a bundle."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------- claim parsing


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(events: list[dict]) -> str:
    """A digest over the canonical form of the evidence events."""
    from .signing import canonical_json

    return _sha(canonical_json(events))


def parse_capture(capture: bytes) -> list[dict]:
    """The events of a frozen capture, rejecting anything unreadable."""
    events: list[dict] = []
    for number, line in enumerate(capture.decode("utf-8", "strict").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfirmationError(f"capture line {number} is not JSON: {exc}") from exc
        if not isinstance(event, dict) or "kind" not in event:
            raise ConfirmationError(f"capture line {number} is not a session event")
        events.append(event)
    if not events:
        raise ConfirmationError("the capture is empty; there is nothing to confirm")
    return events


def _detail(event: dict) -> dict:
    """The payload of an action event, as ``SessionLog.action`` writes it."""
    detail = event.get("detail")
    if isinstance(detail, dict):
        return detail
    # Tolerate a flattened record too: older captures in the wild.
    return {
        key: value for key, value in event.items()
        if key not in ("t", "kind", "name", "detail")
    }


def _window(events: list[dict], index: int) -> list[dict]:
    """The frame group belonging to the operation logged at ``index``.

    ``SessionLog`` writes raw frames immediately before the action that
    explains them, so a claim's evidence is "this action plus the frames since
    the previous non-frame event". That is checkable by eye and by machine.
    """
    frames: list[dict] = []
    cursor = index - 1
    while cursor >= 0 and events[cursor]["kind"] == "frame":
        frames.insert(0, events[cursor])
        cursor -= 1
    return frames


def _session_meta(events: list[dict]) -> dict:
    for event in events:
        if event["kind"] == "session_start":
            return dict(event.get("meta") or {})
    return {}


def _action(events: list[dict], name: str) -> tuple[int, dict] | tuple[None, None]:
    for index, event in enumerate(events):
        if event["kind"] == "action" and event.get("name") == name:
            return index, event
    return None, None


def derive_claims(events: list[dict]) -> dict[str, dict]:
    """Turn a capture into claims, one per operation that actually ran.

    Everything is derived from the recorded events - never from the catalog -
    so the same function recomputes the same claims during review.
    """
    claims: dict[str, dict] = {}

    def add(name: str, events_in: list[dict], **extra) -> None:
        frames = [e for e in events_in if e.get("kind") == "frame"]
        claims[name] = {
            "events": len(events_in),
            "frames": len(frames),
            "digest": _digest(events_in),
            **extra,
        }

    connect_index, connect = _action(events, "connect")
    connect_detail = _detail(connect) if connect else {}
    tx_frames = [e for e in events if e["kind"] == "frame" and e.get("dir") == "tx"]
    rx_frames = [e for e in events if e["kind"] == "frame" and e.get("dir") == "rx"]
    if connect and connect_detail.get("ok") and tx_frames and rx_frames:
        add(
            "handshake",
            _window(events, connect_index) + [connect],
            protocol=connect_detail.get("protocol", ""),
            init=connect_detail.get("init", ""),
            attempts=connect_detail.get("attempts", 0),
        )

    identify_index, identify = _action(events, "identify")
    identify_fields = _detail(identify).get("fields") if identify else None
    if identify and identify_fields:
        add(
            "identify",
            _window(events, identify_index) + [identify],
            fields=sorted(str(k) for k in identify_fields),
        )

    samples = [e for e in events if e["kind"] == "sample"]
    if samples:
        keys = sorted({str(e.get("key")) for e in samples})
        per_key = {}
        for key in keys:
            group = [e for e in samples if str(e.get("key")) == key]
            with_raw = [e for e in group if e.get("raw")]
            per_key[key] = {
                "samples": len(group),
                "raw_samples": len(with_raw),
                "digest": _digest(group),
                "raw_first": with_raw[0]["raw"] if with_raw else "",
                "raw_last": with_raw[-1]["raw"] if with_raw else "",
            }
        add("live", samples, keys=keys, per_key=per_key)

    dtc_index, dtc_action = _action(events, "read_dtcs")
    if dtc_action is not None:
        add(
            "dtc_read",
            _window(events, dtc_index) + [dtc_action],
            count=int(_detail(dtc_action).get("count") or 0),
        )

    clear_index, clear_action = _action(events, "clear_dtcs")
    if clear_action is not None and _detail(clear_action).get("result") == "ok":
        add("dtc_clear", _window(events, clear_index) + [clear_action])

    actuator_events = [
        e for e in events
        if e["kind"] == "action" and e.get("name") in ("actuator_on", "actuator_off")
    ]
    if actuator_events:
        on_events = [e for e in actuator_events if e.get("name") == "actuator_on"]
        keys = sorted({str(_detail(e).get("key")) for e in on_events}) if on_events else []
        add("actuators", actuator_events, keys=keys)
        for key in keys:
            group = [
                e for e in actuator_events if str(_detail(e).get("key")) == key
            ]
            add(f"actuator:{key}", group, key=key)

    for index, event in enumerate(events):
        if (
            event["kind"] == "action"
            and event.get("name") == "routine"
            and _detail(event).get("ok")
        ):
            key = str(_detail(event).get("key"))
            if f"routine:{key}" not in claims:
                add(f"routine:{key}", _window(events, index) + [event], key=key)
    routines = sorted(
        name.split(":", 1)[1] for name in claims if name.startswith("routine:")
    )
    if routines:
        group = [
            e for e in events
            if e["kind"] == "action" and e.get("name") == "routine"
            and _detail(e).get("ok")
        ]
        claims["routine"] = {
            "events": len(group),
            "frames": 0,
            "digest": _digest(group),
            "keys": routines,
        }

    memory_index, memory = _action(events, "memory_read_complete")
    if memory is not None:
        detail = _detail(memory)
        add(
            "memory_read",
            _window(events, memory_index) + [memory],
            size=int(detail.get("size") or 0),
            image_sha256=str(detail.get("sha256") or ""),
            region=str(detail.get("region") or ""),
        )

    backup_index, backup = _action(events, "backup")
    if backup is not None and _detail(backup).get("verified"):
        detail = _detail(backup)
        add(
            "memory_backup",
            _window(events, backup_index) + [backup],
            image_sha256=str(detail.get("sha256") or ""),
            region=str(detail.get("region") or ""),
        )

    discover_index, discover = _action(events, "discover")
    if discover is not None:
        add(
            "discover",
            _window(events, discover_index) + [discover],
            answered=int((_detail(discover).get("answered") or 0)),
        )

    return claims


def observed_only(events: list[dict]) -> dict:
    """Operations seen in the capture that a confirmation cannot claim."""
    counts: dict[str, int] = {}
    for event in events:
        if event["kind"] != "action":
            continue
        name = str(event.get("name") or "")
        if name in NOT_CLAIMABLE:
            counts[name] = counts.get(name, 0) + 1
    return {
        "not_claimable": sorted(counts),
        "counts": counts,
        "note": (
            "Write, program and erase activity is recorded for provenance only. "
            "A field confirmation can never enable those operations for other "
            "installs; that promotion requires the physical-validation protocol."
        ),
    }


# ------------------------------------------------------------------- bundle


def build_confirmation(
    *,
    profile,
    capture: bytes,
    transport: str,
    mode: str = "",
    device_kind: str = "",
    operator_note: str = "",
    disputes: list[str] | None = None,
    include_fitment: bool = False,
    install: str | None = None,
    created_at: float | None = None,
    catalog_fingerprint: str | None = None,
) -> dict:
    """Build a confirmation bundle from a finished (or ongoing) session log.

    ``capture`` is the exact bytes that will travel with the bundle. Everything
    the bundle asserts is recomputable from them.
    """
    events = parse_capture(capture)
    meta = _session_meta(events)
    session_transport = str(meta.get("transport") or transport or "")
    if session_transport in SIM_TRANSPORTS or transport in SIM_TRANSPORTS:
        raise ConfirmationError(
            "a simulated session confirms nothing about hardware: the simulator "
            "is the reference implementation, not evidence about a motorcycle. "
            "Run one session against the real ECU first."
        )

    connect = _detail(_action(events, "connect")[1] or {})
    claims = derive_claims(events)
    fitment = {}
    if include_fitment:
        fitment = {
            "operator_declared": True,
            "model": str(meta.get("model") or ""),
            "year": meta.get("year") or 0,
        }

    handshake_ok = bool(connect.get("ok")) and "handshake" in claims
    problems = []
    if not handshake_ok:
        problems.append("the capture holds no successful, framed handshake")
    if not claims:
        problems.append("no operation in the capture is claimable")
    verdict = "ok" if not problems else "incomplete"

    if catalog_fingerprint is None:
        from .catalog import source_fingerprint

        catalog_fingerprint = source_fingerprint(profile.id)

    created_at = time.time() if created_at is None else created_at
    return {
        "schema": SCHEMA,
        "id": f"conf-{uuid.uuid4().hex[:12]}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(created_at)),
        "app": {"name": "GuzziOnBoard", "version": __version__},
        "install": {
            "marker": install_marker(install or install_id()),
            "anonymous": True,
            "note": (
                "SHA-256 prefix of a random per-install id. No hardware serial, "
                "hostname, account or location is recorded."
            ),
        },
        "ecu": {
            "id": profile.id,
            "family": profile.family,
            "catalog_fingerprint": catalog_fingerprint,
            "declared_confidence": profile.confidence,
            "declared_physical_supported": bool(
                profile.session.get("physical_supported")
            ),
            "declared_capabilities": sorted(profile.capabilities),
        },
        "session": {
            "transport": session_transport,
            "mode": str(meta.get("mode") or mode or ""),
            "device_kind": device_kind,
            "protocol": str(connect.get("protocol") or ""),
            "init": str(connect.get("init") or ""),
            "attempts": connect.get("attempts", 0),
            "started_at": str(meta.get("started_at") or ""),
            "events": len(events),
            "frames": sum(1 for e in events if e["kind"] == "frame"),
            "capture_sha256": _sha(capture),
            "capture_bytes": len(capture),
            "identity": _identity_from_events(events),
        },
        "fitment": fitment,
        "claims": claims,
        "observed": observed_only(events),
        "disputes": sorted({str(d).strip() for d in (disputes or []) if str(d).strip()}),
        "operator_note": str(operator_note or "").strip()[:2000],
        "verdict": verdict,
        "verdict_reason": "; ".join(problems) if problems else (
            "Hardware session with a validated handshake and at least one "
            "claimable operation."
        ),
    }


def _identity_from_events(events: list[dict]) -> dict:
    """The ECU part-number block, taken from the identify action.

    Identity strings (drawing/hardware/software numbers) are the fitment
    evidence a reviewer needs, and they describe the ECU, not the rider.
    """
    for event in events:
        if event["kind"] == "action" and event.get("name") == "identify":
            fields = _detail(event).get("fields") or {}
            return {str(k): str(v) for k, v in fields.items()}
    return {}


# --------------------------------------------------------------- validation


def validate_bundle(bundle: dict) -> dict:
    """Schema and honesty checks that need no capture. Raises or returns
    a normalized copy with a ``findings`` list."""
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise ConfirmationError(f"schema must be {SCHEMA!r}")
    findings: list[str] = []
    for key in ("id", "created_at", "app", "install", "ecu", "session", "claims"):
        if not bundle.get(key):
            raise ConfirmationError(f"{key} is required")
    if not re.fullmatch(r"conf-[0-9a-f]{6,32}", str(bundle["id"])):
        raise ConfirmationError("id must look like 'conf-<hex>'")
    ecu = bundle["ecu"]
    if not re.fullmatch(r"[0-9a-f]{64}", str(ecu.get("catalog_fingerprint", ""))):
        raise ConfirmationError("ecu.catalog_fingerprint must be a SHA-256")
    for key in ("id", "family"):
        if not str(ecu.get(key) or ""):
            raise ConfirmationError(f"ecu.{key} is required")
    session = bundle["session"]
    transport = str(session.get("transport") or "")
    if transport in SIM_TRANSPORTS:
        raise ConfirmationError(
            "a simulated session cannot be submitted as a field confirmation"
        )
    if not transport:
        raise ConfirmationError("session.transport is required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(session.get("capture_sha256", ""))):
        raise ConfirmationError("session.capture_sha256 must be a SHA-256")
    claims = bundle["claims"]
    if not isinstance(claims, dict) or not claims:
        raise ConfirmationError("at least one claim is required")
    for name, claim in claims.items():
        base = name.split(":", 1)[0]
        if base not in BASE_CLAIMS:
            raise ConfirmationError(f"unknown claim {name!r}")
        if not isinstance(claim, dict):
            raise ConfirmationError(f"claim {name!r} must be an object")
        if not re.fullmatch(r"[0-9a-f]{64}", str(claim.get("digest", ""))):
            raise ConfirmationError(f"claim {name!r} needs a SHA-256 digest")
        if int(claim.get("events") or 0) < 1:
            raise ConfirmationError(f"claim {name!r} has no evidence events")
    if "handshake" not in claims:
        findings.append(
            "no handshake claim: the bundle establishes nothing about this "
            "family's transport, so only read-level claims should be considered"
        )
    if bundle.get("verdict") not in ("ok", "incomplete"):
        raise ConfirmationError("verdict must be 'ok' or 'incomplete'")
    if str(bundle.get("install", {}).get("marker", "")) and not re.fullmatch(
        r"[0-9a-f]{16}", str(bundle["install"]["marker"])
    ):
        raise ConfirmationError("install.marker must be a 16-hex anonymous marker")
    forbidden = [
        key for key in ("vin", "serial", "plate", "owner", "email", "address")
        if isinstance(bundle.get(key), str) and bundle.get(key)
    ]
    if forbidden:
        raise ConfirmationError(
            f"bundles must not carry identifiers: {', '.join(forbidden)}"
        )
    return {**bundle, "findings": findings}


def verify_confirmation(bundle: dict, capture: bytes) -> dict:
    """Recompute every claim from the frozen capture.

    This is the reviewer's half of the contract, and it runs in the app too:
    if a bundle has been edited, or the capture is not the one it was built
    from, this says so instead of quietly promoting a capability.
    """
    validated = validate_bundle(bundle)
    if _sha(capture) != validated["session"]["capture_sha256"]:
        raise ConfirmationError(
            "the capture does not match session.capture_sha256: the bundle and "
            "the file it names are not the same evidence"
        )
    events = parse_capture(capture)
    derived = derive_claims(events)
    mismatches: list[str] = []
    missing: list[str] = []
    for name, claim in validated["claims"].items():
        current = derived.get(name)
        if current is None:
            missing.append(name)
            continue
        for field in ("digest", "events", "frames"):
            if field in claim and claim.get(field) != current.get(field):
                mismatches.append(
                    f"{name}.{field}: bundle says {claim.get(field)!r}, "
                    f"the capture says {current.get(field)!r}"
                )
    extra = sorted(set(derived) - set(validated["claims"]))
    if mismatches or missing:
        raise ConfirmationError(
            "the capture does not reproduce this bundle: "
            + "; ".join(mismatches + [f"no evidence for {name}" for name in missing])
        )
    return {
        "ok": True,
        "id": validated["id"],
        "ecu": validated["ecu"]["id"],
        "transport": validated["session"]["transport"],
        "claims": sorted(validated["claims"]),
        "events": len(events),
        "frames": sum(1 for e in events if e["kind"] == "frame"),
        "unclaimed_evidence": extra,
        "findings": validated.get("findings", []),
    }


# ------------------------------------------------------------------- storage


def save_confirmation(
    bundle: dict,
    capture: bytes,
    directory: str | Path | None = None,
) -> dict:
    """Write the bundle and its frozen capture side by side."""
    directory = Path(directory) if directory is not None else DEFAULT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    bundle_path = directory / f"{bundle['id']}.json"
    capture_path = directory / f"{bundle['id']}.session.jsonl"
    capture_path.write_bytes(capture)
    bundle_path.write_text(
        json.dumps({**bundle, "capture_file": capture_path.name}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "bundle_path": str(bundle_path),
        "capture_path": str(capture_path),
        "sha256": _sha(bundle_path.read_bytes()),
        "directory": str(directory),
    }


def load_bundle(path: str | Path) -> dict:
    path = Path(path).expanduser()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfirmationError(f"{path}: {exc}") from exc


def capture_for(bundle: dict, directory: str | Path) -> bytes:
    """The frozen capture belonging to a stored bundle."""
    name = bundle.get("capture_file") or f"{bundle['id']}.session.jsonl"
    path = Path(directory) / name
    if not path.is_file():
        raise ConfirmationError(
            f"{path} is missing: the bundle cannot be reviewed without its capture"
        )
    return path.read_bytes()


def list_confirmations(directory: str | Path | None = None) -> list[dict]:
    directory = Path(directory) if directory is not None else DEFAULT_DIR
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("conf-*.json"), reverse=True):
        try:
            bundle = load_bundle(path)
            out.append(
                {
                    "id": bundle.get("id"),
                    "path": str(path),
                    "created_at": bundle.get("created_at"),
                    "ecu": (bundle.get("ecu") or {}).get("id"),
                    "verdict": bundle.get("verdict"),
                    "claims": sorted((bundle.get("claims") or {})),
                    "transport": (bundle.get("session") or {}).get("transport"),
                    "operator_note": bundle.get("operator_note", ""),
                    "capture_sha256": (bundle.get("session") or {}).get(
                        "capture_sha256"
                    ),
                }
            )
        except ConfirmationError:
            continue
    return out


#: Where a confirmation goes once it exists. There is no upload endpoint: the
#: operator attaches the two files to a GitHub issue, which keeps the evidence
#: public, reviewable and free of any server this project would have to run.
SUBMIT_URL = "https://github.com/ahardkore/GuzziOnBoard/issues/new"
SUBMIT_TEMPLATE = "protocol-confirmation.yml"


def submission(bundle: dict, *, file_name: str = "") -> dict:
    """A pre-filled issue link plus the text to paste next to the files."""
    claims = ", ".join(sorted(bundle.get("claims", {})))
    title = f"Protocol confirmation: {bundle['ecu']['family']} ({bundle['ecu']['id']})"
    body = "\n".join(
        [
            f"- Confirmation id: `{bundle['id']}`",
            f"- ECU family: `{bundle['ecu']['id']}` ({bundle['ecu']['family']})",
            f"- Catalog fingerprint: `{bundle['ecu']['catalog_fingerprint']}`",
            f"- Declared confidence: `{bundle['ecu']['declared_confidence']}`",
            f"- Transport: `{bundle['session']['transport']}`"
            f" / init `{bundle['session'].get('init', '')}`",
            f"- Capture: `{bundle['session']['capture_sha256']}`"
            f" ({bundle['session']['capture_bytes']} bytes,"
            f" {bundle['session']['frames']} frames)",
            f"- Claims: {claims}",
            f"- Verdict: {bundle['verdict']} - {bundle['verdict_reason']}",
            "",
            "Attach both files from the confirmation directory"
            + (f" ({file_name})" if file_name else "")
            + ": the `.json` bundle and its `.session.jsonl` capture.",
        ]
    )
    from urllib.parse import urlencode

    query = urlencode({"template": SUBMIT_TEMPLATE, "title": title, "body": body})
    return {
        "url": f"{SUBMIT_URL}?{query}",
        "title": title,
        "body": body,
        "files": ["<id>.json", "<id>.session.jsonl"],
        "note": (
            "Nothing is uploaded by GuzziOnBoard. Opening the link starts an "
            "issue where you attach the bundle and its capture yourself; the "
            "maintainer can recompute every claim from that capture."
        ),
    }
