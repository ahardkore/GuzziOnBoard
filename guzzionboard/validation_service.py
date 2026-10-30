"""Deployable read-confirmation relay; terminate HTTPS at a trusted proxy.

A bearer credential authorizes submission, not the truth of a claim. Reports
are self-reported observations; there is no way for this service to prove a
remote ECU or client is genuine. The signing key and token are provided via
process environment and must not be committed. No ECU image is accepted.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import confirmations, protocol_updates
from .catalog import load_catalog, source_fingerprint

MAX_REQUEST = 65536


class RelayError(ValueError):
    pass


class ValidationRelay:
    def __init__(self, db: str | Path, *, token: str, seed: str, key_id: str):
        if len(token) < 32:
            raise RelayError("submission token must have at least 32 characters")
        if not key_id:
            raise RelayError("signing key ID is required")
        from .signing import public_key
        public_key(seed)  # reject an invalid seed at startup
        self.db, self.token, self.seed, self.key_id = str(db), token, seed, key_id
        Path(self.db).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS reports_v2 (ecu TEXT NOT NULL, region TEXT NOT NULL, id TEXT NOT NULL, bundle TEXT NOT NULL, capture TEXT NOT NULL, PRIMARY KEY (ecu, region))")
            conn.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL, envelope TEXT NOT NULL)")
        os.chmod(self.db, 0o600)

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def _validate(self, report):
        if not isinstance(report, dict) or set(report) != {"bundle", "capture"}:
            raise RelayError("expected bundle and minimal capture")
        bundle, text = report["bundle"], report["capture"]
        if not isinstance(text, str) or len(text.encode()) > 32768:
            raise RelayError("capture is invalid or too large")
        capture = text.encode()
        try:
            verified = confirmations.verify_confirmation(bundle, capture)
            events = confirmations.parse_capture(capture)
        except (confirmations.ConfirmationError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise RelayError(f"invalid confirmation: {exc}") from exc
        if set(bundle["claims"]) != {"memory_read"} or bundle.get("verdict") != "ok":
            raise RelayError("only completed memory-read reports are accepted")
        if len(events) < 4 or events[0].get("kind") != "session_start":
            raise RelayError("minimal session and handshake required")
        if any(e.get("kind") not in ("session_start", "frame", "action") for e in events):
            raise RelayError("unexpected evidence event")
        if any(e.get("kind") == "action" and e.get("name") not in ("connect", "memory_read_complete") for e in events):
            raise RelayError("only connection and memory-read actions are accepted")
        if (set(events[0]) != {"kind", "meta"}
                or len([e for e in events if e.get("kind") == "session_start"]) != 1):
            raise RelayError("unexpected session fields")
        connect_events = [e for e in events if e.get("name") == "connect"]
        read_events = [e for e in events if e.get("name") == "memory_read_complete"]
        if len(connect_events) != 1 or len(read_events) != 1 or events[-1] is not read_events[0]:
            raise RelayError("exactly one connection and one completed read are required")
        if (set(connect_events[0]) != {"kind", "name", "detail"}
                or set(connect_events[0].get("detail") or {}) != {"ok", "protocol", "init"}
                or set(read_events[0]) != {"kind", "name", "detail"}
                or set(read_events[0].get("detail") or {}) != {"region", "size", "sha256"}):
            raise RelayError("unexpected action fields")
        frames = [e for e in events if e.get("kind") == "frame"]
        if not 1 <= len(frames) <= 12 or any(
                set(f) != {"kind", "dir", "hex"} or f.get("dir") not in ("tx", "rx")
                or not isinstance(f.get("hex"), str) or len(f["hex"]) > 128
                for f in frames):
            raise RelayError("unexpected handshake frame")
        if events.index(connect_events[0]) != 1 + len(frames):
            raise RelayError("frames must be limited to the connection handshake")
        meta = events[0].get("meta") or {}
        if set(meta) != {"ecu", "transport", "mode"} or meta["transport"] not in ("kline", "can", "elm_j1850"):
            raise RelayError("invalid or non-hardware session metadata")
        if meta["ecu"] != verified["ecu"] or meta["transport"] != verified["transport"]:
            raise RelayError("session metadata does not match the report")
        derived = confirmations.derive_claims(events)
        if "handshake" not in derived or "memory_read" not in derived:
            raise RelayError("a framed connection and completed read are required")
        ecu = verified["ecu"]
        try:
            profile = load_catalog(overlays=False).ecu(ecu)
            if bundle["ecu"]["catalog_fingerprint"] != source_fingerprint(ecu):
                raise RelayError("catalog fingerprint differs from relay catalog")
            claim = derived["memory_read"]
            memory = profile.memory or {}
            region = (memory.get("regions") or {}).get(claim["region"]) or {}
            if (not memory.get("read_supported") or memory.get("research_read_only")
                    or not region.get("size") or claim["size"] != region["size"]):
                raise RelayError("read path or exact region geometry is not established")
        except (KeyError, ValueError) as exc:
            if isinstance(exc, RelayError):
                raise
            raise RelayError("unknown ECU or region") from exc
        # Store only a canonical minimal bundle, not client-provided free text,
        # fitment, identity or unrecognized fields. The capture is already bounded.
        sanitized = confirmations.build_confirmation(profile=profile, capture=capture,
                        transport=verified["transport"], install="relay-normalization")
        sanitized["id"] = bundle["id"]
        sanitized["install"]["marker"] = bundle["install"]["marker"]
        sanitized["claims"] = {"memory_read": sanitized["claims"]["memory_read"]}
        confirmations.verify_confirmation(sanitized, capture)
        return ecu, claim["region"], sanitized, text

    def submit(self, report):
        ecu, region, bundle, text = self._validate(report)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM reports_v2 WHERE ecu=? AND region=?", (ecu, region)).fetchone()
            if existing and existing[0] == bundle["id"]:
                return {"accepted": True, "duplicate": True}
            db.execute("INSERT OR REPLACE INTO reports_v2 VALUES (?,?,?,?,?)",
                       (ecu, region, bundle["id"], json.dumps(bundle), text))
            records = []
            for report_ecu, raw_bundle, raw_capture in db.execute("SELECT ecu,bundle,capture FROM reports_v2 ORDER BY ecu,region"):
                candidate = json.loads(raw_bundle)
                try:
                    if candidate["ecu"]["catalog_fingerprint"] == source_fingerprint(report_ecu):
                        records.append((candidate, raw_capture.encode()))
                except (KeyError, ValueError):
                    continue  # stale reports need a fresh observation for this catalog
            state = db.execute("SELECT sequence FROM state WHERE id=1").fetchone()
            seq = (state[0] if state else 0) + 1
            pack = protocol_updates.build_update_pack(records, quorum=1, sequence=seq,
                reviewer="automatic authenticated read reports",
                notes="Self-reported successful reads; no ECU image or independent physical verification was provided.")
            # A signed self-report is provenance, not independent bench proof.
            # Do not upgrade family-wide confidence or enable an untested path.
            # Each source names its precise region; catalog fingerprints bind it
            # to the installed profile, not all ECU variants or other regions.
            for promotion in pack["promotions"]:
                observed = sorted({b["claims"]["memory_read"]["region"] for b, _ in records
                                   if b["ecu"]["id"] == promotion["ecu"]})
                promotion["effects"] = [{"target": "source", "value":
                    f"Authenticated self-reported completed read of region {region!r}; "
                    "hardware origin and image completeness were not independently verified."}
                    for region in observed]
                promotion["evidence_note"] = ("Self-reported completed reads; no independent hardware verification; "
                                              "no family-wide confidence or write authorization change.")
                protocol_updates.check_effects(promotion, {"memory_read"})
            envelope = protocol_updates.envelope_for(pack, seed=self.seed, key_id=self.key_id)
            data = json.dumps(envelope, separators=(",", ":"))
            if len(data.encode()) > protocol_updates.MAX_PACK_BYTES:
                raise RelayError("signed update exceeds maximum size")
            db.execute("INSERT OR REPLACE INTO state VALUES (1,?,?)", (seq, data))
        return {"accepted": True, "duplicate": False, "sequence": seq}

    def latest(self):
        with self.connect() as db:
            row = db.execute("SELECT envelope FROM state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None


def handler_for(relay):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)
        def log_message(self, *_args):
            pass  # never log authorization headers or evidence
        def reply(self, status, value):
            data = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path != "/protocol-update.json":
                return self.reply(404, {"error": "not found"})
            envelope = relay.latest()
            return self.reply(200, envelope) if envelope else self.reply(404, {"error": "no update yet"})
        def do_POST(self):
            if self.path != "/v1/confirmations":
                return self.reply(404, {"error": "not found"})
            provided = self.headers.get("Authorization", "")
            if not hmac.compare_digest(provided.encode("utf-8"), ("Bearer " + relay.token).encode("utf-8")):
                return self.reply(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= MAX_REQUEST:
                    return self.reply(413, {"error": "invalid request size"})
                report = json.loads(self.rfile.read(length))
                result = relay.submit(report)
                return self.reply(200 if result.get("duplicate") else 201, result)
            except (RelayError, confirmations.ConfirmationError, protocol_updates.ProtocolUpdateError, ValueError, TypeError, KeyError):
                return self.reply(400, {"error": "invalid read confirmation"})
            except (OSError, sqlite3.Error):
                return self.reply(503, {"error": "relay storage unavailable"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Read-validation relay (put behind HTTPS)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    relay = ValidationRelay(args.db, token=os.environ.get("GOB_VALIDATION_TOKEN", ""),
                            seed=os.environ.get("GOB_SIGNING_SEED", ""),
                            key_id=os.environ.get("GOB_KEY_ID", ""))
    server = ThreadingHTTPServer((args.host, args.port), handler_for(relay))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
