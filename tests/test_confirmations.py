"""Field-confirmation bundles as files: build, store, list, re-verify.

The aggregation pipeline is covered in ``test_protocol_updates.py``. This file
is about the operator's side of the exchange: the bundle that lands in
``~/.guzzionboard/confirmations/``, the anonymous install marker that makes
independence judgeable, and the fact that a stored bundle can still be
recomputed byte-for-byte months later from the capture next to it.
"""
from __future__ import annotations

import json

import pytest

from guzzionboard import confirmations
from guzzionboard.catalog import load_catalog


def session_log(transport: str = "kline", *, ok: bool = True) -> bytes:
    lines = [
        {
            "t": 1.0,
            "kind": "session_start",
            "id": "abc123",
            "meta": {
                "app_version": "0.3.0",
                "ecu": "5am",
                "ecu_family": "IAW 5AM",
                "transport": transport,
                "mode": "read_only",
            },
        },
        {"t": 1.1, "kind": "frame", "dir": "tx", "hex": "81 10 f1 81 05"},
        {"t": 1.2, "kind": "frame", "dir": "rx", "hex": "80 f1 10 41 05 c4"},
        {
            "t": 1.3,
            "kind": "action",
            "name": "connect",
            "detail": {
                "transport": transport,
                "protocol": "iso14230",
                "init": "fast",
                "ok": ok,
                "attempts": 1,
            },
        },
        {
            "t": 1.4,
            "kind": "action",
            "name": "identify",
            "detail": {"fields": {"Drawing": "IAW5AMHW610", "Software": "5AMXXX"}},
        },
        {
            "t": 2.0,
            "kind": "sample",
            "key": "rpm",
            "lid": 0x30,
            "raw": "0110",
            "value": 1200,
            "unit": "rpm",
        },
    ]
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(confirmations, "DEFAULT_DIR", tmp_path / "confirmations")
    monkeypatch.setattr(confirmations, "INSTALL_FILE", tmp_path / "install.json")
    return tmp_path


def bundle(capture: bytes | None = None, install: str = "a" * 32) -> tuple[dict, bytes]:
    capture = capture if capture is not None else session_log()
    return (
        confirmations.build_confirmation(
            profile=load_catalog(overlays=False).ecu("5am"),
            capture=capture,
            transport="kline",
            install=install,
        ),
        capture,
    )


# -------------------------------------------------------------- the install id


def test_the_install_marker_is_stable_anonymous_and_replaceable(home):
    first = confirmations.install_id()
    assert first == confirmations.install_id()          # stable across calls
    assert len(first) == 32
    marker = confirmations.install_marker(first)
    assert len(marker) == 16 and first not in marker    # never the raw id

    replacement = confirmations.install_id(refresh=True)
    assert replacement != first
    assert confirmations.install_id() == replacement
    assert confirmations.install_marker(replacement) != marker

    # a corrupt install file is replaced rather than crashing a session
    confirmations.INSTALL_FILE.write_text("{not json")
    rebuilt = confirmations.install_id()
    assert len(rebuilt) == 32 and rebuilt != replacement


# ------------------------------------------------------------- stored bundles


def test_a_stored_bundle_and_its_capture_survive_a_round_trip(home):
    bundle_in, capture = bundle()
    stored = confirmations.save_confirmation(bundle_in, capture)
    assert stored["directory"] == str(confirmations.DEFAULT_DIR)

    listed = confirmations.list_confirmations()
    assert len(listed) == 1
    entry = listed[0]
    assert entry["id"] == bundle_in["id"]
    assert entry["ecu"] == "5am"
    assert entry["claims"] == sorted(bundle_in["claims"])

    reloaded = confirmations.load_bundle(stored["bundle_path"])
    frozen = confirmations.capture_for(reloaded, stored["directory"])
    assert frozen == capture
    report = confirmations.verify_confirmation(reloaded, frozen)
    assert report["ok"] and report["ecu"] == "5am"
    assert report["frames"] == 2


def test_a_bundle_without_its_capture_cannot_be_reviewed(home):
    bundle_in, capture = bundle()
    stored = confirmations.save_confirmation(bundle_in, capture)
    confirmations.capture_for(
        confirmations.load_bundle(stored["bundle_path"]), stored["directory"]
    )
    import os
    os.unlink(stored["capture_path"])
    with pytest.raises(confirmations.ConfirmationError, match="cannot be reviewed"):
        confirmations.capture_for(
            confirmations.load_bundle(stored["bundle_path"]), stored["directory"]
        )
    assert confirmations.list_confirmations()                # the bundle is still listed


def test_an_unreadable_confirmation_is_skipped_not_fatal(home):
    bundle_in, capture = bundle()
    stored = confirmations.save_confirmation(bundle_in, capture)
    (confirmations.DEFAULT_DIR / "conf-000000000000.json").write_text("{broken")
    assert [entry["id"] for entry in confirmations.list_confirmations()] == [bundle_in["id"]]
    assert stored["sha256"]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda b: b.pop("claims"), "claims"),
        (lambda b: b.update(schema="something/else"), "schema"),
        (lambda b: b["ecu"].update(catalog_fingerprint="nope"), "SHA-256"),
        (lambda b: b["claims"].update(programming={"events": 1, "digest": "0" * 64}), "unknown claim"),
        (lambda b: b["claims"]["live"].update(digest="nope"), "SHA-256 digest"),
        (lambda b: b.update(vin="ZGUKE000000000000"), "identifiers"),
        (lambda b: b["session"].update(transport=""), "transport"),
    ],
)
def test_a_malformed_bundle_is_refused(mutate, message):
    bundle_in, _ = bundle()
    edited = json.loads(json.dumps(bundle_in))
    mutate(edited)
    with pytest.raises(confirmations.ConfirmationError, match=message):
        confirmations.validate_bundle(edited)


def test_the_bundle_records_what_the_frontend_declared_at_the_time(home):
    bundle_in, _ = bundle()
    assert bundle_in["ecu"]["declared_confidence"] == "verified-capture"
    assert bundle_in["ecu"]["declared_physical_supported"] is True
    assert bundle_in["ecu"]["declared_capabilities"]
    assert bundle_in["session"]["protocol"] == "iso14230"
    assert bundle_in["session"]["attempts"] == 1
    assert bundle_in["session"]["identity"]["Drawing"] == "IAW5AMHW610"
    assert bundle_in["app"]["name"] == "GuzziOnBoard"


def test_include_fitment_is_opt_in_and_labelled():
    profile = load_catalog(overlays=False).ecu("5am")
    capture = session_log()
    captured = confirmations.build_confirmation(
        profile=profile, capture=capture, transport="kline",
        install="c" * 32, include_fitment=True,
    )
    assert captured["fitment"]["operator_declared"] is True
    assert captured["fitment"]["operator_declared"] is True


def test_a_session_without_a_handshake_is_incomplete_and_says_why():
    bundle_in, capture = bundle(session_log(ok=False))
    assert bundle_in["verdict"] == "incomplete"
    assert "handshake" in bundle_in["verdict_reason"]
    assert "handshake" not in bundle_in["claims"]
    confirmations.verify_confirmation(bundle_in, capture)
