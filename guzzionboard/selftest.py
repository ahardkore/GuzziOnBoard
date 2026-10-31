"""Check an installed copy of the workstation, without a motorcycle.

``guzzionboard --selftest`` / ``guzzionboard-desktop --selftest`` runs the real
stack - catalog, HTTP API, safety gate, simulator, UI files, and (in a frozen
build) the isolated checksum worker executable - and prints one line per check.

It exists because "the installer built successfully" is not evidence that the
thing it produced runs: a frozen build fails in ways a source checkout never
does (missing data files, a worker binary that was not collected, a bridge
script that never made it into the bundle). This is the check CI runs against
the artifact itself, and the check a user can run if the window misbehaves.

Nothing here touches the user's own data: the whole test runs inside a
temporary directory, including the per-user state root.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from . import __version__, resources


#: A windowed build has no console, so the transcript of a self-test run is
#: written here as well as to stdout. Set by the build (packaging/build.py)
#: and by anyone who wants a copy of the output.
LOG_ENV = "GOB_SELFTEST_LOG"


class Result:
    def __init__(self) -> None:
        self.checks: list[tuple[bool, str, str]] = []
        self.lines: list[str] = []

    def say(self, line: str = "") -> None:
        self.lines.append(line)
        try:
            print(line)
        except Exception:            # a frozen windowed build may have no stdout
            pass

    def record(self, ok: bool, name: str, detail: str = "") -> bool:
        self.checks.append((bool(ok), name, detail))
        self.say(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    @property
    def failures(self) -> list[tuple[bool, str, str]]:
        return [check for check in self.checks if not check[0]]


def _get(port: int, path: str, *, token: str | None = None, headers: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        sent = {"Host": f"127.0.0.1:{port}"}
        if token:
            sent[resources.TOKEN_HEADER] = token
        sent.update(headers or {})
        connection.request("GET", path, headers=sent)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _post(port: int, path: str, payload: dict, *, token: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        sent = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
        if token:
            sent[resources.TOKEN_HEADER] = token
        connection.request("POST", path, body=json.dumps(payload).encode(), headers=sent)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def run(*, export_dir: str | None = None, host: str = "127.0.0.1",
        verbose: bool = False) -> int:
    """Run every check; return 0 when the installation is usable."""
    result = Result()
    result.say(f"GuzziOnBoard {__version__} self-test")
    if os.environ.get("GOB_SELFTEST_REQUIRE_HARDWARE") == "1":
        try:
            import serial  # noqa: F401
            import serial.tools.list_ports  # noqa: F401
            import can  # noqa: F401
            import can.interfaces  # noqa: F401
            # python-can loads backends dynamically; importing the top-level
            # package alone cannot prove the frozen virtual backend was collected.
            bus = can.Bus(interface="virtual", channel="gob-selftest")
            try:
                bus.send(can.Message(arbitration_id=0x123, data=b"\x01"))
            finally:
                bus.shutdown()
            result.record(True, "bundled serial and virtual CAN modules work")
        except Exception as exc:
            result.record(False, "bundled serial and virtual CAN modules work", str(exc))
    with tempfile.TemporaryDirectory(prefix="guzzionboard-selftest-") as work:
        os.environ[resources.HOME_ENV] = work        # never touch real user data
        exports = Path(export_dir or (Path(work) / "exports"))
        exports.mkdir(parents=True, exist_ok=True)
        try:
            _run_checks(result, exports, host)
        except Exception as exc:                      # a failed check, not a traceback
            import traceback

            traceback.print_exc()
            result.record(False, "self-test completed", f"{type(exc).__name__}: {exc}")
    failures = result.failures
    result.say()
    if failures:
        result.say(f"{len(failures)} of {len(result.checks)} checks failed.")
        result.say("This installation is not complete; reinstall, or report the output above.")
        code = 1
    else:
        result.say(f"All {len(result.checks)} checks passed. This copy is usable.")
        code = 0
    _write_transcript(result)
    return code


def _write_transcript(result: Result) -> None:
    """Leave a copy of the transcript where a windowed run can be read."""
    target = os.environ.get(LOG_ENV)
    if not target:
        return
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(result.lines) + "\n", encoding="utf-8")
    except OSError as exc:                    # pragma: no cover - best effort
        result.say(f"(could not write {target}: {exc})")


def _run_checks(result: Result, exports: Path, host: str) -> None:
    from .server import RequestGuard, make_handler
    from .workstation import Workstation

    # -- the files a build has to carry ---------------------------------
    web = None
    try:
        web = resources.web_root()
        result.record(True, "UI directory", str(web))
    except resources.BundleIncomplete as exc:
        result.record(False, "UI directory", str(exc))
    if web is not None:
        for name in ("index.html", "app.js", "styles.css", "demo-api.js"):
            result.record((web / name).is_file(), f"UI file {name}")
        bridge = web / "desktop-bridge.js"
        result.record(bridge.is_file(), "desktop bridge script",
                      str(bridge) if bridge.is_file() else "missing")

    from .catalog import load_catalog

    catalog = load_catalog()
    summary = catalog.summary()
    result.record(
        summary["ecu_count"] >= 10 and summary["vehicle_count"] >= 100,
        "catalog",
        f"{summary['ecu_count']} families, {summary['vehicle_count']} model variants",
    )

    from .maps import available_xdfs

    xdfs = available_xdfs()
    result.record(len(xdfs) >= 90, "XDF library", f"{len(xdfs)} definitions")

    from .protocol_updates import BUNDLED_KEYRING

    result.record(Path(BUNDLED_KEYRING).is_file(), "protocol update keyring",
                  str(BUNDLED_KEYRING))

    from .adapter import DRIVER_BUNDLE_ZIP

    bundle = Path(DRIVER_BUNDLE_ZIP)
    result.record(
        True,
        "FTDI driver bundle",
        str(bundle) if bundle.is_file()
        else "not shipped in this build (the pre-flight will point at ftdichip.com)",
    )

    # -- the isolated checksum worker ------------------------------------
    _check_worker(result)

    # -- the server, the guard and the UI as served ----------------------
    workstation = Workstation(record=False)
    token = "selftest-token"
    handler = make_handler(
        workstation, guard=RequestGuard(token=token), desktop=_SelftestBridge(exports)
    )
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer((host, 0), handler)
    server.daemon_threads = True
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(port, "/")
        page = body.decode("utf-8", "replace")
        result.record(status == 200 and "GuzziOnBoard" in page, "UI page served", f"HTTP {status}")
        result.record('data-desktop="1"' in page, "page marked as desktop-hosted")
        result.record("desktop-bridge.js" in page, "bridge script injected before the app")

        status, body = _get(port, "/api/desktop/ping", token=token)
        payload = json.loads(body or b"{}")
        result.record(status == 200 and payload.get("ok") is True, "API answers", f"HTTP {status}")

        status, _ = _get(port, "/api/status")
        result.record(status == 403, "API refuses a request with no session token",
                      f"HTTP {status}")

        import base64

        status, body = _get(port, "/api/status", token=base64.b64encode(b"nope").decode())
        result.record(status == 403, "API refuses a wrong session token", f"HTTP {status}")

        status, _ = _get(port, "/api/status", token=token, headers={"Origin": "https://example.com"})
        result.record(status == 403, "API refuses a foreign origin", f"HTTP {status}")

        status, _ = _get(port, "/api/status", token=token,
                         headers={"Host": f"attacker.example:{port}"})
        result.record(status == 403, "API refuses a non-loopback Host header", f"HTTP {status}")

        status, body = _get(port, "/api/desktop", token=token)
        payload = json.loads(body or b"{}")
        result.record(
            status == 200 and payload.get("available") is True,
            "desktop host routes",
            f"exports → {payload.get('exports')}",
        )

        # -- a real session through the real stack -----------------------
        status, body = _post(port, "/api/select", {
            "ecu": "5am", "transport": "simulator",
        }, token=token)
        selected = json.loads(body or b"{}")
        ecu = selected.get("ecu") or {}
        result.record(
            status == 200 and ecu.get("id") == "5am",
            "select a motorcycle",
            f"{ecu.get('family') or 'nothing selected'} over {selected.get('transport')}",
        )
        status, body = _post(port, "/api/connect", {"mode": "simulator"}, token=token)
        connected = json.loads(body or b"{}")
        result.record(status == 200, "connect to the simulator", f"HTTP {status}")
        status, body = _get(port, "/api/identify", token=token)
        identity = json.loads(body or b"{}")
        fields = identity.get("fields") or {}
        result.record(
            status == 200 and any("IAW" in str(v) for v in fields.values()),
            "identify over the wire protocol",
            ", ".join(f"{k}={v}" for k, v in list(fields.items())[:3]),
        )
        status, body = _get(port, "/api/live?keys=rpm,battery", token=token)
        live = json.loads(body or b"{}")
        samples = live.get("samples") or []
        result.record(
            status == 200 and len(samples) == 2 and all(s.get("raw") for s in samples),
            "live data with raw bytes kept",
            f"{len(samples)} channels",
        )
        status, body = _post(port, "/api/disconnect", {}, token=token)
        result.record(status == 200, "disconnect", f"HTTP {status}")

        # -- saving a file, the way a report export does ------------------
        status, body = _post(port, "/api/desktop/save",
                             {"name": "../escape/report.txt", "content": "selftest"}, token=token)
        saved = json.loads(body or b"{}")
        written = Path(saved.get("path", "")) if saved.get("path") else None
        inside = bool(written) and written.parent == exports
        result.record(
            status == 200 and inside and written.is_file(),
            "saving an export lands inside the export folder",
            str(written),
        )
        result.record(
            (exports / "report.txt").exists() or inside,
            "a directory in the file name is stripped, not followed",
        )
        status, body = _post(port, "/api/desktop/save",
                             {"name": "view.html", "content": "<html>view</html>"}, token=token)
        result.record(status == 200, "saving a printable view", f"HTTP {status}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        workstation.disconnect()

    # -- the desktop bridge script itself --------------------------------
    from .desktop import DesktopBridge  # noqa: F401  (import check only)

    result.record(True, "desktop shell module imports")


class _SelftestBridge:
    """A stand-in host object: the self-test is checking the server, not a window."""

    def __init__(self, exports: Path) -> None:
        self.exports = Path(exports)

    def info(self) -> dict:
        return {"available": True, "host": "selftest", "version": __version__,
                "exports": str(self.exports), "note": "self-test host object"}

    def save_text(self, name: str, content: str) -> dict:
        path = resources.unique_path(self.exports, name)
        path.write_text(content, encoding="utf-8")
        return {"name": path.name, "path": str(path), "dir": str(path.parent),
                "bytes": len(content)}

    def print_view(self, html: str) -> dict:
        path = resources.unique_path(self.exports, "guzzionboard-view.html")
        path.write_text(html, encoding="utf-8")
        return {"path": str(path), "opened": False, "note": "self-test"}

    def open_external(self, url: str) -> dict:
        return {"ok": True, "url": url, "note": "self-test"}

    def open_folder(self, which: str) -> dict:
        return {"ok": True, "path": str(self.exports), "which": which, "note": "self-test"}

    def raise_window(self) -> dict:
        return {"ok": True, "focused": False, "url": "http://127.0.0.1/", "reason": "self-test"}

    def quit(self) -> dict:
        return {"ok": True, "note": "self-test"}

    def bridge_script(self) -> bytes:
        return b"/* selftest bridge */\n"


def _check_worker(result: Result) -> None:
    """Round-trip a plugin through the isolated checksum worker, when shipped."""
    from .checksums import ChecksumUnavailable, load_providers, worker_command

    command = worker_command()
    if resources.frozen():
        result.record(command is not None, "isolated checksum worker executable",
                      command[0] if command else "not present in this build")
    if command is None:
        return

    plugin = '''
PROVIDER_ID = "selftest.plugin"
NAME = "Self Test"
VERSION = "1"
SUPPORTED_CHECKSUMS = ["GuzziOnBoard self test"]


def update(image, context):
    return bytes(image)


def verify(image, context):
    return True
'''
    with tempfile.TemporaryDirectory(prefix="guzzionboard-selftest-plugins-") as plugins:
        directory = Path(plugins)
        (directory / "selftest_plugin.py").write_text(plugin, encoding="utf-8")
        providers, errors = load_providers(directory)
        ok = len(providers) == 1 and not errors
        detail = providers[0].provider_id if ok else f"errors: {errors or 'none'}"
        result.record(ok, "checksum plugin loads in its own process", detail)
        if not ok:
            return
        try:
            out, _verify = providers[0]._isolated_apply(b"12345678", {"region": "flash"})
            result.record(out == b"12345678", "checksum plugin round trip")
        except ChecksumUnavailable as exc:
            result.record(False, "checksum plugin round trip", str(exc))


if __name__ == "__main__":        # pragma: no cover - manual launch
    sys.exit(run(verbose=True))
