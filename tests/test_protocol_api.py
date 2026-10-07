"""The HTTP surface an operator actually uses.

Everything the pipeline does is reachable from the workstation API - build a
confirmation from the session you just ran, verify somebody else's bundle,
check a signed pack, apply it, revert it - and every one of those steps is
tested here the way the UI calls it. The catalog reload at the end is the
whole point: after an apply, the *running* workstation serves the promoted
definition to everyone who asks for it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from guzzionboard import confirmations, protocol_updates
from guzzionboard.catalog import load_catalog
from guzzionboard.server import Api
from guzzionboard.sessionlog import SessionLog
from guzzionboard.workstation import Workstation

SEED = "5a" * 32


def hardware_capture(*, seed: int = 0, samples: int = 0, dtcs: bool = True) -> bytes:
    """A session exactly as the workstation records one against a real ECU."""
    lines = [
        {
            "t": 1.0 + seed * 0.01,
            "kind": "session_start",
            "id": "deadbeef",
            "meta": {
                "app_version": "0.3.0",
                "ecu": "7sm",
                "ecu_family": "IAW 7SM",
                "transport": "kline",
                "mode": "read_only",
            },
        },
        {"t": 1.1 + seed * 0.01, "kind": "frame", "dir": "tx", "hex": "81 10 f1 81 05"},
        {"t": 1.2 + seed * 0.01, "kind": "frame", "dir": "rx", "hex": "80 f1 10 41 05 c4"},
        {
            "t": 1.3 + seed * 0.01,
            "kind": "action",
            "name": "connect",
            "detail": {
                "transport": "kline",
                "protocol": "iso14230",
                "init": "fast",
                "ok": True,
                "attempts": 1,
            },
        },
        {
            "t": 1.4 + seed * 0.01,
            "kind": "action",
            "name": "identify",
            "detail": {"fields": {"Software": f"7SM-{seed}", "Hardware": "HW100"}},
        },
    ]
    for index in range(samples):
        lines.append(
            {
                "t": 2.0 + index + seed,
                "kind": "sample",
                "key": "rpm",
                "lid": 0x30,
                "raw": f"{index + 1 + seed:02x}10",
                "value": 1000 + index,
                "unit": "rpm",
            }
        )
    if dtcs:
        # a 7SM session can read fault codes; it cannot poll live data, because
        # the catalog declares no 7SM parameters for a session to poll.
        lines.append(
            {
                "t": 3.0 + seed,
                "kind": "action",
                "name": "read_dtcs",
                "detail": {"count": 2, "codes": ["P0130", "P0115"]},
            }
        )
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode()


class FakeLog:
    """The bits of :class:`SessionLog` the API touches, without a session."""

    def __init__(self, path: Path, capture: bytes):
        path.write_bytes(capture)
        self.path = path
        self.enabled = True
        self.counts = {"action": 2, "frame": 2}
        self.actions: list[tuple[str, dict]] = []

    def action(self, name, detail=None):
        self.actions.append((name, detail or {}))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(confirmations, "DEFAULT_DIR", tmp_path / "confirmations")
    monkeypatch.setattr(confirmations, "INSTALL_FILE", tmp_path / "install.json")
    monkeypatch.setattr(protocol_updates, "DEFAULT_DIR", tmp_path / "protocol")
    monkeypatch.setattr(
        protocol_updates, "LOCAL_KEYRING", tmp_path / "protocol" / "keys.json"
    )
    return tmp_path


@pytest.fixture
def api(home):
    """A workstation pointed at the 7SM, dressed as a hardware session."""
    workstation = Workstation(record=False)
    workstation.select(ecu="7sm", transport="kline", device="/dev/ttyUSB0")
    api = Api(workstation)
    return api


def as_hardware_session(api, capture: bytes, name: str = "session.jsonl") -> FakeLog:
    log = FakeLog(confirmations.DEFAULT_DIR.parent / name, capture)
    api.ws.log = log
    api.ws.selection.transport_kind = "kline"
    return log


# ----------------------------------------------------------------- GET status


def test_the_status_endpoint_is_honest_before_anything_is_applied(api):
    status, body = api.get_protocol_updates({})
    assert status == 200
    assert body["status"]["applied"] is False
    assert body["status"]["applied_status"]["state"] == "none"
    assert body["confirmations"] == []
    assert body["submission"]["url"].startswith("https://github.com/")
    assert body["selection"]["ecu"] == "7sm"
    assert "write" in body["not_claimable"]
    assert "never uploaded" in body["note"]


# ------------------------------------------------------------- building one


def test_a_simulated_session_cannot_build_a_confirmation(api):
    api.ws.select(ecu="5am", transport="simulator")
    api.ws.log = FakeLog(confirmations.DEFAULT_DIR.parent / "sim.jsonl", b"")
    with pytest.raises(ValueError, match="cannot confirm"):
        api.post_confirmations_build({})


def test_a_session_without_a_capture_is_refused(api):
    api.ws.log = None
    with pytest.raises(ValueError, match="no recorded session"):
        api.post_confirmations_build({})


def test_building_a_confirmation_writes_two_files_and_a_link(api):
    as_hardware_session(api, hardware_capture())
    status, body = api.post_confirmations_build({"note": "read live data fine"})
    assert status == 200
    bundle = body["bundle"]
    assert bundle["verdict"] == "ok"
    assert set(bundle["claims"]) >= {"handshake", "identify", "dtc_read"}
    assert Path(body["stored"]["bundle_path"]).is_file()
    assert Path(body["stored"]["capture_path"]).read_bytes() == hardware_capture()
    assert body["submission"]["url"].startswith(confirmations.SUBMIT_URL)
    assert bundle["id"] in body["submission"]["body"]
    assert "nothing is uploaded" in body["note"]
    # the session log records what happened, for the record
    assert api.ws.log.actions[-1][0] == "confirmation"
    # and it shows up in the status listing
    listing = api.get_protocol_updates({})[1]["confirmations"]
    assert [entry["id"] for entry in listing] == [bundle["id"]]


def test_a_half_written_line_is_never_claimed(api):
    capture = hardware_capture()
    log = as_hardware_session(api, capture + b'{"t": 9.9, "kind": "acti')
    _, body = api.post_confirmations_build({})
    frozen = Path(body["stored"]["capture_path"]).read_bytes()
    assert frozen == capture                     # the partial event was cut off
    assert body["bundle"]["session"]["capture_sha256"] == body["bundle"]["session"][
        "capture_sha256"
    ]
    assert log.path.read_bytes() != frozen       # the live log keeps growing


def test_a_bundle_can_be_re_verified_over_http(api):
    as_hardware_session(api, hardware_capture())
    api.post_confirmations_build({})
    status, body = api.post_confirmations_verify({})
    assert status == 200
    assert body["report"]["ok"] is True
    assert body["report"]["claims"]
    # a bundle whose capture is missing cannot be waved through
    listing = api.get_protocol_updates({})[1]["confirmations"]
    Path(listing[0]["path"]).parent.joinpath(
        f"{listing[0]['id']}.session.jsonl"
    ).unlink()
    with pytest.raises(confirmations.ConfirmationError, match="cannot be reviewed"):
        api.post_confirmations_verify({})


def test_structural_validation_is_available_without_a_capture(api):
    as_hardware_session(api, hardware_capture())
    bundle = api.post_confirmations_build({})[1]["bundle"]
    status, body = api.post_confirmations_validate({"bundle": bundle})
    assert status == 200 and body["ok"] is True
    broken = json.loads(json.dumps(bundle))
    broken["claims"] = {}
    with pytest.raises(confirmations.ConfirmationError, match="claims"):
        api.post_confirmations_validate({"bundle": broken})
    with pytest.raises(ValueError, match="'bundle' object"):
        api.post_confirmations_validate({})


# --------------------------------------------------- check, apply, revert


def _pack_from(api, tmp_path, *, seed_a: int = 0, seed_b: int = 1) -> dict:
    """Two independent confirmations, aggregated and signed."""
    confirmations_in = []
    for marker, seed in (("a" * 32, seed_a), ("b" * 32, seed_b)):
        bundle = confirmations.build_confirmation(
            profile=load_catalog(overlays=False).ecu("7sm"),
            capture=hardware_capture(seed=seed),
            transport="kline",
            install=marker,
        )
        confirmations_in.append((bundle, hardware_capture(seed=seed)))
    return protocol_updates.build_update_pack(confirmations_in, reviewer="maintainer")


def test_check_apply_and_revert_over_http(api, home, tmp_path):
    pack = _pack_from(api, tmp_path)
    envelope = protocol_updates.envelope_for(pack, seed=SEED, key_id="release")
    file_url = (tmp_path / "protocol-update.json").as_uri()
    (tmp_path / "protocol-update.json").write_text(json.dumps(envelope))

    # nothing pinned: the pack cannot be trusted, and the API says why.
    # (These calls raise here; ``Api._dispatch`` turns the ValueError subclass
    # into an HTTP 400 with the same message for the browser.)
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="no trusted key"):
        api.post_protocol_updates_check({"url": file_url})

    assert api.post_protocol_updates_pin_key(
        {"key_id": "release", "public_key": envelope["public_key"]}
    )[1]["pinned"] == "release"

    status, body = api.post_protocol_updates_check({"url": file_url})
    assert status == 200
    preview = body["preview"]
    assert preview["signature_verified"] is True
    assert preview["pack"]["reviewer"] == "maintainer"
    assert {change["claim"] for change in preview["changes"]} >= {
        "handshake", "identify", "dtc_read",
    }
    assert "Read-level promotions only" in preview["message"]
    assert api.ws.catalog.ecu("7sm").field_confirmation == {}   # not applied yet

    # applying with the wrong digest is refused
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="reviewed preview"):
        api.post_protocol_updates_apply(
            {"envelope": envelope, "expected_sha256": "0" * 64}
        )

    status, body = api.post_protocol_updates_apply(
        {"envelope": envelope, "expected_sha256": preview["sha256"]}
    )
    assert status == 200 and body["applied"] is True
    assert body["catalog"]["catalog_reloaded"] is True

    profile = api.ws.catalog.ecu("7sm")
    assert "dtc_read" in profile.capabilities
    assert profile.capability_level("dtc_read") == "verified-bench"
    assert "live" not in profile.capabilities        # nothing claimed it
    assert profile.confidence == "inferred"          # control actions untouched
    assert profile.field_confirmation["independent_sessions"] == 2

    # ... and the running API now serves the promotion
    status, body = api.get_protocol_updates({})
    assert body["status"]["applied"] is True
    assert body["selection"]["field_confirmation"]["independent_sessions"] == 2
    assert "dtc_read" in body["selection"]["effective_capabilities"]
    assert api.get_catalog({})[1]["summary"]["protocol_updates"]["applied"] is True

    status, body = api.post_protocol_updates_revert({})
    assert body["reverted"] is True
    assert "dtc_read" not in api.ws.catalog.ecu("7sm").capabilities
    assert api.get_protocol_updates({})[1]["status"]["applied"] is False


def test_apply_requires_the_envelope_you_previewed(api, home, tmp_path):
    """No silent re-fetch: apply without the reviewed bytes is refused."""
    with pytest.raises(ValueError, match="apply what you previewed"):
        api.post_protocol_updates_apply({"expected_sha256": "0" * 64})
    with pytest.raises(ValueError, match="apply what you previewed"):
        api.post_protocol_updates_apply({"expected_sha256": "0" * 64, "url": "   "})


def test_applying_a_pack_reviewed_for_another_release_is_refused(api, home, tmp_path):
    pack = _pack_from(api, tmp_path)
    pack["base"]["catalog_fingerprints"]["7sm"] = "b" * 64
    envelope = protocol_updates.envelope_for(pack, seed=SEED, key_id="release")
    api.post_protocol_updates_pin_key(
        {"key_id": "release", "public_key": envelope["public_key"]}
    )
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="could not read"):
        api.post_protocol_updates_check({"url": str(tmp_path)})   # a directory
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(envelope))
    with pytest.raises(protocol_updates.ProtocolUpdateError, match="different catalog revision"):
        api.post_protocol_updates_check({"url": str(path)})


def test_keys_can_be_pinned_and_removed_but_not_faked(api, home):
    public = protocol_updates.envelope_for.__module__ and __import__(
        "guzzionboard.signing", fromlist=["public_key"]
    ).public_key(SEED)
    assert api.post_protocol_updates_pin_key(
        {"key_id": "release", "public_key": public}
    )[1]["keys"] == ["release"]
    with pytest.raises(ValueError, match="64 hex"):
        api.post_protocol_updates_pin_key({"key_id": "x", "public_key": "nope"})
    assert api.post_protocol_updates_unpin_key({"key_id": "release"})[1][
        "removed"
    ] == "release"
    assert protocol_updates.keyring() == {}


# ------------------------------------------------------- the HTTP boundary


def test_dispatch_turns_a_protocol_refusal_into_a_browser_readable_400(api, home, tmp_path):
    """A real socket, a real request: what the UI receives is a 400, not a crash.

    The handlers raise ``ProtocolUpdateError`` (a ``ValueError`` subclass) on
    purpose - only ``Api._dispatch`` knows how to turn that into a status code,
    so the mapping is pinned here over the wire rather than in-process.
    """
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from guzzionboard.server import make_handler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api.ws))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        def call(method: str, path: str, body: dict | None = None):
            request = Request(
                base + path,
                data=json.dumps(body or {}).encode() if method == "POST" else None,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            try:
                with urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as exc:
                return exc.code, json.loads(exc.read())

        status, body = call("GET", "/api/protocol-updates")
        assert status == 200 and body["status"]["applied"] is False

        # an unreachable URL is the caller's mistake, and reads like one
        status, body = call("POST", "/api/protocol-updates/check", {"url": "file:///nope"})
        assert status == 400 and body["code"] == "bad_request"
        assert "could not read" in body["error"]

        # no key pinned yet: a well-formed envelope still cannot be trusted
        pack_file = tmp_path / "protocol-update.json"
        pack_file.write_text(json.dumps({
            "schema": protocol_updates.ENVELOPE_SCHEMA,
            "key_id": "release",
        }))
        status, body = call(
            "POST", "/api/protocol-updates/check", {"url": pack_file.as_uri()}
        )
        assert status == 400
        assert body["code"] == "bad_request"
        assert "no trusted key" in body["error"]

        # the same boundary for confirmation bundles: bad input is the caller's fault
        status, body = call("POST", "/api/confirmations/validate", {"bundle": {}})
        assert status == 400 and body["code"] == "bad_request"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
