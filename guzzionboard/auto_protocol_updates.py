"""Background delivery of signed, read-only protocol updates.

Optional read-sharing uploads a minimized session report separately. An update is
applied only when the existing signature, catalog, sequence and effect checks
pass. Evidence collection and publication are separate infrastructure.
"""
from __future__ import annotations

import threading
import time

from . import protocol_updates

INTERVAL_SECONDS = 4 * 60 * 60
# Serialize automatic and UI-driven updates in this process.
UPDATE_LOCK = threading.RLock()


class AutoProtocolUpdates:
    def __init__(self, workstation, *, interval=INTERVAL_SECONDS):
        self.workstation = workstation
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._status = {"state": "waiting", "last_check": None, "detail": "Waiting for the first check."}

    def status(self):
        with self._lock:
            return dict(self._status)

    def _set(self, state, detail):
        with self._lock:
            self._status = {"state": state, "detail": detail, "last_check": time.time()}

    def check_once(self):
        try:
            from .read_sharing import flush_outbox
            flush_outbox()
            if not protocol_updates.keyring():
                self._set("no_trusted_key", "No release key is pinned; automatic updates cannot be verified or applied.")
                return
            import os
            source = os.environ.get("GOB_PROTOCOL_UPDATE_URL") or None
            if source and not source.startswith("https://"):
                raise protocol_updates.ProtocolUpdateError("Automatic update URL must use HTTPS")
            envelope = protocol_updates.fetch_pack(source) if source else protocol_updates.fetch_pack()
            with UPDATE_LOCK:
                if self._stop.is_set():
                    return
                preview = protocol_updates.check_envelope(envelope)
                if preview["already_applied"]:
                    self._set("current", "The published signed protocol update is already applied.")
                    return
                protocol_updates.apply_pack(envelope, expected_sha256=preview["sha256"])
                self.workstation.reload_catalog()
            self._set("applied", f"Applied signed read-level update {preview['pack']['id']}; active ECU sessions are unchanged.")
        except (protocol_updates.ProtocolUpdateError, OSError, ValueError) as exc:
            self._set("unavailable", str(exc))
        except Exception as exc:  # retain a visible error, never stop the workstation
            self._set("error", f"Automatic update failed: {exc}")

    def _run(self):
        while not self._stop.is_set():
            self.check_once()
            if self._stop.wait(self.interval):
                break

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="protocol-update", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.1)
