"""Signed protocol updates: how one operator's confirmation reaches every install.

The catalog's confidence levels are data, and data can be updated - but this
is a tool that talks to a motorcycle's engine controller, so "somebody said it
works" is not a mechanism. This module is the other half of
:mod:`guzzionboard.confirmations`: it turns reviewed field confirmations into a
single **protocol update pack**, and it decides what a pack is allowed to do.

The pipeline
------------

1. **Capture** (``confirmations.py``) - an operator's real session freezes into
   a bundle with a raw capture and claim digests.
2. **Aggregate** (:func:`build_update_pack`) - confirmations are validated
   against their captures and grouped by ``(ECU family, claim)``. A claim needs
   ``quorum`` confirmations that are *independent*: distinct install markers
   and distinct captures. Contradicted claims are refused, not averaged.
3. **Sign** (:func:`envelope_for`) - the pack is canonicalised and signed with
   the maintainer's Ed25519 seed. The seed never enters this repository.
4. **Distribute** - the envelope is published as a release asset. The URL is
   pinned in :data:`DEFAULT_PACK_URL`; the key that signs it lives in the
   shipped keyring, and an operator can pin their own as well.
5. **Verify and apply** (``apply_pack``) - the install checks the signature
   against a pinned key, checks that the pack was reviewed against this exact
   catalog revision, checks that its sequence number is newer than what is
   already applied, and only then writes an overlay. The overlay is read by
   ``catalog.load_catalog()`` on the next start.

What a pack may do
------------------

A promotion is a set of **effects**, and the allowlist is deliberately short:
open a physical session, grant a *read-level* capability, mark observed
parameters ``verified-bench``, and attach provenance. Nothing else. In
particular:

* **No pack can raise a family's overall confidence.** Control actions gate on
  the profile level (``safety.py``), so a pack cannot widen what a stranger's
  motorcycle will answer to. Raising a family to ``verified-bench`` stays a
  human catalog change with a review trail.
* **No pack can enable writing, erasing or programming.** Those effects do not
  exist in the vocabulary at all, the words are rejected if they appear, and
  the write path additionally requires the physical-validation protocol in
  ``docs/PHYSICAL_VALIDATION.md``.
* **No pack can rewrite scalings, identifiers, actuators or routines.** A
  promotion that could edit those would be a way to smuggle a guessed byte
  past review.

Why not just query a server? Because there is no server. The pack is a file
with a signature; the repository ships the public key, the maintainer keeps
the private one, and an install that never fetches anything still gets
promotions through the ordinary catalog in the next release.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .confirmations import (
    ConfirmationError,
    derive_claims,
    parse_capture,
    validate_bundle,
    verify_confirmation,
)
from .signing import (
    SignatureError,
    canonical_json,
    is_public_key,
    load_keyring,
    save_keyring,
    verify as verify_signature,
)

SCHEMA = "guzzionboard.protocol-update/v1"
ENVELOPE_SCHEMA = "guzzionboard.protocol-update-envelope/v1"
OVERLAY_SCHEMA = "guzzionboard.protocol-overlay/v1"

DEFAULT_DIR = Path.home() / ".guzzionboard" / "protocol"
#: Public keyring shipped with the application (see ``docs/PROTOCOL_UPDATES.md``).
BUNDLED_KEYRING = Path(__file__).parent / "catalog" / "protocol_keys.json"
#: Release asset every install checks. GitHub Releases, not a bespoke service:
#: the artifact is public, versioned and independently mirrorable.
DEFAULT_PACK_URL = (
    "https://github.com/ahardkore/GuzziOnBoard/releases/latest/download/"
    "protocol-update.json"
)
#: An operator (or a workshop) can pin additional keys without touching the
#: shipped ones. Empty until somebody adds one.
LOCAL_KEYRING = DEFAULT_DIR / "keys.json"

MAX_PACK_BYTES = 512 * 1024
MAX_FETCH_SECONDS = 20.0

#: Read-level capabilities a verified confirmation may grant.
PACK_CAPABILITIES = ("identify", "live", "dtc_read", "memory_read")

#: claim name -> the capability it justifies.
CLAIM_CAPABILITY = {
    "identify": "identify",
    "live": "live",
    "dtc_read": "dtc_read",
    "memory_read": "memory_read",
    "memory_backup": "memory_read",
}

#: Effects a promotion may ask for, and the claims that justify them.
#: ``requires_all`` must all be present; ``requires_any`` needs one of them.
EFFECT_TARGETS: dict[str, dict] = {
    "session.physical_supported": {
        "kind": "bool",
        "requires_all": ("handshake",),
        "requires_any": ("identify", "live", "dtc_read"),
        "reason": "a validated handshake plus at least one answered operation",
    },
    "memory.read_supported": {
        "kind": "bool",
        "requires_any": ("memory_read", "memory_backup"),
        "reason": "a completed ECU memory read",
    },
    "capability": {
        "kind": "capability",
        "requires_any": (),
        "reason": "the capability this claim exercised",
    },
    "capability_confidence": {
        "kind": "capability-level",
        "requires_any": (),
        "reason": "the capability this claim exercised",
    },
    "parameter_confidence": {
        "kind": "parameter-level",
        "requires_all": ("live",),
        "reason": "live samples with raw bytes",
    },
    "source": {
        "kind": "text",
        "requires_any": (),
        "reason": "provenance for the promoted definition",
    },
}

#: Levels a pack may set. ``verified-bench`` is what a real session earns;
#: anything weaker than the family's own level is not a promotion at all.
PACK_LEVELS = ("verified-bench", "verified-capture")

#: Words that must never appear in an effect. Belt and braces: the targets
#: above already exclude them, and a pack that tries anyway is refused rather
#: than partially applied.
FORBIDDEN_EFFECT_TOKENS = (
    "write", "erase", "program", "flash", "bootloader", "recover",
    "actuat", "routine", "discover", "clear",
)


class ProtocolUpdateError(ValueError):
    """A pack that is not signed, not current, or not allowed to do that."""


# --------------------------------------------------------------------- utils


def _now(now: float | None = None) -> float:
    return time.time() if now is None else float(now)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str, field: str) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ProtocolUpdateError(f"{field} must be an ISO-8601 date-time") from exc


def pack_digest(payload: dict) -> str:
    """SHA-256 over the canonical payload - the identity of a promotion set."""
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def promotion_key(promotion: dict) -> str:
    """``ecu/claim`` - what a promotion is about, used for de-duplication."""
    return f"{promotion.get('ecu')}/{promotion.get('claim')}"


def _forbidden(text: str) -> str | None:
    lowered = text.lower()
    for token in FORBIDDEN_EFFECT_TOKENS:
        if token in lowered:
            return token
    return None


def check_effects(promotion: dict, available_claims: set[str] | None = None) -> dict:
    """Validate one promotion's effects against the allowlist.

    Raises :class:`ProtocolUpdateError` for anything this application is not
    allowed to apply - unknown targets, forbidden vocabulary, a control
    capability, or an effect the claims do not justify. ``available_claims``
    is every base claim this pack promotes for the same ECU, which is what
    cross-claim conditions (a handshake *plus* an answered operation) are
    checked against.
    """
    claim = str(promotion.get("claim") or "")
    base_claim = claim.split(":", 1)[0]
    promoted = set(available_claims or {base_claim})
    effects = promotion.get("effects")
    if not isinstance(effects, list) or not effects:
        raise ProtocolUpdateError(f"{promotion_key(promotion)}: no effects")
    for effect in effects:
        if not isinstance(effect, dict):
            raise ProtocolUpdateError(f"{promotion_key(promotion)}: malformed effect")
        target = str(effect.get("target") or "")
        rule = EFFECT_TARGETS.get(target)
        if rule is None:
            token = _forbidden(target) or _forbidden(json.dumps(effect))
            raise ProtocolUpdateError(
                f"{promotion_key(promotion)}: effect {target!r} is not in this "
                "application's allowlist"
                + (f" (contains {token!r})" if token else "")
                + ". Writing, programming and control actions cannot arrive in "
                "a protocol update."
            )
        for required in rule.get("requires_all", ()):
            if required not in promoted:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: effect {target!r} needs a "
                    f"{required!r} claim ({rule['reason']})"
                )
        any_of = rule.get("requires_any")
        if any_of and not (promoted & set(any_of)):
            raise ProtocolUpdateError(
                f"{promotion_key(promotion)}: effect {target!r} needs one of "
                f"{', '.join(any_of)} ({rule['reason']})"
            )
        value = effect.get("value")
        if rule["kind"] == "bool":
            if value is not True:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: effect {target!r} may only be true"
                )
        elif rule["kind"] == "capability":
            capability = str(value or "")
            if claim.split(":", 1)[0] not in CLAIM_CAPABILITY and not claim.startswith(
                ("routine:", "actuator:")
            ):
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: claim {claim!r} grants no capability"
                )
            if capability not in PACK_CAPABILITIES:
                token = _forbidden(capability)
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: capability {capability!r} is not "
                    "in the read-level allowlist "
                    f"({', '.join(PACK_CAPABILITIES)})"
                    + (f"; forbidden term {token!r}" if token else "")
                )
            expected = CLAIM_CAPABILITY.get(claim)
            if expected and capability != expected:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: claim {claim!r} justifies "
                    f"{expected!r}, not {capability!r}"
                )
        elif rule["kind"] == "capability-level":
            body = value if isinstance(value, dict) else {}
            capability = str(body.get("capability") or "")
            level = str(body.get("confidence") or "")
            if capability not in PACK_CAPABILITIES:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: {capability!r} is not a "
                    "read-level capability"
                )
            if level not in PACK_LEVELS:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: confidence {level!r} is outside "
                    f"{PACK_LEVELS}"
                )
        elif rule["kind"] == "parameter-level":
            body = value if isinstance(value, dict) else {}
            if not str(body.get("key") or ""):
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: parameter_confidence needs a key"
                )
            if str(body.get("confidence") or "") not in PACK_LEVELS:
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: parameter confidence must be one "
                    f"of {PACK_LEVELS}"
                )
        elif rule["kind"] == "text":
            if not str(value or "").strip():
                raise ProtocolUpdateError(
                    f"{promotion_key(promotion)}: effect {target!r} needs text"
                )
    return {"promotion": promotion_key(promotion), "effects": len(effects)}


# ------------------------------------------------------------------ building


def _claim_effects(
    ecu: str,
    claim: str,
    *,
    keys: list[str],
    parameters: list[str],
    family: str,
    references: list[dict],
    promoted: set[str],
) -> list[dict]:
    """The effects a claim earns - the one place that mapping lives."""
    base = claim.split(":", 1)[0]
    effects: list[dict] = []
    if base in ("handshake", "identify", "live", "dtc_read") and (
        "handshake" in promoted and promoted & {"identify", "live", "dtc_read"}
    ):
        effects.append({"target": "session.physical_supported", "value": True})
    if base in CLAIM_CAPABILITY:
        capability = CLAIM_CAPABILITY[base]
        effects.append({"target": "capability", "value": capability})
        effects.append(
            {
                "target": "capability_confidence",
                "value": {"capability": capability, "confidence": "verified-bench"},
            }
        )
    if base in ("memory_read", "memory_backup"):
        effects.append({"target": "memory.read_supported", "value": True})
    if base == "live" and parameters:
        for key in parameters:
            effects.append(
                {
                    "target": "parameter_confidence",
                    "value": {"key": key, "confidence": "verified-bench"},
                }
            )
    effects.append(
        {
            "target": "source",
            "value": (
                f"Verified protocol update: {family} {claim} confirmed by "
                f"{len(references)} independent field session(s) on real hardware "
                f"({', '.join(r['id'] for r in references)})"
            ),
        }
    )
    return effects


def build_update_pack(
    confirmations: list[tuple[dict, bytes]],
    *,
    quorum: int = 2,
    reviewer: str = "",
    pack_id: str = "",
    sequence: int = 1,
    issued_at: float | None = None,
    valid_days: int = 400,
    notes: str = "",
    withhold: tuple[str, ...] = (),
    allow_incomplete: bool = False,
) -> dict:
    """Aggregate confirmations into a pack. Pure: no files, no clock surprises.

    Each entry of ``confirmations`` is ``(bundle, capture_bytes)``. Every
    bundle is validated *and* re-derived from its capture, so a hand-edited
    claim cannot be aggregated.
    """
    if not confirmations:
        raise ProtocolUpdateError("no confirmations supplied")
    if quorum < 2:
        raise ProtocolUpdateError(
            "quorum must be at least 2: one machine, one session and one "
            "mistake must not be able to change the catalog for everybody"
        )
    issued = _now(issued_at)
    verified: list[dict] = []
    rejections: list[dict] = []
    for bundle, capture in confirmations:
        try:
            report = verify_confirmation(bundle, capture)
        except ConfirmationError as exc:
            rejections.append({"id": bundle.get("id", "?"), "reason": str(exc)})
            continue
        if bundle.get("verdict") != "ok" and not allow_incomplete:
            rejections.append(
                {
                    "id": bundle.get("id", "?"),
                    "reason": f"verdict is {bundle.get('verdict')!r}: "
                    f"{bundle.get('verdict_reason', '')}",
                }
            )
            continue
        verified.append({"bundle": bundle, "capture": capture, "report": report})
    if not verified:
        raise ProtocolUpdateError(
            "no confirmation passed validation: "
            + "; ".join(f"{r['id']}: {r['reason']}" for r in rejections)
        )

    # Group claim by claim, then family by family.
    groups: dict[tuple[str, str], list[dict]] = {}
    fingerprints: dict[str, set[str]] = {}
    for item in verified:
        bundle = item["bundle"]
        ecu = str(bundle["ecu"]["id"])
        fingerprints.setdefault(ecu, set()).add(str(bundle["ecu"]["catalog_fingerprint"]))
        for claim in sorted(bundle["claims"]):
            groups.setdefault((ecu, claim), []).append(
                {
                    "id": bundle["id"],
                    "install": bundle["install"]["marker"],
                    "capture": bundle["session"]["capture_sha256"],
                    "family": bundle["ecu"]["family"],
                    "claim_event": bundle["claims"][claim],
                }
            )

    # Which claims clear the bar for each family decides what effects are
    # justified, so the claim map is computed first and the effects after.
    promotable: list[tuple[str, str, list[dict]]] = []
    parameters_by_claim: dict[tuple[str, str], list[str]] = {}
    refused: list[dict] = []
    promoted_claims: dict[str, set[str]] = {}
    promotions: list[dict] = []
    for (ecu, claim), group in sorted(groups.items()):
        if f"{ecu}/{claim}" in withhold:
            refused.append(
                {"ecu": ecu, "claim": claim, "reason": "withheld by the reviewer"}
            )
            continue
        disputed = sorted(
            {
                str(dispute)
                for item in verified
                if item["bundle"]["ecu"]["id"] == ecu
                for dispute in item["bundle"].get("disputes", [])
            }
        )
        if claim in disputed or f"{ecu}/{claim}" in disputed:
            refused.append(
                {
                    "ecu": ecu,
                    "claim": claim,
                    "reason": "an operator reported this claim as not reproducing",
                }
            )
            continue
        if len(group) < quorum:
            refused.append(
                {
                    "ecu": ecu,
                    "claim": claim,
                    "reason": f"{len(group)} confirmation(s), quorum is {quorum}",
                }
            )
            continue
        markers = {g["install"] for g in group}
        captures = {g["capture"] for g in group}
        if len(markers) < quorum or len(captures) < quorum:
            refused.append(
                {
                    "ecu": ecu,
                    "claim": claim,
                    "reason": (
                        "the confirmations are not independent: "
                        f"{len(markers)} install(s), {len(captures)} capture(s)"
                    ),
                }
            )
            continue
        references = [
            {
                "id": g["id"],
                "install_marker": g["install"],
                "capture_sha256": g["capture"],
                "claim_digest": g["claim_event"]["digest"],
            }
            for g in sorted(group, key=lambda g: g["id"])
        ]
        parameters: list[str] = []
        if claim == "live":
            per_bundle = [
                set((b["bundle"]["claims"]["live"].get("per_key") or {}))
                for b in verified
                if b["bundle"]["ecu"]["id"] == ecu
            ]
            parameters = sorted(set.intersection(*per_bundle)) if per_bundle else []
        promoted_claims.setdefault(ecu, set()).add(claim.split(":", 1)[0])
        promotable.append((ecu, claim, references))
        if parameters:
            parameters_by_claim[(ecu, claim)] = parameters

    for ecu, claim, references in promotable:
        effects = _claim_effects(
            ecu,
            claim,
            keys=[],
            parameters=parameters_by_claim.get((ecu, claim), []),
            promoted=promoted_claims.get(ecu, {claim.split(":", 1)[0]}),
            family=next(
                (b["bundle"]["ecu"]["family"] for b in verified
                 if b["bundle"]["ecu"]["id"] == ecu),
                ecu,
            ),
            references=references,
        )
        promotions.append(
            {
                "ecu": ecu,
                "claim": claim,
                "effects": effects,
                "references": references,
                "evidence_note": (
                    f"{len(references)} independent field confirmation(s) on real "
                    f"hardware; each claim digest can be recomputed from the "
                    f"attached capture."
                ),
            }
        )

    for promotion in promotions:
        check_effects(promotion, promoted_claims.get(promotion["ecu"]))

    if not promotions:
        raise ProtocolUpdateError(
            "nothing reached quorum: "
            + "; ".join(f"{r['ecu']}/{r['claim']} - {r['reason']}" for r in refused)
        )

    base: dict[str, str] = {}
    for ecu, found in sorted(fingerprints.items()):
        if not any(promotion["ecu"] == ecu for promotion in promotions):
            continue
        if len(found) != 1:
            raise ProtocolUpdateError(
                f"{ecu}: confirmations were taken against different catalog "
                f"revisions ({len(found)}); rebuild them against one release"
            )
        base[ecu] = found.pop()
    id_text = pack_id or (
        f"pu-{_iso(issued)[:10]}-{pack_digest({'p': promotions})[:8]}"
    )
    return {
        "schema": SCHEMA,
        "id": id_text,
        "sequence": int(sequence),
        "issued_at": _iso(issued),
        "expires_at": _iso(issued + valid_days * 86400),
        "reviewer": reviewer,
        "quorum": int(quorum),
        "generator": {"tool": "build_protocol_update.py", "version": __version__},
        "base": {"catalog_fingerprints": base},
        "promotions": promotions,
        "refused": refused,
        "rejected": rejections,
        "notes": notes,
        "rules": (
            "Read-level promotions only. Family confidence, control actions and "
            "every write path are unchanged by a protocol update."
        ),
    }


# -------------------------------------------------------------------- signing


def envelope_for(pack: dict, *, seed: str, key_id: str) -> dict:
    """Wrap a pack in a signed envelope. ``seed`` is the maintainer's private
    key and must never be committed."""
    from .signing import public_key, sign

    if not key_id.strip():
        raise ProtocolUpdateError("a key id is required so installs know what to trust")
    validate_pack(pack)
    payload = json.loads(canonical_json(pack))
    return {
        "schema": ENVELOPE_SCHEMA,
        "key_id": key_id,
        "public_key": public_key(seed),
        "payload": payload,
        "signature": sign(canonical_json(payload), seed),
        "payload_sha256": pack_digest(payload),
    }


def validate_pack(pack: dict, *, now: float | None = None) -> dict:
    """Structural and semantic validation of a pack (no signature involved)."""
    if not isinstance(pack, dict) or pack.get("schema") != SCHEMA:
        raise ProtocolUpdateError(f"schema must be {SCHEMA!r}")
    for key in ("id", "sequence", "issued_at", "expires_at", "base", "promotions"):
        if pack.get(key) in (None, "", [], {}):
            raise ProtocolUpdateError(f"{key} is required")
    if int(pack["sequence"]) < 1:
        raise ProtocolUpdateError("sequence must be a positive integer")
    issued = _parse_time(pack["issued_at"], "issued_at")
    expires = _parse_time(pack["expires_at"], "expires_at")
    if expires <= issued:
        raise ProtocolUpdateError("expires_at must be after issued_at")
    moment = _now(now)
    if moment > expires:
        raise ProtocolUpdateError(
            f"{pack['id']} expired on {pack['expires_at']}; ask for a current "
            "protocol update"
        )
    if issued > moment + 86400:
        raise ProtocolUpdateError("issued_at is in the future; refusing the pack")
    fingerprints = (pack.get("base") or {}).get("catalog_fingerprints")
    if not isinstance(fingerprints, dict) or not fingerprints:
        raise ProtocolUpdateError("base.catalog_fingerprints is required")
    for ecu, value in fingerprints.items():
        if not isinstance(value, str) or len(value) != 64:
            raise ProtocolUpdateError(f"base fingerprint for {ecu!r} must be a SHA-256")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ProtocolUpdateError(
                f"base fingerprint for {ecu!r} must be hexadecimal"
            ) from exc
    promotions = pack["promotions"]
    if not isinstance(promotions, list) or not promotions:
        raise ProtocolUpdateError("a pack with no promotions is not an update")
    claims_by_ecu: dict[str, set[str]] = {}
    for promotion in promotions:
        if isinstance(promotion, dict) and promotion.get("ecu") and promotion.get("claim"):
            claims_by_ecu.setdefault(str(promotion["ecu"]), set()).add(
                str(promotion["claim"]).split(":", 1)[0]
            )
    seen: set[str] = set()
    for promotion in promotions:
        if not isinstance(promotion, dict):
            raise ProtocolUpdateError("promotions must be objects")
        for key in ("ecu", "claim", "effects", "references"):
            if not promotion.get(key):
                raise ProtocolUpdateError(f"promotion is missing {key!r}")
        if not isinstance(promotion["references"], list) or len(
            promotion["references"]
        ) < int(pack.get("quorum", 2)):
            raise ProtocolUpdateError(
                f"{promotion_key(promotion)}: fewer references than the quorum of "
                f"{pack.get('quorum', 2)}"
            )
        if promotion["ecu"] not in fingerprints:
            raise ProtocolUpdateError(
                f"{promotion_key(promotion)}: no base fingerprint for {promotion['ecu']}"
            )
        key = promotion_key(promotion)
        if key in seen:
            raise ProtocolUpdateError(f"{key}: duplicated promotion")
        seen.add(key)
        check_effects(promotion, claims_by_ecu.get(promotion["ecu"]))
    return pack


def verify_envelope(
    envelope: dict,
    keyring: dict[str, str],
    *,
    now: float | None = None,
) -> dict:
    """Check the signature and the pack. Raises on anything it cannot trust."""
    if not isinstance(envelope, dict) or envelope.get("schema") != ENVELOPE_SCHEMA:
        raise ProtocolUpdateError(f"schema must be {ENVELOPE_SCHEMA!r}")
    key_id = str(envelope.get("key_id") or "")
    if not key_id:
        raise ProtocolUpdateError("the envelope names no signing key")
    if not keyring:
        raise ProtocolUpdateError(
            "no trusted key is pinned, so no protocol update can be applied. "
            f"Add one to {LOCAL_KEYRING} (or ship it in "
            f"{BUNDLED_KEYRING.name}) - a signed update is only trustworthy "
            "against a key you chose in advance."
        )
    if key_id not in keyring:
        raise ProtocolUpdateError(
            f"the pack is signed by {key_id!r}, which is not in the trusted "
            f"keyring ({', '.join(sorted(keyring)) or 'empty'})"
        )
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ProtocolUpdateError("the envelope carries no payload")
    message = canonical_json(payload)
    signature = str(envelope.get("signature") or "")
    if not verify_signature(message, signature, keyring[key_id]):
        raise ProtocolUpdateError(
            f"the signature does not verify against {key_id!r}: the pack was "
            "edited, or it was signed with a different key"
        )
    digest = hashlib.sha256(message).hexdigest()
    claimed = str(envelope.get("payload_sha256") or "")
    if claimed and claimed != digest:
        raise ProtocolUpdateError(
            "the envelope's own digest does not match its payload"
        )
    validate_pack(payload, now=now)
    return {
        "pack": payload,
        "key_id": key_id,
        "sha256": digest,
        "signature_verified": True,
    }


# -------------------------------------------------------------------- fetches


def fetch_pack(url: str | None = None, *, timeout: float = MAX_FETCH_SECONDS) -> dict:
    """Download an envelope. HTTPS or a local file; nothing else."""
    url = (url or DEFAULT_PACK_URL).strip()
    if not url:
        raise ProtocolUpdateError("no protocol update URL is configured")
    if url.startswith("file://"):
        try:
            raw = Path(url[len("file://"):]).expanduser().read_bytes()
        except OSError as exc:
            raise ProtocolUpdateError(f"could not read {url}: {exc}") from exc
    elif "://" not in url:
        try:
            raw = Path(url).expanduser().read_bytes()
        except OSError as exc:
            raise ProtocolUpdateError(f"could not read {url}: {exc}") from exc
    elif url.startswith("https://"):
        request = urllib.request.Request(
            url, headers={"User-Agent": f"GuzziOnBoard/{__version__}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_PACK_BYTES + 1)
        except (urllib.error.URLError, OSError) as exc:
            raise ProtocolUpdateError(f"could not fetch {url}: {exc}") from exc
    else:
        raise ProtocolUpdateError(
            "protocol updates must come over HTTPS (or from a local file); "
            f"refusing {url!r}"
        )
    if len(raw) > MAX_PACK_BYTES:
        raise ProtocolUpdateError(
            f"the pack is larger than {MAX_PACK_BYTES} bytes; refusing it"
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolUpdateError(f"{url}: not a protocol update envelope ({exc})") from exc


# --------------------------------------------------------------- application


def _directory(directory: str | Path | None) -> Path:
    return Path(directory) if directory is not None else DEFAULT_DIR


def _applied_record(directory: Path) -> dict:
    path = directory / "applied.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _applied_digest(record: dict) -> str:
    return str((record.get("pack") or {}).get("sha256") or "")


def _applied_sequence(record: dict) -> int:
    try:
        return int((record.get("pack") or {}).get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def keyring(directory: str | Path | None = None) -> dict[str, str]:
    """The trusted public keys: bundled first, then operator-pinned."""
    directory = _directory(directory)
    keys: dict[str, str] = {}
    for path in (BUNDLED_KEYRING, directory / "keys.json"):
        try:
            keys.update(load_keyring(path))
        except SignatureError as exc:                      # pragma: no cover
            raise ProtocolUpdateError(str(exc)) from exc
    return keys


def catalog_fingerprints(ecu_ids: list[str]) -> dict[str, str]:
    """The SHA-256 of each named family definition as installed locally."""
    from .catalog import source_fingerprint

    out: dict[str, str] = {}
    for ecu_id in ecu_ids:
        try:
            out[ecu_id] = source_fingerprint(ecu_id)
        except Exception:                                  # pragma: no cover
            continue
    return out


def defined_parameter_keys(ecu_id: str) -> set[str] | None:
    """Live-data keys the *shipped* definition of a family declares.

    ``None`` means the family is not in this catalog at all (the fingerprint
    check owns that refusal); an empty set means the family exists and declares
    no live data, so no parameter promotion can be carried out for it.
    """
    from .catalog import load_catalog

    try:
        profile = load_catalog(overlays=False).ecu(ecu_id)
    except Exception:
        return None
    return {param.key for param in profile.live_parameters}


def unmatched_parameter_promotions(pack: dict) -> list[dict]:
    """Promoted live parameters the *shipped* definitions do not declare.

    A promotion the catalog cannot carry out is not a promotion: it would show
    up in the preview as a change and quietly do nothing, so both the maintainer
    tool (before signing) and the install (before applying) refuse it. Families
    with no declared live data at all are reported as ``declares: 0``.
    """
    unmatched: list[dict] = []
    for promotion in pack.get("promotions") or []:
        ecu = str(promotion.get("ecu") or "")
        known = defined_parameter_keys(ecu)
        if known is None:                     # family is not in this catalog
            continue
        for effect in promotion.get("effects") or []:
            if effect.get("target") != "parameter_confidence":
                continue
            value = effect.get("value")
            key = str((value or {}).get("key") or "") if isinstance(value, dict) else ""
            if key and key not in known:
                unmatched.append(
                    {
                        "ecu": ecu,
                        "claim": str(promotion.get("claim") or ""),
                        "parameter": key,
                        "declares": len(known),
                    }
                )
    return unmatched


def _undefined_parameters(pack: dict) -> list[str]:
    return [
        f"{entry['ecu']}/{entry['claim']}: {entry['parameter']!r}"
        for entry in unmatched_parameter_promotions(pack)
    ]


def check_envelope(
    envelope: dict,
    *,
    directory: str | Path | None = None,
    now: float | None = None,
) -> dict:
    """Verify a pack and describe exactly what applying it would change.

    Applying is a second, explicit step (:func:`apply_pack`) that must quote
    the digest returned here, so a stale preview cannot be applied to a
    different pack.
    """
    directory = _directory(directory)
    verified = verify_envelope(envelope, keyring(directory), now=now)
    pack = verified["pack"]
    local = catalog_fingerprints(sorted(pack["base"]["catalog_fingerprints"]))
    stale = {
        ecu: {"expected_by_pack": want, "installed": local.get(ecu, "missing")}
        for ecu, want in pack["base"]["catalog_fingerprints"].items()
        if local.get(ecu) != want
    }
    applied = _applied_record(directory)
    same_as_applied = _applied_digest(applied) == verified["sha256"]
    if _applied_sequence(applied) >= pack["sequence"] and not same_as_applied:
        raise ProtocolUpdateError(
            f"pack sequence {pack['sequence']} is not newer than the applied "
            f"sequence {_applied_sequence(applied)}; refusing a replayed pack"
        )
    if stale and not same_as_applied:
        detail = ", ".join(
            f"{ecu}: pack expects {v['expected_by_pack'][:12]}…, "
            f"installed {str(v['installed'])[:12]}…"
            for ecu, v in stale.items()
        )
        raise ProtocolUpdateError(
            "this pack was reviewed against a different catalog revision than "
            f"the one installed ({detail}). Update the application, or wait for "
            "a pack built against this release - a promotion is never applied "
            "to a definition it did not review."
        )
    undefined = _undefined_parameters(pack)
    if undefined and not same_as_applied:
        raise ProtocolUpdateError(
            "this pack promotes live parameters that this catalog revision does "
            "not define for the family (" + "; ".join(undefined) + "). Nothing "
            "was changed: a promotion the definitions cannot carry out is not a "
            "promotion. Ask for a pack built against the installed catalog."
        )
    distinct_captures = {
        reference["capture_sha256"]
        for promotion in pack["promotions"]
        for reference in promotion["references"]
    }
    return {
        "ok": True,
        "pack": {
            "id": pack["id"],
            "sequence": pack["sequence"],
            "issued_at": pack["issued_at"],
            "expires_at": pack["expires_at"],
            "reviewer": pack.get("reviewer", ""),
            "quorum": pack.get("quorum", 2),
            "notes": pack.get("notes", ""),
            "rules": pack.get("rules", ""),
        },
        "key_id": verified["key_id"],
        "sha256": verified["sha256"],
        "signature_verified": True,
        "already_applied": same_as_applied,
        "changes": [
            {
                "ecu": promotion["ecu"],
                "claim": promotion["claim"],
                "confirmations": len(promotion["references"]),
                "effects": [
                    f"{e['target']}={e.get('value')}" for e in promotion["effects"]
                ],
                "evidence_note": promotion.get("evidence_note", ""),
            }
            for promotion in pack["promotions"]
        ],
        "message": (
            "Signed by a pinned key, reviewed against this catalog revision, "
            f"and built from {len(distinct_captures)} independent field "
            "confirmation(s). Read-level promotions only."
        ),
    }


def apply_pack(
    envelope: dict,
    *,
    expected_sha256: str,
    directory: str | Path | None = None,
    now: float | None = None,
) -> dict:
    """Verify, then store the pack as this install's applied promotion set."""
    directory = _directory(directory)
    preview = check_envelope(envelope, directory=directory, now=now)
    if not expected_sha256 or expected_sha256 != preview["sha256"]:
        raise ProtocolUpdateError(
            "the pack digest does not match the reviewed preview; re-run the "
            "check and confirm the digest you were shown"
        )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "applied").mkdir(exist_ok=True)
    digest = preview["sha256"]
    stored = directory / "applied" / f"{digest}.json"
    stored.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    record = {
        "schema": OVERLAY_SCHEMA,
        "pack": preview["pack"] | {"sha256": digest, "key_id": preview["key_id"]},
        "applied_at": _iso(_now(now)),
        "signature_verified": True,
        "envelope_file": f"applied/{digest}.json",
        # The promotion bodies travel verbatim from the signed payload: the
        # overlay is data, not prose this module retypes.
        "promotions": _overlay_promotions(envelope["payload"]),
        "preview": preview["changes"],
    }
    (directory / "applied.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"applied": True, **preview}


def _overlay_promotions(pack: dict) -> dict:
    """Fold a pack's per-claim promotions into per-ECU overlay entries."""
    overlay: dict[str, dict] = {}
    for promotion in pack["promotions"]:
        ecu = promotion["ecu"]
        entry = overlay.setdefault(
            ecu,
            {
                "capabilities_add": [],
                "capability_confidence": {},
                "parameter_confidence": {},
                "sources_add": [],
                "references": [],
                "effects": [],
                "physical_supported": False,
                "memory_read_supported": False,
                "evidence_note": promotion.get("evidence_note", ""),
            },
        )
        entry["references"].extend(promotion["references"])
        for effect in promotion["effects"]:
            target, value = effect["target"], effect.get("value")
            entry["effects"].append(f"{target}={json.dumps(value)}")
            if target == "capability" and value not in entry["capabilities_add"]:
                entry["capabilities_add"].append(value)
            elif target == "capability_confidence":
                entry["capability_confidence"][value["capability"]] = value["confidence"]
            elif target == "parameter_confidence":
                entry["parameter_confidence"][value["key"]] = value["confidence"]
            elif target == "source":
                entry["sources_add"].append(value)
            elif target == "session.physical_supported":
                entry["physical_supported"] = True
            elif target == "memory.read_supported":
                entry["memory_read_supported"] = True
    return overlay


def catalog_fragment(pack: dict, *, applied_at: str = "") -> dict[str, dict]:
    """The same promotions expressed as catalog-file edits.

    Two publication routes exist and they carry identical promotions: a signed
    pack (fast, for installs that opt in to fetching) and a catalog change
    committed to the repository (slow, but reaches every user in the next
    release and needs no trust infrastructure at all). This function produces
    the second one from the first, so the two can never disagree.
    """
    applied_at = applied_at or _iso(time.time())
    fragment: dict[str, dict] = {}
    for ecu, entry in _overlay_promotions(pack).items():
        references = entry["references"]
        captures = sorted(
            {str(r.get("capture_sha256")) for r in references if r.get("capture_sha256")}
        )
        fragment[ecu] = {
            "capabilities_add": list(entry["capabilities_add"]),
            "capability_confidence": dict(entry["capability_confidence"]),
            "parameter_confidence": dict(entry["parameter_confidence"]),
            "sources_add": list(entry["sources_add"]),
            "physical_supported": bool(entry["physical_supported"]),
            "memory_read_supported": bool(entry["memory_read_supported"]),
            "field_confirmation": {
                "pack": pack.get("id", ""),
                "key_id": "",
                "applied_at": applied_at,
                "independent_sessions": len(captures),
                "confirmation_ids": sorted(
                    {str(r.get("id")) for r in references if r.get("id")}
                ),
                "captures": captures,
                "note": (
                    "Promoted by a reviewed protocol update built from independent "
                    "field sessions on real hardware. Read-level only: no control "
                    "action, no confidence change, no write path."
                ),
            },
        }
    return fragment


def merge_catalog_fragment(raw: dict, fragment: dict) -> dict:
    """Merge one promotion fragment into a family's definition document."""
    merged = json.loads(json.dumps(raw))
    capabilities = list(merged.get("capabilities") or [])
    for name in fragment.get("capabilities_add") or []:
        if name not in capabilities:
            capabilities.append(name)
    merged["capabilities"] = capabilities

    levels = dict(merged.get("capability_confidence") or {})
    levels.update(fragment.get("capability_confidence") or {})
    if levels:
        merged["capability_confidence"] = levels

    if fragment.get("physical_supported"):
        session = dict(merged.get("session") or {})
        session["physical_supported"] = True
        session["physical_evidence_note"] = (
            "Physical use enabled by a reviewed protocol update built from "
            "independent field sessions on real hardware."
        )
        merged["session"] = session
    if fragment.get("memory_read_supported") and isinstance(merged.get("memory"), dict):
        merged["memory"] = {**merged["memory"], "read_supported": True}

    sources = list(merged.get("sources") or [])
    for source in fragment.get("sources_add") or []:
        if source not in sources:
            sources.append(source)
    merged["sources"] = sources

    merged["field_confirmation"] = dict(fragment.get("field_confirmation") or {})
    parameter_levels = fragment.get("parameter_confidence") or {}
    if parameter_levels:
        for parameter in merged.get("parameters") or []:
            if parameter.get("key") in parameter_levels:
                parameter["confidence"] = parameter_levels[parameter["key"]]
    return merged


def load_applied_overlay(
    directory: str | Path | None = None,
) -> tuple[dict | None, dict]:
    """The overlay in force, and a status honest enough to show in the UI.

    The signature is verified when a pack is *applied* (that is the moment the
    bytes cross a trust boundary). Every later start re-checks that the stored
    envelope is still the one that was verified - digest for digest - and says
    so, so a file edited after the fact is refused rather than trusted.
    """
    directory = _directory(directory)
    record = _applied_record(directory)
    if not record:
        return None, {"state": "none", "detail": "No protocol update is applied."}
    envelope_file = directory / str(record.get("envelope_file") or "")
    if not envelope_file.is_file():
        return None, {
            "state": "refused",
            "reason": "the applied pack file is missing",
            "pack": record.get("pack", {}),
        }
    try:
        envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {
            "state": "refused",
            "reason": f"the applied pack is unreadable ({exc})",
            "pack": record.get("pack", {}),
        }
    digest = hashlib.sha256(canonical_json(envelope.get("payload") or {})).hexdigest()
    expected = str((record.get("pack") or {}).get("sha256") or "")
    if digest != expected or str(envelope.get("payload_sha256") or "") not in ("", digest):
        return None, {
            "state": "refused",
            "reason": (
                "the applied pack no longer matches the digest that was "
                "verified when it was applied; it has been edited since"
            ),
            "pack": record.get("pack", {}),
        }
    key_id = str((record.get("pack") or {}).get("key_id") or "")
    trusted = keyring(directory)
    if key_id and key_id not in trusted:
        return None, {
            "state": "refused",
            "reason": (
                f"the key {key_id!r} that signed this pack is no longer pinned "
                "in the trusted keyring"
            ),
            "pack": record.get("pack", {}),
        }
    if not record.get("signature_verified"):
        return None, {
            "state": "refused",
            "reason": "the applied record does not say the signature was verified",
            "pack": record.get("pack", {}),
        }
    overlay = {
        "schema": OVERLAY_SCHEMA,
        "pack": record.get("pack", {}),
        "applied_at": record.get("applied_at", ""),
        "promotions": {
            ecu: {**entry, "field_confirmation": _provenance(record, ecu)}
            for ecu, entry in (record.get("promotions") or {}).items()
        },
    }
    return overlay, {
        "state": "applied",
        "pack": record.get("pack", {}),
        "applied_at": record.get("applied_at", ""),
        "signature_verified": True,
        "promotions": {
            ecu: sorted(entry.get("effects", []))
            for ecu, entry in (record.get("promotions") or {}).items()
        },
        "detail": (
            "Read-level promotions were applied from a signed pack. The "
            "signature was verified at apply time; the stored envelope is "
            "checked against that digest on every start."
        ),
    }


def _provenance(record: dict, ecu: str) -> dict:
    entry = (record.get("promotions") or {}).get(ecu) or {}
    references = entry.get("references") or []
    # Every claim carries its own reference list, so de-duplicate by the thing
    # that makes a confirmation a *session*: its id and its capture.
    ids = sorted({str(r.get("id")) for r in references if r.get("id")})
    captures = sorted(
        {str(r.get("capture_sha256")) for r in references if r.get("capture_sha256")}
    )
    return {
        "pack": (record.get("pack") or {}).get("id", ""),
        "pack_sha256": (record.get("pack") or {}).get("sha256", ""),
        "key_id": (record.get("pack") or {}).get("key_id", ""),
        "applied_at": record.get("applied_at", ""),
        "independent_sessions": len(captures) or len(ids),
        "confirmation_ids": ids,
        "captures": captures,
        "note": (
            "Promoted by a signed protocol update, not by the shipped catalog: "
            "each confirmation's claim digest can be recomputed from the frozen "
            "capture named in the pack."
        ),
    }


def status(directory: str | Path | None = None) -> dict:
    """Everything the UI needs to be honest about protocol updates."""
    directory = _directory(directory)
    overlay, overlay_status = load_applied_overlay(directory)
    keys = {}
    for path in (BUNDLED_KEYRING, directory / "keys.json"):
        try:
            for name, value in load_keyring(path).items():
                keys[name] = value[:16] + "…"
        except SignatureError:                             # pragma: no cover
            continue
    return {
        "directory": str(directory),
        "source_url": DEFAULT_PACK_URL,
        "trusted_keys": keys,
        "bundled_keyring": str(BUNDLED_KEYRING),
        "local_keyring": str(directory / "keys.json"),
        "applied": bool(overlay),
        "applied_status": overlay_status,
        "pack_source": "signed-remote-pack" if overlay else "shipped-catalog",
        "note": (
            "Protocol updates carry read-level promotions only. Writing, "
            "control actions and a family's overall confidence are never "
            "changed by an update; those stay in the reviewed catalog."
        ),
        "how": (
            "Pin the release key (scripts/build_protocol_update.py --generate-key "
            "on the maintainer side), publish protocol-update.json as a release "
            "asset, then check for it here. An install that never fetches still "
            "gets promotions in the next application release."
        ),
    }


def revert(directory: str | Path | None = None) -> dict:
    """Forget the applied pack; the shipped catalog is in force again."""
    directory = _directory(directory)
    record = _applied_record(directory)
    if not record:
        return {"reverted": False, "reason": "no protocol update is applied"}
    names = [directory / "applied.json"]
    envelope_file = str(record.get("envelope_file") or "")
    if envelope_file:
        names.append(directory / envelope_file)
    for path in names:
        try:
            path.unlink()
        except OSError:
            pass
    return {
        "reverted": True,
        "pack": (record.get("pack") or {}).get("id", ""),
        "note": "The shipped catalog is in force again.",
    }


def pin_key(name: str, public_key_hex: str, directory: str | Path | None = None) -> dict:
    """Add a trusted public key to this install's keyring."""
    directory = _directory(directory)
    if not is_public_key(public_key_hex):
        raise ProtocolUpdateError("a public key is 64 hex characters")
    keys = load_keyring(directory / "keys.json")
    keys[name] = public_key_hex.lower()
    save_keyring(directory / "keys.json", keys)
    return {"pinned": name, "keys": sorted(keys), "path": str(directory / "keys.json")}


def unpin_key(name: str, directory: str | Path | None = None) -> dict:
    directory = _directory(directory)
    keys = load_keyring(directory / "keys.json")
    if name in keys:
        del keys[name]
        save_keyring(directory / "keys.json", keys)
    return {"pinned": sorted(keys), "removed": name}


__all__ = [
    "DEFAULT_PACK_URL",
    "EFFECT_TARGETS",
    "PACK_CAPABILITIES",
    "ProtocolUpdateError",
    "apply_pack",
    "build_update_pack",
    "check_envelope",
    "envelope_for",
    "fetch_pack",
    "keyring",
    "load_applied_overlay",
    "pack_digest",
    "pin_key",
    "revert",
    "status",
    "unpin_key",
    "validate_pack",
    "verify_envelope",
]
