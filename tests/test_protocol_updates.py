"""The field-confirmation -> protocol-update pipeline, end to end.

The behaviour these tests pin is the whole point of the feature:

* a simulated session confirms nothing;
* a bundle is only worth something if its claims can be recomputed from the
  capture that travels with it;
* one machine, one session or one edited bundle cannot change the catalog for
  everybody - independence and quorum are enforced before signing;
* a pack only applies against the catalog revision it was reviewed on, and
  only while its signature verifies against a key pinned in advance;
* no pack can enable writing, control actions or a confidence promotion,
  whatever it asks for;
* once applied, the *catalog the app loads* really does reflect the promotion,
  which is what makes it show up for every user out of one file.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from guzzionboard import confirmations, protocol_updates, signing
from guzzionboard.catalog import load_catalog

SEED_A = "11" * 32
SEED_B = "22" * 32


# ------------------------------------------------------------------ fixtures


def session_log(
    *,
    transport: str = "kline",
    ecu: str = "7sm",
    family: str = "IAW 7SM",
    model: str = "California 1400",
    year: int = 2015,
    handshake_ok: bool = True,
    identify: bool = True,
    live_keys: tuple[str, ...] = (),
    # ^ only keys the family actually declares: a 7SM session cannot
    #   produce live samples, and a pack that promotes them is refused.
    samples: int = 3,
    dtc_read: bool = False,
    memory_read: bool = False,
    write: bool = False,
    error: str = "",
    seed: int = 0,
) -> bytes:
    """A session log shaped exactly like the workstation writes one.

    ``seed`` shifts every timestamp and raw byte, which is how the tests build
    two *independent* sessions instead of re-submitting identical evidence.
    """
    shift = seed * 0.001
    lines = [
        {
            "t": 1.0,
            "kind": "session_start",
            "id": "abcd1234",
            "meta": {
                "app_version": "0.3.0",
                "model": model,
                "year": year,
                "ecu": ecu,
                "ecu_family": family,
                "transport": transport,
                "mode": "read_only" if transport != "simulator" else "simulator",
            },
        },
        {"t": 1.1 + shift, "kind": "frame", "dir": "tx", "hex": "81 10 f1 81 05"},
        {"t": 1.2 + shift, "kind": "frame", "dir": "rx", "hex": "80 f1 10 41 05 c4"},
        {
            "t": 1.3,
            "kind": "action",
            "name": "connect",
            "detail": {
                "transport": transport,
                "ecu": ecu,
                "init": "fast",
                "protocol": "iso14230",
                "ok": handshake_ok,
                "detail": "StartCommunication accepted" if handshake_ok else "timeout",
                "attempts": 1,
            },
        },
    ]
    if identify:
        lines += [
            {"t": 1.4 + shift, "kind": "frame", "dir": "tx", "hex": "83 10 f1 1a 80 1a"},
            {
                "t": 1.5,
                "kind": "frame",
                "dir": "rx",
                "hex": "88 f1 10 5a 80 49 41 57 20 37 53 4d" if not seed else "88 f1 10 5a 80 49 41 57 20 37 53 4e",
            },
            {
                "t": 1.6,
                "kind": "action",
                "name": "identify",
                "detail": {
                    "fields": {
                        "Drawing": "IAW7SMHW100",
                        "Hardware": "HW100",
                        "Software": "7SMAAHW100",
                    }
                },
            },
        ]
    for index in range(samples):
        for key in live_keys:
            lines.append(
                {
                    "t": 2.0 + index + shift,
                    "kind": "sample",
                    "key": key,
                    "lid": 0x30 if key == "rpm" else 0x21,
                    "raw": f"{index + 1 + seed:02x}10",
                    "value": index + 1,
                    "unit": "rpm" if key == "rpm" else "\u00b0C",
                }
            )
    if dtc_read:
        lines += [
            {"t": 3.0 + shift, "kind": "frame", "dir": "tx", "hex": "82 10 f1 18 02"},
            {
                "t": 3.1,
                "kind": "action",
                "name": "read_dtcs",
                "detail": {"count": 0, "dtcs": [], "context": {}},
            },
        ]
    if memory_read:
        lines.append(
            {
                "t": 4.0,
                "kind": "action",
                "name": "memory_read_complete",
                "detail": {
                    "region": "flash",
                    "size": 311296,
                    "sha256": "ab" * 32,
                    "duration_s": 20.0,
                },
            }
        )
    if write:
        lines.append(
            {"t": 5.0, "kind": "action", "name": "write", "detail": {"ok": True}}
        )
    if error:
        lines.append({"t": 6.0, "kind": "error", "where": "live", "message": error})
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode()


def bundle_for(
    tmp_path: Path,
    *,
    install: str,
    capture: bytes | None = None,
    ecu: str = "7sm",
    **kwargs,
) -> tuple[dict, bytes]:
    profile = load_catalog(overlays=False).ecu(ecu)
    seed = kwargs.pop("seed", 0)
    capture = capture if capture is not None else session_log(ecu=ecu, seed=seed, **kwargs)
    bundle = confirmations.build_confirmation(
        profile=profile,
        capture=capture,
        transport="kline",
        install=install,
        created_at=time.time(),
    )
    return bundle, capture


def pair(tmp_path: Path, **kwargs) -> list[tuple[dict, bytes]]:
    """Two independent field confirmations of the same session shape."""
    first, capture_first = bundle_for(tmp_path, install="a" * 32, seed=0, **kwargs)
    second, capture_second = bundle_for(tmp_path, install="b" * 32, seed=1, **kwargs)
    return [(first, capture_first), (second, capture_second)]


def pack_for(tmp_path: Path, session: dict | None = None, **build_kwargs) -> dict:
    return protocol_updates.build_update_pack(pair(tmp_path, **(session or {})),
                                              **build_kwargs)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private HOME, so nothing touches a developer's real ~/.guzzionboard."""
    monkeypatch.setattr(confirmations, "DEFAULT_DIR", tmp_path / "confirmations")
    monkeypatch.setattr(confirmations, "INSTALL_FILE", tmp_path / "install.json")
    monkeypatch.setattr(protocol_updates, "DEFAULT_DIR", tmp_path / "protocol")
    monkeypatch.setattr(protocol_updates, "LOCAL_KEYRING", tmp_path / "protocol" / "keys.json")
    return tmp_path


def sign(pack, seed=SEED_A, key_id="release"):
    return protocol_updates.envelope_for(pack, seed=seed, key_id=key_id)


def pin(tmp_path: Path, envelope: dict, key_id: str = "release") -> dict:
    directory = tmp_path / "protocol"
    directory.mkdir(parents=True, exist_ok=True)
    keys = signing.load_keyring(directory / "keys.json")
    keys[key_id] = envelope["public_key"]
    signing.save_keyring(directory / "keys.json", keys)
    return keys


# --------------------------------------------------------- the capture half


def test_a_simulated_session_cannot_become_a_confirmation():
    profile = load_catalog(overlays=False).ecu("5am")
    with pytest.raises(confirmations.ConfirmationError, match="simulated"):
        confirmations.build_confirmation(
            profile=profile,
            capture=session_log(transport="simulator", ecu="5am", family="IAW 5AM"),
            transport="simulator",
        )


def test_claims_are_derived_from_the_recorded_events_only():
    events = confirmations.parse_capture(
        session_log(dtc_read=True, memory_read=True, live_keys=("rpm", "coolant_temp"))
    )
    claims = confirmations.derive_claims(events)
    assert set(claims) >= {"handshake", "identify", "live", "dtc_read", "memory_read"}
    # the handshake claim carries its protocol and its frames
    assert claims["handshake"]["protocol"] == "iso14230"
    assert claims["handshake"]["frames"] >= 2
    # live keeps per-channel evidence, with raw bytes
    assert claims["live"]["keys"] == ["coolant_temp", "rpm"]
    assert claims["live"]["per_key"]["rpm"]["raw_samples"] == 3
    # every digest is a SHA-256
    for claim in claims.values():
        assert len(claim["digest"]) == 64


def test_a_write_in_the_capture_is_recorded_but_never_claimable():
    events = confirmations.parse_capture(session_log(write=True))
    claims = confirmations.derive_claims(events)
    assert not any(claim.startswith("write") for claim in claims)
    observed = confirmations.observed_only(events)
    assert "write" in observed["not_claimable"]
    assert "never enable those operations" in observed["note"]


def test_a_bundle_reproduces_from_its_capture_and_fails_when_edited(tmp_path):
    bundle, capture = bundle_for(
        tmp_path, install="a" * 32, live_keys=("rpm", "coolant_temp")
    )
    report = confirmations.verify_confirmation(bundle, capture)
    assert report["ok"] and report["ecu"] == "7sm"

    edited = json.loads(json.dumps(bundle))
    edited["claims"]["live"]["digest"] = "00" * 32
    with pytest.raises(confirmations.ConfirmationError, match="does not reproduce"):
        confirmations.verify_confirmation(edited, capture)

    other = session_log(live_keys=("rpm",), samples=1)
    with pytest.raises(confirmations.ConfirmationError, match="does not match"):
        confirmations.verify_confirmation(bundle, other)


def test_a_bundle_carries_no_identifier_and_a_simulator_bundle_is_refused():
    bundle, _ = bundle_for(Path("/tmp"), install="b" * 32)
    text = json.dumps(bundle)
    assert "California" not in text                    # the bike stays private
    for key in ("vin", "serial", "owner", "email", "address", "plate"):
        assert key not in bundle
    assert bundle["install"]["anonymous"] is True
    assert bundle["fitment"] == {}
    # the ECU's own part numbers are evidence, and they are kept
    assert bundle["session"]["identity"]["Software"] == "7SMAAHW100"

    simulated = json.loads(json.dumps(bundle))
    simulated["session"]["transport"] = "simulator"
    with pytest.raises(confirmations.ConfirmationError, match="simulated"):
        confirmations.validate_bundle(simulated)


def test_incomplete_sessions_are_honest_about_it():
    bundle, capture = bundle_for(
        Path("/tmp"), install="c" * 32, handshake_ok=False
    )
    assert bundle["verdict"] == "incomplete"
    assert "handshake" in bundle["verdict_reason"]
    confirmations.verify_confirmation(bundle, capture)   # still reproducible


def test_the_submission_is_a_link_the_operator_drives():
    bundle, _ = bundle_for(Path("/tmp"), install="d" * 32)
    submission = confirmations.submission(bundle)
    assert submission["url"].startswith(confirmations.SUBMIT_URL)
    assert "nothing is uploaded" in submission["note"].lower()
    assert bundle["id"] in submission["body"]
    assert bundle["session"]["capture_sha256"] in submission["body"]


def test_the_issue_template_the_submission_points_at_exists():
    """The link in the UI opens a form; the form has to be in the repository."""
    root = Path(__file__).resolve().parent.parent
    template = root / ".github" / "ISSUE_TEMPLATE" / confirmations.SUBMIT_TEMPLATE
    assert template.is_file(), template
    text = template.read_text(encoding="utf-8")
    assert ".session.jsonl" in text          # tells the operator to attach the capture
    assert "simulator" in text               # and that a simulated session is out


# ----------------------------------------------------- aggregation and rules


def test_quorum_and_independence_are_enforced(tmp_path):
    live = {"live_keys": ("rpm", "coolant_temp")}
    one, capture_one = bundle_for(tmp_path, install="a" * 32, seed=0, **live)
    two, capture_two = bundle_for(tmp_path, install="b" * 32, seed=1, samples=5, **live)

    with pytest.raises(protocol_updates.ProtocolUpdateError, match="no confirmations"):
        protocol_updates.build_update_pack([])
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="quorum must be at least 2"):
        protocol_updates.build_update_pack([(one, capture_one)], quorum=1)
    # one confirmation is not a consensus
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="nothing reached quorum"):
        protocol_updates.build_update_pack([(one, capture_one)])
    # a capture that is not the bundle's own capture is not evidence
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="no confirmation passed"):
        protocol_updates.build_update_pack([(one, capture_two)])
    # the same install submitting two sessions is one voice, not two
    same_install_a, capture_a = bundle_for(tmp_path, install="a" * 32, seed=2, **live)
    same_install_b, capture_b = bundle_for(tmp_path, install="a" * 32, seed=3, **live)
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="not independent"):
        protocol_updates.build_update_pack([(same_install_a, capture_a),
                                           (same_install_b, capture_b)])
    pack = protocol_updates.build_update_pack(
        [(one, capture_one), (two, capture_two), (same_install_a, capture_a)]
    )
    assert pack["schema"] == protocol_updates.SCHEMA
    keys = {p["claim"] for p in pack["promotions"]}
    assert {"handshake", "identify", "live"} <= keys
    assert pack["base"]["catalog_fingerprints"]["7sm"]
    # quorum is the floor, not the ceiling: a third voice is counted too
    for promotion in pack["promotions"]:
        assert len(promotion["references"]) >= 2


def test_a_reviewer_can_withhold_a_claim_and_disputes_stop_a_promotion(tmp_path):
    pack = protocol_updates.build_update_pack(
        pair(tmp_path, live_keys=("rpm", "coolant_temp")), withhold=("7sm/live",)
    )
    assert "7sm/live" not in {p["claim"] for p in pack["promotions"]}
    assert any(r["claim"] == "live" for r in pack["refused"])

    disputed, capture_disputed = bundle_for(tmp_path, install="c" * 32, seed=4)
    disputed["disputes"] = ["live"]
    pack = protocol_updates.build_update_pack(
        pair(tmp_path) + [(disputed, capture_disputed)]
    )
    assert all(p["claim"] != "live" for p in pack["promotions"])


def test_a_pack_can_only_grant_read_level_things(tmp_path):
    pack = pack_for(tmp_path, session={"dtc_read": True})
    targets = {
        effect["target"] for promotion in pack["promotions"] for effect in promotion["effects"]
    }
    assert targets <= set(protocol_updates.EFFECT_TARGETS)

    for target, value in (
        ("capability", "memory_write"),
        ("memory.write_supported", True),
        ("capability", "actuators"),
        ("capability", "discover"),
        ("session.confidence", "verified-bench"),
        ("programming.enabled", True),
    ):
        forged = json.loads(json.dumps(pack))
        forged["promotions"][0]["effects"].append({"target": target, "value": value})
        with pytest.raises(protocol_updates.ProtocolUpdateError):
            protocol_updates.validate_pack(forged)


def test_parameter_promotion_needs_the_channels_everyone_saw(tmp_path):
    confirmations_in = [
        bundle_for(tmp_path, install="a" * 32, seed=0,
                   live_keys=("rpm", "coolant_temp")),
        bundle_for(tmp_path, install="b" * 32, seed=1, live_keys=("rpm",)),
    ]
    pack = protocol_updates.build_update_pack(confirmations_in)
    promoted = {
        effect["value"]["key"]
        for promotion in pack["promotions"]
        if promotion["claim"] == "live"
        for effect in promotion["effects"]
        if effect["target"] == "parameter_confidence"
    }
    assert promoted == {"rpm"}       # only the channel both sessions saw


def test_an_edited_bundle_is_rejected_before_it_can_be_aggregated(tmp_path):
    honest = pair(tmp_path)
    edited = json.loads(json.dumps(honest[0][0]))
    edited["claims"]["identify"]["events"] = 99
    pack = protocol_updates.build_update_pack(honest + [(edited, honest[0][1])])
    # the edited bundle is dropped before it can vote, and the pack says so
    assert any(
        entry["id"] == edited["id"] and "does not reproduce" in entry["reason"]
        for entry in pack["rejected"]
    )
    for promotion in pack["promotions"]:
        assert len(promotion["references"]) == 2
    # a pack built from *only* tampered bundles does not exist at all
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="no confirmation passed"):
        protocol_updates.build_update_pack([(edited, honest[0][1])])


# -------------------------------------------------------- signature and trust


def test_a_pack_needs_a_signature_from_a_key_pinned_in_advance(tmp_path, home):
    pack = pack_for(tmp_path)

    # nothing pinned -> every pack is refused, including a genuine one
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="no trusted key"):
        protocol_updates.verify_envelope(sign(pack), {})

    # pinned -> accepted
    envelope = sign(pack)
    keys = pin(tmp_path, envelope)
    verified = protocol_updates.verify_envelope(envelope, keys)
    assert verified["signature_verified"] is True

    # a different key signing the same pack is refused
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="not in the trusted"):
        protocol_updates.verify_envelope(sign(pack, seed=SEED_B, key_id="impostor"), keys)

    # the same key id, but the payload edited after signing
    tampered = json.loads(json.dumps(envelope))
    tampered["payload"]["promotions"][0]["effects"].append(
        {"target": "capability", "value": "memory_write"}
    )
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="signature does not verify"):
        protocol_updates.verify_envelope(tampered, keys)


def test_an_expired_or_replayed_pack_is_refused(tmp_path, home):
    pack = pack_for(tmp_path, sequence=4, valid_days=10)
    envelope = sign(pack)
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"

    applied = protocol_updates.apply_pack(
        envelope, expected_sha256=protocol_updates.check_envelope(envelope, directory=directory)["sha256"],
        directory=directory,
    )
    assert applied["applied"] is True
    # applying the same pack again is idempotent, not a downgrade
    again = protocol_updates.check_envelope(envelope, directory=directory)
    assert again["already_applied"] is True
    # an older sequence with different content is a replay
    old = sign(pack_for(tmp_path, sequence=2))
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="replayed"):
        protocol_updates.check_envelope(old, directory=directory)
    # the builder will not even sign a pack that has already expired ...
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="expired"):
        sign(
            pack_for(tmp_path, sequence=9, issued_at=time.time() - 400 * 86400,
                     valid_days=1)
        )
    # ... and one that expired after signing is refused at check time
    stale = pack_for(tmp_path, sequence=9)
    stale["issued_at"] = protocol_updates._iso(time.time() - 30 * 86400)
    stale["expires_at"] = protocol_updates._iso(time.time() - 86400)
    expired = {
        "schema": protocol_updates.ENVELOPE_SCHEMA,
        "key_id": "release",
        "public_key": signing.public_key(SEED_A),
        "payload": stale,
        "signature": signing.sign(signing.canonical_json(stale), SEED_A),
        "payload_sha256": protocol_updates.pack_digest(stale),
    }
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="expired"):
        protocol_updates.check_envelope(expired, directory=directory)


def test_a_pack_reviewed_against_another_catalog_revision_is_refused(tmp_path, home):
    pack = pack_for(tmp_path)
    pack["base"]["catalog_fingerprints"]["7sm"] = "f" * 64
    envelope = sign(pack)
    pin(tmp_path, envelope)
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="different catalog revision"):
        protocol_updates.check_envelope(envelope, directory=tmp_path / "protocol")


def test_applying_requires_the_digest_that_was_previewed(tmp_path, home):
    envelope = sign(pack_for(tmp_path))
    pin(tmp_path, envelope)
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="does not match the reviewed preview"):
        protocol_updates.apply_pack(
            envelope, expected_sha256="0" * 64, directory=tmp_path / "protocol"
        )


# ----------------------------------------------------------- the payoff: users


def test_applying_a_pack_changes_what_every_install_loads(tmp_path, home):
    """The point of the whole exercise: one signed file, every install's catalog.

    The 7SM ships identification only, and a real 7SM session cannot produce
    live samples (the catalog declares no 7SM parameters), so the field claim
    that is exercised here is the one such a session can actually make: reading
    fault codes.
    """
    before = load_catalog(overlays=False).ecu("7sm")
    assert before.session.get("physical_supported") is True
    assert "dtc_read" not in before.capabilities
    assert before.confidence == "inferred"
    assert before.supports("dtc_read") is False

    pack = pack_for(tmp_path, session={"dtc_read": True})
    envelope = sign(pack)
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"
    preview = protocol_updates.check_envelope(envelope, directory=directory)
    protocol_updates.apply_pack(
        envelope, expected_sha256=preview["sha256"], directory=directory
    )

    load_catalog.cache_clear()
    try:
        after = load_catalog().ecu("7sm")
        assert "dtc_read" in after.capabilities
        assert "identify" in after.capabilities
        assert after.supports("dtc_read")
        assert after.capability_level("dtc_read") == "verified-bench"
        assert after.capability_level("identify") == "verified-bench"
        # the family's own confidence is untouched, so control actions stay gated
        assert after.confidence == "inferred"
        assert not after.supports("dtc_clear")
        assert not after.supports("live")
        # and the promotion carries its provenance
        confirmation = after.field_confirmation
        assert confirmation["independent_sessions"] == 2
        assert confirmation["pack"] == pack["id"]
        assert len(confirmation["captures"]) == 2
        assert any("Verified protocol update" in source for source in after.sources)
        # the shipped definition on disk was not rewritten
        assert after.memory == load_catalog().ecu("7sm").memory
    finally:
        load_catalog.cache_clear()

    # an install that has not applied it still sees the shipped catalog
    assert "dtc_read" not in load_catalog(overlays=False).ecu("7sm").capabilities


def test_a_promotion_never_enables_writing(tmp_path, home):
    pack = pack_for(tmp_path, session={"memory_read": True})
    envelope = sign(pack)
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"
    preview = protocol_updates.check_envelope(envelope, directory=directory)
    protocol_updates.apply_pack(
        envelope, expected_sha256=preview["sha256"], directory=directory
    )
    load_catalog.cache_clear()
    try:
        after = load_catalog().ecu("7sm")
        assert after.memory.get("read_supported") is True
        assert after.memory.get("write_supported") is False
        assert not after.supports("memory_write")
        assert "memory_write" not in after.capabilities
    finally:
        load_catalog.cache_clear()


def test_a_tampered_overlay_is_refused_at_load_time(tmp_path, home):
    envelope = sign(pack_for(tmp_path))
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"
    preview = protocol_updates.check_envelope(envelope, directory=directory)
    protocol_updates.apply_pack(
        envelope, expected_sha256=preview["sha256"], directory=directory
    )
    assert protocol_updates.status(directory)["applied"] is True

    # somebody edits the stored pack after it was applied
    stored = next((directory / "applied").glob("*.json"))
    edited = json.loads(stored.read_text())
    edited["payload"]["promotions"][0]["effects"].append(
        {"target": "capability", "value": "memory_read"}
    )
    stored.write_text(json.dumps(edited))

    overlay, status = protocol_updates.load_applied_overlay(directory)
    assert overlay is None
    assert status["state"] == "refused"
    assert "edited since" in status["reason"]
    load_catalog.cache_clear()
    try:
        assert "live" not in load_catalog().ecu("7sm").capabilities
    finally:
        load_catalog.cache_clear()


def test_reverting_puts_the_shipped_catalog_back(tmp_path, home):
    envelope = sign(pack_for(tmp_path))
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"
    protocol_updates.apply_pack(
        envelope,
        expected_sha256=protocol_updates.check_envelope(envelope, directory=directory)["sha256"],
        directory=directory,
    )
    result = protocol_updates.revert(directory)
    assert result["reverted"] is True
    load_catalog.cache_clear()
    try:
        assert "live" not in load_catalog().ecu("7sm").capabilities
    finally:
        load_catalog.cache_clear()


def test_reverting_tolerates_a_record_that_names_no_envelope(tmp_path, home):
    """Older or hand-edited applied records must not break the way back out."""
    directory = tmp_path / "protocol"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "applied.json").write_text(json.dumps({
        "pack": {"id": "pack-old", "sequence": 1, "sha256": "a" * 64},
    }))
    result = protocol_updates.revert(directory)
    assert result["reverted"] is True and result["pack"] == "pack-old"
    assert not (directory / "applied.json").exists()


def test_status_explains_itself_and_fetches_are_bounded(tmp_path, home):
    status = protocol_updates.status(tmp_path / "protocol")
    assert status["applied"] is False
    assert "read-level promotions only" in status["note"]
    assert "release asset" in status["how"]

    with pytest.raises(protocol_updates.ProtocolUpdateError, match="HTTPS"):
        protocol_updates.fetch_pack("http://example.invalid/pack.json")
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="could not fetch"):
        protocol_updates.fetch_pack("https://127.0.0.1:9/none.json", timeout=0.5)

    path = tmp_path / "pack.json"
    path.write_text(json.dumps({"schema": protocol_updates.ENVELOPE_SCHEMA}))
    assert protocol_updates.fetch_pack(str(path))["schema"] == protocol_updates.ENVELOPE_SCHEMA


def test_an_operator_can_pin_a_key_without_touching_the_shipped_one(tmp_path, home):
    envelope = protocol_updates.envelope_for(
        {
            "schema": protocol_updates.SCHEMA,
            "id": "pu-test",
            "sequence": 1,
            "issued_at": protocol_updates._iso(time.time()),
            "expires_at": protocol_updates._iso(time.time() + 86400),
            "reviewer": "workshop",
            "quorum": 2,
            "generator": {"tool": "test", "version": "0"},
            "base": {"catalog_fingerprints": {"5am": "a" * 64}},
            "promotions": [
                {
                    "ecu": "5am",
                    "claim": "live",
                    "effects": [
                        {"target": "capability", "value": "live"},
                        {
                            "target": "capability_confidence",
                            "value": {"capability": "live", "confidence": "verified-bench"},
                        },
                    ],
                    "references": [
                        {"id": f"conf-{index:06x}"} for index in range(2)
                    ],
                }
            ],
        },
        seed=SEED_B,
        key_id="workshop",
    )
    directory = tmp_path / "protocol"
    protocol_updates.pin_key("workshop", envelope["public_key"], directory)
    keys = protocol_updates.keyring(directory)
    assert "workshop" in keys
    verified = protocol_updates.verify_envelope(envelope, keys)
    assert verified["pack"]["id"] == "pu-test"
    # pinning the key is enough to *check* the pack; the base fingerprint still
    # has to match the local catalog before it will apply
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="different catalog revision"):
        protocol_updates.check_envelope(envelope, directory=directory)
    protocol_updates.unpin_key("workshop", directory)
    assert "workshop" not in protocol_updates.keyring(directory)


def test_the_effect_allowlist_cannot_drift_into_control_actions():
    for target, rule in protocol_updates.EFFECT_TARGETS.items():
        lowered = target.lower()
        for token in ("write", "erase", "program", "actuator", "routine"):
            assert token not in lowered
        if rule["kind"] == "capability":
            assert set(protocol_updates.PACK_CAPABILITIES) == {
                "identify", "live", "dtc_read", "memory_read",
            }
    assert not any(
        token in " ".join(protocol_updates.PACK_CAPABILITIES)
        for token in ("write", "program")
    )


def test_a_promotion_the_definitions_cannot_carry_out_is_refused(tmp_path, home):
    """A pack may only list changes that actually happen.

    The 7SM declares no live parameters, so a pack that "promotes" an rpm
    channel for it would show up in the preview as a change and do nothing at
    all. That is refused rather than applied as a no-op.
    """
    pack = pack_for(tmp_path, session={"live_keys": ("rpm",)})
    unmatched = protocol_updates.unmatched_parameter_promotions(pack)
    assert unmatched == [
        {"ecu": "7sm", "claim": "live", "parameter": "rpm", "declares": 0}
    ]
    assert protocol_updates.defined_parameter_keys("7sm") == set()
    assert "rpm" in protocol_updates.defined_parameter_keys("5am")

    envelope = sign(pack)
    pin(tmp_path, envelope)
    directory = tmp_path / "protocol"
    with pytest.raises(
        protocol_updates.ProtocolUpdateError, match="does not define for the family"
    ):
        protocol_updates.check_envelope(envelope, directory=directory)
    # nothing was written, so nothing has to be undone
    assert protocol_updates.status(directory)["applied"] is False


# ------------------------------------------------- the other publication route


def test_the_catalog_fragment_route_carries_the_same_promotions(tmp_path, home):
    """A committed catalog change and a signed pack must never disagree.

    The 5AM is the family used here because it declares live parameters, so the
    parameter half of a promotion is exercised rather than skipped.
    """
    pack = pack_for(
        tmp_path,
        session={
            "ecu": "5am", "family": "IAW 5AM", "model": "Norge 1200", "year": 2012,
            "live_keys": ("rpm", "coolant_temp"), "memory_read": True,
        },
    )
    fragment = protocol_updates.catalog_fragment(pack, applied_at="2026-01-01T00:00:00Z")
    assert set(fragment) == {"5am"}
    change = fragment["5am"]
    assert change["field_confirmation"]["independent_sessions"] == 2
    assert change["field_confirmation"]["applied_at"] == "2026-01-01T00:00:00Z"
    assert set(change["capabilities_add"]) >= {"identify", "live", "memory_read"}
    assert change["parameter_confidence"]["rpm"] == "verified-bench"
    assert change["memory_read_supported"] is True
    assert change["physical_supported"] is True

    def read_raw() -> dict:
        return json.loads(
            (Path(protocol_updates.__file__).parent / "catalog" / "ecus" / "5am.json")
            .read_text(encoding="utf-8")
        )

    raw = read_raw()
    merged = protocol_updates.merge_catalog_fragment(raw, change)
    assert "live" in merged["capabilities"]
    assert merged["capability_confidence"]["live"] == "verified-bench"
    assert merged["session"]["physical_supported"] is True
    assert merged["memory"]["read_supported"] is True
    assert merged["field_confirmation"]["pack"] == pack["id"]
    assert any("Verified protocol update" in source for source in merged["sources"])
    # the two routes describe the same promotion
    overlay = protocol_updates._overlay_promotions(pack)
    assert sorted(overlay["5am"]["capabilities_add"]) == sorted(
        set(change["capabilities_add"])
    )
    # ... and the source document is untouched: this function is pure
    assert raw == read_raw()


def test_a_merged_catalog_file_loads_with_the_promotion_in_force(tmp_path, monkeypatch,
                                                                 home):
    from guzzionboard import catalog as catalog_mod

    work = tmp_path / "catalog"
    (work / "ecus").mkdir(parents=True)
    for path in (catalog_mod.CATALOG_DIR / "ecus").glob("*.json"):
        (work / "ecus" / path.name).write_bytes(path.read_bytes())
    for name in ("vehicles.json", "dtc_sae.json", "protocol_keys.json"):
        (work / name).write_bytes((catalog_mod.CATALOG_DIR / name).read_bytes())
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", work)
    monkeypatch.setattr(catalog_mod, "ECU_DIR", work / "ecus")

    pack = pack_for(tmp_path, session={"dtc_read": True})
    fragment = protocol_updates.catalog_fragment(pack)
    target = work / "ecus" / "7sm.json"
    merged = protocol_updates.merge_catalog_fragment(
        json.loads(target.read_text(encoding="utf-8")), fragment["7sm"]
    )
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    catalog_mod.load_catalog.cache_clear()
    try:
        profile = catalog_mod.load_catalog().ecu("7sm")
        assert profile.supports("dtc_read")
        assert profile.capability_level("dtc_read") == "verified-bench"
        assert profile.confidence == "inferred"
        assert profile.field_confirmation["pack"] == pack["id"]
        assert catalog_mod.source_fingerprint("7sm") != pack["base"][
            "catalog_fingerprints"
        ]["7sm"]              # the file genuinely changed
    finally:
        catalog_mod.load_catalog.cache_clear()


def test_the_maintainer_tool_builds_checks_and_refuses(tmp_path):
    """The CLI end to end: generate a key, build a pack, verify it."""
    import subprocess

    script = Path(__file__).resolve().parent.parent / "scripts" / "build_protocol_update.py"
    submitted = tmp_path / "submitted"
    submitted.mkdir()
    for index, marker in enumerate(("a" * 32, "b" * 32)):
        bundle, capture = bundle_for(tmp_path, install=marker, seed=index)
        (submitted / f"{bundle['id']}.json").write_text(json.dumps(bundle))
        (submitted / f"{bundle['id']}.session.jsonl").write_bytes(capture)

    def run(*args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, timeout=300,
        )

    keys = tmp_path / "keys"
    assert run("--generate-key", "release", "--key-dir", str(keys)).returncode == 0
    seed_file = keys / "release.seed"
    assert seed_file.is_file()
    assert oct(seed_file.stat().st_mode)[-3:] == "600"

    out = tmp_path / "dist" / "protocol-update.json"
    built = run(
        "--confirmations", str(submitted), "--reviewer", "the maintainer",
        "--seed-file", str(seed_file), "--key-id", "release",
        "--sequence", "7", "--out", str(out),
    )
    assert built.returncode == 0, built.stderr
    assert "independent confirmation(s)" in built.stdout
    assert "Review checklist" in built.stdout

    checked = run("--check", str(out), "--keys", str(keys / "release.pub.json"))
    assert checked.returncode == 0, checked.stderr
    assert "signature ok" in checked.stdout
    assert "catalog 7sm: matches" in checked.stdout

    # without a pinned key the tool refuses rather than guessing
    unpinned = run("--check", str(out))
    assert unpinned.returncode == 2
    assert "no trusted key" in unpinned.stderr

    # a pack built from a directory with no confirmations is refused
    empty = tmp_path / "nothing"
    empty.mkdir()
    refused = run("--confirmations", str(empty), "--seed-file", str(seed_file))
    assert refused.returncode != 0
    assert "no usable confirmations" in refused.stderr

    # a claim that promotes a parameter this catalog does not define is refused
    # before it is signed, so a pack cannot promise a change it cannot make
    fabricated = tmp_path / "fabricated"
    fabricated.mkdir()
    for index, marker in enumerate(("c" * 32, "d" * 32)):
        bundle, capture = bundle_for(
            tmp_path, install=marker, seed=10 + index, live_keys=("rpm",)
        )
        (fabricated / f"{bundle['id']}.json").write_text(json.dumps(bundle))
        (fabricated / f"{bundle['id']}.session.jsonl").write_bytes(capture)
    unmatched = run(
        "--confirmations", str(fabricated), "--seed-file", str(seed_file),
        "--out", str(tmp_path / "unused.json"),
    )
    assert unmatched.returncode == 2
    assert "refusing to sign" in unmatched.stderr
    assert "'rpm'" in unmatched.stderr and "declares 0 live parameter" in unmatched.stderr
    assert not (tmp_path / "unused.json").exists()
