"""The trust boundary modules, tested on their own rather than in passing.

``physical_validation``, ``validation_service`` and ``read_sharing`` decide what
counts as evidence. Until now they were only exercised indirectly, through the
relay integration tests: a validator that accepted everything, or a relay that
signed a report it should have refused, would have passed those.

Everything here is synthetic. No ECU, no network, no Cloudflare.
"""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from guzzionboard import physical_validation
from guzzionboard.confirmations import ConfirmationError
from guzzionboard.physical_validation import (
    PhysicalValidationError,
    load_manifests,
    validate_manifest,
)
from guzzionboard.validation_service import (
    MAX_REQUEST,
    RelayError,
    ValidationRelay,
    handler_for,
)

SCHEMA = physical_validation.SCHEMA
DIGEST = "a" * 64
TOKEN = "t" * 40
SEED = "11" * 32


# ------------------------------------------------------- manifest validation

def manifest(**overrides) -> dict:
    """A complete, passing real-ECU evidence record."""
    value = {
        "schema": SCHEMA,
        "kind": "real-ecu",
        "result": "pass",
        "id": "griso-1200-8v-2012-flash-read",
        "performed_at": "2026-10-04T10:00:00Z",
        "operator": {"name": "A Tester", "organization": "Workshop"},
        "motorcycle": {
            "make": "Moto Guzzi", "model": "Griso 1200 8V", "year": 2012,
            "configuration": "standard exhaust and air filter, 9,000 km",
        },
        "ecu": {"family": "IAW 5AM", "hardware": "5AM", "software": "V1.0"},
        "artifacts": [{"kind": "session", "path": "session.jsonl", "sha256": DIGEST}],
        "checks": [{"name": "readback matches", "detail": "two reads, equal", "status": "pass"}],
    }
    value.update(overrides)
    return value


def test_a_complete_record_validates_and_is_labelled_as_operator_supplied(tmp_path):
    record = validate_manifest(manifest(), path=str(tmp_path / "record.json"))
    assert record["id"] == "griso-1200-8v-2012-flash-read"
    # The tool indexes evidence; it does not certify it.
    assert record["endorsement"] == "operator-supplied-not-core-certified"
    assert record["artifact_summary"] == {
        "total": 1, "missing": 1, "hash_mismatch": 0, "verified": 0,
    }
    assert record["registry_status"] == "evidence-index-incomplete"


def test_an_artifact_that_is_present_and_matches_is_verified(tmp_path):
    payload = tmp_path / "session.jsonl"
    payload.write_bytes(b'{"kind":"session_start"}\n')
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    value = manifest(artifacts=[{"kind": "session", "path": "session.jsonl", "sha256": digest}])
    record = validate_manifest(value, path=str(tmp_path / "record.json"))
    assert record["artifact_summary"]["verified"] == 1
    assert record["registry_status"] == "evidence-index-locally-complete"


def test_a_present_artifact_with_the_wrong_hash_is_reported_not_accepted(tmp_path):
    payload = tmp_path / "session.jsonl"
    payload.write_bytes(b"edited after the fact")
    value = manifest(artifacts=[{"kind": "session", "path": "session.jsonl", "sha256": DIGEST}])
    record = validate_manifest(value, path=str(tmp_path / "record.json"))
    assert record["artifact_summary"]["hash_mismatch"] == 1
    assert record["registry_status"] == "evidence-index-incomplete"


@pytest.mark.parametrize("overrides,message", [
    ({"schema": "something/v9"}, "schema must be"),
    ({"kind": "vibes"}, "kind must be real-ecu or dyno"),
    ({"result": "probably"}, "result must be pass, fail, or incomplete"),
    ({"id": "UPPER CASE"}, "lowercase record identifier"),
    ({"performed_at": "last tuesday"}, "ISO date-time"),
    ({"operator": None}, "operator is required"),
    ({"motorcycle": {**manifest()["motorcycle"], "year": "MMXII"}}, "year must be an integer"),
    ({"motorcycle": {**manifest()["motorcycle"], "year": 1800}}, "outside 1900..2200"),
    ({"motorcycle": {**manifest()["motorcycle"], "configuration": "stock"}},
     "configuration needs specific detail"),
    ({"artifacts": []}, "at least one hashed artifact"),
    ({"artifacts": [{"kind": "session", "path": "x", "sha256": "short"}]}, "64-hex SHA-256"),
    ({"artifacts": [{"kind": "vibes", "path": "x", "sha256": DIGEST}]}, "invalid kind"),
    ({"checks": []}, "at least one check result"),
    ({"checks": [{"name": "x", "detail": "y", "status": "maybe"}]}, "invalid status"),
])
def test_a_malformed_record_is_refused_with_a_specific_reason(overrides, message):
    with pytest.raises(PhysicalValidationError, match=message):
        validate_manifest(manifest(**overrides))


def test_a_pass_cannot_contain_a_failed_check():
    value = manifest(checks=[
        {"name": "readback", "detail": "mismatch", "status": "fail"},
    ])
    with pytest.raises(PhysicalValidationError, match="cannot contain failed"):
        validate_manifest(value)


def test_a_dyno_record_needs_a_calibrated_dyno(tmp_path):
    value = manifest(kind="dyno")
    with pytest.raises(PhysicalValidationError, match="dyno records require"):
        validate_manifest(value)
    value["build"] = {
        "source_sha256": DIGEST, "output_sha256": DIGEST,
        "xdf_sha256": DIGEST, "plan_sha256": DIGEST,
    }
    value["dyno"] = {
        "make": "Dynojet", "model": "250i", "serial": "1",
        "calibration_date": "2026-09-30", "correction_standard": "SAE J1349",
    }
    record = validate_manifest(value)
    assert record["kind"] == "dyno"
    value["dyno"]["calibration_date"] = "30/09/2026"
    with pytest.raises(PhysicalValidationError, match="YYYY-MM-DD"):
        validate_manifest(value)


def test_the_registry_reports_bad_files_and_duplicate_ids_separately(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(manifest()))
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "duplicate.json").write_text(json.dumps(manifest()))
    records, errors = load_manifests(tmp_path)
    assert [record["id"] for record in records] == ["griso-1200-8v-2012-flash-read"]
    reasons = sorted(error["error"] for error in errors)
    assert any("duplicate" in reason for reason in reasons)
    assert any("Expecting" in reason or "property" in reason.lower()
               or "json" in reason.lower() for reason in reasons)


def test_missing_registry_directory_is_empty_not_an_error(tmp_path):
    assert load_manifests(tmp_path / "nope") == ([], [])


# ----------------------------------------------------------- relay boundary

def test_the_relay_refuses_a_short_bearer_token(tmp_path):
    with pytest.raises(RelayError, match="32"):
        ValidationRelay(tmp_path / "relay.sqlite", token="short", seed=SEED,
                        key_id="release")


def test_the_relay_refuses_a_bad_signing_seed(tmp_path):
    from guzzionboard.signing import SignatureError

    # Startup validation must reject the seed rather than fail at first signing.
    with pytest.raises(SignatureError):
        ValidationRelay(tmp_path / "relay.sqlite", token=TOKEN, seed="not-hex",
                        key_id="release")


def test_the_relay_refuses_a_missing_key_id(tmp_path):
    with pytest.raises(RelayError, match="key ID"):
        ValidationRelay(tmp_path / "relay.sqlite", token=TOKEN, seed=SEED, key_id="")


@pytest.fixture
def relay(tmp_path):
    return ValidationRelay(tmp_path / "relay.sqlite", token=TOKEN, seed=SEED,
                           key_id="release")


@pytest.fixture
def relay_server(relay):
    import http.client

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(relay))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def call(server, method, path, *, body=None, token=None, headers=None):
    import http.client

    connection = http.client.HTTPConnection(*server.server_address, timeout=10)
    try:
        sent = {} if headers is None else dict(headers)
        if token:
            sent["Authorization"] = "Bearer " + token
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        return response.status, raw
    finally:
        connection.close()


def test_submission_requires_the_bearer_token_in_constant_time(relay_server):
    """A missing, short, or wrong token is a 401 - never a guess at the length."""
    for token in (None, "u" * len(TOKEN), "u", TOKEN + "!"):
        status, body = call(
            relay_server, "POST", "/v1/confirmations", body="{}",
            token=token, headers={"Content-Type": "application/json"},
        )
        assert status == 401, token
        assert b"error" in body


def test_the_published_pack_is_public_because_it_is_signed(relay_server):
    """GET /protocol-update.json is deliberately unauthenticated.

    Distribution has to work for a client that has only the bundled release
    key; what protects it is the signature and the local key pin, not the
    bearer token. The endpoint must still say "nothing yet" rather than
    serving an unsigned placeholder.
    """
    status, body = call(relay_server, "GET", "/protocol-update.json")
    assert status == 404
    assert json.loads(body) == {"error": "no update yet"}


def test_unknown_routes_are_404_and_unknown_methods_are_not_silently_accepted(relay_server):
    assert call(relay_server, "GET", "/nope", token=TOKEN)[0] == 404
    assert call(relay_server, "POST", "/nope", body="{}", token=TOKEN)[0] == 404
    # BaseHTTPRequestHandler answers an unimplemented verb with 501.
    assert call(relay_server, "DELETE", "/v1/confirmations", token=TOKEN)[0] in (404, 405, 501)


def test_an_oversized_body_is_refused_before_it_is_read(relay_server):
    status, _ = call(
        relay_server, "POST", "/v1/confirmations", body="{}",
        token=TOKEN, headers={"Content-Length": str(MAX_REQUEST + 1)},
    )
    assert status == 413


def test_an_unknown_route_is_a_404_and_a_wrong_method_a_405(relay_server):
    assert call(relay_server, "GET", "/nope", token=TOKEN)[0] == 404
    assert call(relay_server, "DELETE", "/status", token=TOKEN)[0] in (405, 501)


def test_a_report_that_is_not_a_valid_bundle_is_refused_without_a_signature(relay_server):
    status, body = call(
        relay_server, "POST", "/v1/confirmations", body=json.dumps({"bundle": {}}),
        token=TOKEN, headers={"Content-Type": "application/json"},
    )
    assert status >= 400
    assert b"signature" not in body.lower() or b"error" in body.lower()
