"""Optional automated sharing of a minimal hardware-read confirmation.

The report excludes the ECU image, identification block, vehicle details and
live-data frames. It includes connection frames, which could contain identifying
bytes on some protocols, plus region, size and image hash. Sharing requires explicit local configuration and consent.
A log is evidence reported by an installation, not proof of physical hardware.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from . import confirmations, resources

OUTBOX = resources.data_root() / "protocol" / "outbox"
MAX_CAPTURE = 8 * 1024 * 1024
_lock = threading.Lock()
_flush_lock = threading.Lock()


def configured():
    return (os.environ.get("GOB_SHARE_READ_VALIDATIONS") == "1"
            and bool(os.environ.get("GOB_VALIDATION_URL", "").startswith("https://"))
            and bool(os.environ.get("GOB_VALIDATION_TOKEN")))


def queue_read(diag, image, region):
    """Queue one physical read; never delay or fail the ECU operation."""
    if not configured() or not diag.transport.is_physical or not diag.log.enabled:
        return False
    if image.source != "read" or diag.profile.memory.get("research_read_only"):
        return False
    try:
        path = diag.log.path
        if path.stat().st_size > MAX_CAPTURE:
            return False
        raw = path.read_bytes()
        events = confirmations.parse_capture(raw[:raw.rfind(b"\n") + 1])
        ci, connect = confirmations._action(events, "connect")
        memory = next((event for event in reversed(events)
                       if event.get("kind") == "action" and event.get("name") == "memory_read_complete"), None)
        if connect is None or memory is None or not confirmations._detail(connect).get("ok"):
            return False
        detail = confirmations._detail(memory)
        if (detail.get("region") != region or detail.get("size") != image.size
                or detail.get("sha256") != image.sha256):
            return False
        # Only connection framing and the successful read summary are retained.
        # Do not include identity, arbitrary bus frames, the image or live data.
        frames = confirmations._window(events, ci)
        if (not frames or len(frames) > 12
                or any(len(str(frame.get("hex", ""))) > 128 for frame in frames)):
            return False
        minimal = [{"kind": "session_start", "meta": {
            "ecu": diag.profile.id, "transport": diag.transport.name,
            "mode": diag.gate.mode.value}}]
        minimal.extend({"kind": "frame", "dir": f.get("dir"), "hex": f.get("hex")} for f in frames)
        c = confirmations._detail(connect)
        minimal.append({"kind": "action", "name": "connect", "detail": {
            "ok": True, "protocol": c.get("protocol", ""), "init": c.get("init", "")}})
        minimal.append({"kind": "action", "name": "memory_read_complete", "detail": {
            "region": region, "size": image.size, "sha256": image.sha256}})
        capture = ("\n".join(json.dumps(e, separators=(",", ":")) for e in minimal) + "\n").encode()
        bundle = confirmations.build_confirmation(profile=diag.profile, capture=capture,
                                                    transport=diag.transport.name)
        if bundle["verdict"] != "ok" or "memory_read" not in bundle["claims"]:
            return False
        # Never promote other observations as a side effect of a memory read.
        bundle["claims"] = {"memory_read": bundle["claims"]["memory_read"]}
        # Identical retries from this installation are idempotent.
        bundle["id"] = "conf-" + hashlib.sha256(capture + bundle["install"]["marker"].encode()).hexdigest()[:24]
        confirmations.verify_confirmation(bundle, capture)
        with _lock:
            OUTBOX.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = OUTBOX / (bundle["id"] + ".json")
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps({"bundle": bundle, "capture": capture.decode()}), encoding="utf-8")
            temp.chmod(0o600)
            os.replace(temp, path)
        threading.Thread(target=flush_outbox, name="share-read", daemon=True).start()
        return True
    except (OSError, ValueError, TypeError, confirmations.ConfirmationError):
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("submission redirects are not allowed")


def flush_outbox():
    if not configured() or not _flush_lock.acquire(blocking=False):
        return
    try:
        url = os.environ["GOB_VALIDATION_URL"].rstrip("/") + "/v1/confirmations"
        token = os.environ["GOB_VALIDATION_TOKEN"]
        opener = urllib.request.build_opener(_NoRedirect())
        with _lock:
            paths = sorted(OUTBOX.glob("conf-*.json")) if OUTBOX.is_dir() else []
        for path in paths:
            try:
                with _lock:
                    data = path.read_bytes()
                if len(data) > 65536:
                    continue
                request = urllib.request.Request(url, data=data, method="POST", headers={
                    "Authorization": "Bearer " + token, "Content-Type": "application/json"})
                with opener.open(request, timeout=15) as response:
                    result = json.loads(response.read(4096))
                    if response.status in (200, 201) and result.get("accepted") is True:
                        with _lock:
                            path.unlink(missing_ok=True)
            except (OSError, ValueError, urllib.error.URLError):
                break  # retain this and later reports for the next attempt
    finally:
        _flush_lock.release()


def status():
    with _lock:
        queued = len(list(OUTBOX.glob("conf-*.json"))) if OUTBOX.is_dir() else 0
    return {"configured": configured(), "queued": queued,
            "note": "Reports contain connection frames, an install marker, ECU profile, region, size and image hash; no ECU image or identity block. Connection frames may contain identifying bytes. Reports are self-reported."}
