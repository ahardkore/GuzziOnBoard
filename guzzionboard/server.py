"""Dependency-free local HTTP API and static file server.

This is the seam a desktop shell would replace. It binds locally, speaks JSON,
and holds exactly one :class:`~guzzionboard.workstation.Workstation`.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import adapter as adapter_mod
from . import canlog
from . import tools
from .catalog import CatalogError
from .diagnostics import NotConnected
from .firmware import FirmwareImage, FirmwareError
from .maps import XDF_DIR, XdfError, XdfFile, load_xdfs
from .programming import ProgrammingError, ProgrammingService
from .safety import SafetyViolation
from .security import SecurityUnavailable, describe_all, load_plugins
from .sessionlog import SessionLog
from .transports.base import TransportError, TransportUnavailable
from .workstation import Workstation

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


class JobRunner:
    """One long-running memory operation at a time, with live progress.

    Reading an ECU takes twenty to thirty minutes, so these cannot run inside
    a request. Exactly one job may be in flight: concurrent flash operations
    on one ECU are never something the user meant.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict = {"name": None, "state": "idle"}

    def start(self, name: str, fn) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ProgrammingError(
                    f"{self._state['name']} is still running; wait for it to "
                    "finish or disconnect"
                )
            self._state = {
                "name": name, "state": "running", "started": time.time(),
                "progress": None, "result": None, "error": None,
            }

        def report(progress):
            self._state["progress"] = progress.as_dict()

        def target():
            try:
                result = fn(report)
                self._state["result"] = result
                self._state["state"] = "done"
            except BaseException as exc:
                self._state["error"] = f"{type(exc).__name__}: {exc}"
                self._state["state"] = "failed"
            finally:
                self._state["finished"] = time.time()

        self._thread = threading.Thread(target=target, daemon=True, name=name)
        self._thread.start()
        return self.status()

    def status(self) -> dict:
        state = dict(self._state)
        state["running"] = bool(self._thread and self._thread.is_alive())
        return state


class Api:
    """Route table. Each handler returns ``(status, payload)``."""

    def __init__(self, workstation: Workstation):
        self.ws = workstation
        self._prog: ProgrammingService | None = None
        self.jobs = JobRunner()

    # -- catalog ----------------------------------------------------------
    def get_catalog(self, query: dict) -> tuple[int, dict]:
        catalog = self.ws.catalog
        return 200, {
            "summary": catalog.summary(),
            "makes": catalog.makes(),
            "models": [
                {
                    "model": model,
                    "variants": [v.as_dict() for v in catalog.find(model)],
                }
                for model in catalog.models()
            ],
            "vehicles": [
                {
                    "make": v.make, "model": v.model,
                    "year_from": v.year_from, "year_to": v.year_to,
                    "ecu": v.ecu,
                }
                for v in catalog.vehicles
            ],
            "ecus": [e.as_dict() for e in catalog.ecus.values()],
        }

    def get_resolve(self, query: dict) -> tuple[int, dict]:
        model = (query.get("model") or [""])[0]
        make = (query.get("make") or [""])[0]
        year = int((query.get("year") or ["0"])[0] or 0)
        matches = self.ws.catalog.find(model, year or None, make)
        return 200, {
            "model": model,
            "make": make,
            "year": year,
            "ambiguous": len(matches) > 1,
            "matches": [
                {**m.as_dict(), "ecu_detail": self.ws.catalog.ecu(m.ecu).as_dict()}
                for m in matches
            ],
        }

    # -- lifecycle --------------------------------------------------------
    def post_select(self, body: dict) -> tuple[int, dict]:
        try:
            return 200, self.ws.select(
                model=body.get("model", ""),
                year=int(body.get("year") or 0),
                ecu=body.get("ecu", ""),
                make=body.get("make", ""),
                transport=body.get("transport", "simulator"),
                device=body.get("device", ""),
                can_tx_id=body.get("can_tx_id", ""),
                can_rx_id=body.get("can_rx_id", ""),
            )
        except ValueError as exc:
            return 400, {"error": str(exc)}

    def post_connect(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.connect(
            mode=body.get("mode", "simulator"),
            init_method=body.get("init_method"),
        )

    def post_disconnect(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.disconnect()

    def get_status(self, query: dict) -> tuple[int, dict]:
        return 200, self.ws.status()

    def post_checklist(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.accept_checklist(bool(body.get("accepted")))

    # -- diagnostics ------------------------------------------------------
    def get_identify(self, query: dict) -> tuple[int, dict]:
        return 200, self.ws.require_service().identify().as_dict()

    def get_live(self, query: dict) -> tuple[int, dict]:
        keys = (query.get("keys") or [""])[0]
        selected = [k for k in keys.split(",") if k] or None
        samples = self.ws.require_service().read_parameters(selected)
        return 200, {
            "at": samples[0].at if samples else 0,
            "samples": [s.as_dict() for s in samples],
        }

    def get_parameters(self, query: dict) -> tuple[int, dict]:
        profile = self.ws.selection.profile
        if profile is None:
            return 400, {"error": "no vehicle selected"}
        return 200, {"parameters": [p.as_dict() for p in profile.live_parameters]}

    def get_dtcs(self, query: dict) -> tuple[int, dict]:
        service = self.ws.require_service()
        dtcs = service.read_dtcs()
        decision = service.check_clear_dtcs()
        return 200, {"dtcs": dtcs, "clear": decision.as_dict()}

    def post_dtcs_clear(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.require_service().clear_dtcs(body.get("token", ""))

    # -- service actions --------------------------------------------------
    def get_actuators(self, query: dict) -> tuple[int, dict]:
        service = self.ws.require_service()
        out = []
        for actuator in service.profile.actuators:
            decision = service.check_actuator(actuator.key)
            out.append({**actuator.as_dict(), "decision": decision.as_dict()})
        return 200, {"actuators": out, "active": service.active_outputs and {
            k: round(v, 1) for k, v in service.active_outputs.items()
        } or {}}

    def post_actuator_pulse(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.require_service().pulse_actuator(
            body["key"], body.get("token", ""), body.get("seconds")
        )

    def post_actuator_release(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.require_service().release_actuator(body["key"])

    def get_routines(self, query: dict) -> tuple[int, dict]:
        service = self.ws.require_service()
        out = []
        for routine in service.profile.routines:
            decision = service.check_routine(routine.key)
            out.append({**routine.as_dict(), "decision": decision.as_dict()})
        return 200, {"routines": out}

    def post_routine_run(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.require_service().run_routine(
            body["key"], body.get("token", "")
        )

    # -- discovery --------------------------------------------------------
    def post_discover(self, body: dict) -> tuple[int, dict]:
        service = self.ws.require_service()
        return 200, service.discover_identifiers(
            int(body.get("start", 0x30)), int(body.get("end", 0x7F))
        )

    # -- sessions and reports ---------------------------------------------
    def get_sessions(self, query: dict) -> tuple[int, dict]:
        return 200, {"sessions": SessionLog.list_sessions(self.ws.session_dir)}

    def get_session_events(self, query: dict) -> tuple[int, dict]:
        name = (query.get("name") or [""])[0]
        path = Path(self.ws.session_dir) / name
        if not name or not path.is_file() or path.parent != Path(self.ws.session_dir):
            return 404, {"error": "no such session"}
        limit = int((query.get("limit") or ["500"])[0])
        events = list(SessionLog.read(path))
        return 200, {"name": name, "total": len(events), "events": events[-limit:]}

    def get_report(self, query: dict) -> tuple[int, dict]:
        report = self.ws.build_report()
        return 200, {"report": report, "text": self.ws.report_text(report)}

    # -- memory and programming ------------------------------------------
    def _programming(self) -> ProgrammingService:
        if self._prog is None or self._prog.diag is not self.ws.require_service():
            self._prog = ProgrammingService(self.ws.require_service())
        return self._prog

    def get_memory(self, query: dict) -> tuple[int, dict]:
        prog = self._programming()
        return 200, {
            "capabilities": prog.capabilities(),
            "job": self.jobs.status(),
            "checkpoints": {
                name: prog.pending_checkpoint(name)
                for name in prog.regions()
            },
            "acknowledgement": self.ws.gate.PROGRAMMING_ACKNOWLEDGEMENT,
            "programming_enabled": self.ws.gate.allow_programming,
        }

    def get_memory_progress(self, query: dict) -> tuple[int, dict]:
        return 200, self.jobs.status()

    def post_memory_backup(self, body: dict) -> tuple[int, dict]:
        prog = self._programming()
        region = body.get("region", "flash")

        def run(report):
            return prog.backup(region, progress=report)

        return 202, self.jobs.start(f"backup:{region}", run)

    def post_memory_read(self, body: dict) -> tuple[int, dict]:
        prog = self._programming()
        region = body.get("region", "flash")

        def run(report):
            image = prog.read_region(region, progress=report)
            path = image.save(prog.image_dir / f"{prog.profile.id}-{region}-read.bin")
            return {"path": str(path), "describe": image.describe()}

        return 202, self.jobs.start(f"read:{region}", run)

    def post_memory_validate(self, body: dict) -> tuple[int, dict]:
        prog = self._programming()
        path = body.get("path")
        if not path:
            return 400, {"error": "a 'path' to an image file is required"}
        try:
            image = FirmwareImage.from_file(path)
        except OSError as exc:
            return 400, {"error": str(exc)}
        return 200, prog.validate(image, body.get("region", "flash"))

    def post_memory_write(self, body: dict) -> tuple[int, dict]:
        prog = self._programming()
        region = body.get("region", "flash")
        path, token = body.get("path"), body.get("token")
        if not path or not token:
            return 400, {"error": "'path' and 'token' are both required"}
        image = FirmwareImage.from_file(path)

        def run(report):
            return prog.write_region(image, token, region, progress=report)

        return 202, self.jobs.start(f"write:{region}", run)

    def post_memory_check_write(self, body: dict) -> tuple[int, dict]:
        decision = self._programming().check_write(body.get("region", "flash"))
        return 200, decision.as_dict()

    # -- maps (TunerPro XDF) -----------------------------------------------
    def get_maps(self, query: dict) -> tuple[int, dict]:
        xdfs = load_xdfs()
        return 200, {
            "directory": str(XDF_DIR),
            "xdfs": [x.describe() for x in xdfs],
        }

    def _load_xdf(self, ref: str) -> XdfFile:
        """An XDF from the plugin directory (by title or filename), or a path."""
        for xdf in load_xdfs():
            if ref in (xdf.title, Path(xdf.path).name if xdf.path else None):
                return xdf
        if Path(ref).suffix.lower() == ".xdf":
            return XdfFile.from_file(ref)
        raise XdfError(
            f"no XDF named {ref!r} in {XDF_DIR}, and not a .xdf path either"
        )

    @staticmethod
    def _address_base(body: dict) -> int | None:
        base = body.get("address_base")
        if base in (None, ""):
            return None
        try:
            return int(str(base), 0)
        except ValueError:
            raise XdfError(f"address_base {base!r} is not a number") from None

    def post_maps_render(self, body: dict) -> tuple[int, dict]:
        path, ref = body.get("path"), body.get("xdf")
        if not path:
            return 400, {"error": "an image 'path' is required"}
        if not ref:
            return 400, {"error": "an 'xdf' (title or .xdf path) is required"}
        try:
            image = FirmwareImage.from_file(path)
        except OSError as exc:
            return 400, {"error": str(exc)}
        try:
            xdf = self._load_xdf(ref)
        except XdfError as exc:
            return 400, {"error": str(exc)}
        try:
            render = xdf.render(image, address_base=self._address_base(body))
        except XdfError as exc:
            return 400, {"error": str(exc)}
        return 200, {**render, "image": image.describe()}

    def post_maps_diff(self, body: dict) -> tuple[int, dict]:
        a, b, ref = body.get("path_a"), body.get("path_b"), body.get("xdf")
        if not (a and b):
            return 400, {"error": "'path_a' and 'path_b' are both required"}
        if not ref:
            return 400, {"error": "an 'xdf' (title or .xdf path) is required"}
        try:
            before, after = FirmwareImage.from_file(a), FirmwareImage.from_file(b)
        except OSError as exc:
            return 400, {"error": str(exc)}
        try:
            xdf = self._load_xdf(ref)
        except XdfError as exc:
            return 400, {"error": str(exc)}
        try:
            diff = xdf.diff(before, after, address_base=self._address_base(body))
        except XdfError as exc:
            return 400, {"error": str(exc)}
        return 200, {**diff, "image": before.describe()}

    def post_programming_enable(self, body: dict) -> tuple[int, dict]:
        self.ws.gate.enable_programming(body.get("acknowledgement", ""))
        return 200, {"programming_enabled": True}

    def post_programming_disable(self, body: dict) -> tuple[int, dict]:
        self.ws.gate.disable_programming()
        return 200, {"programming_enabled": False}

    def get_security(self, query: dict) -> tuple[int, dict]:
        load_plugins()
        return 200, {
            "providers": describe_all(),
            "plugin_dir": str(__import__("guzzionboard.security",
                                         fromlist=["PLUGIN_DIR"]).PLUGIN_DIR),
        }

    # -- adapter and tools ------------------------------------------------
    def get_adapter(self, query: dict) -> tuple[int, dict]:
        port = (query.get("port") or [""])[0]
        loopback = (query.get("loopback") or ["0"])[0] == "1"
        report = adapter_mod.check_adapter(port, loopback=loopback)
        return 200, {
            "report": report.as_dict(),
            "text": report.text(),
            "ports": adapter_mod.list_ports(),
        }

    def post_adapter_latency(self, body: dict) -> tuple[int, dict]:
        port = body.get("port", "")
        ok = adapter_mod.set_latency_timer(port, int(body.get("value", 1)))
        return 200, {
            "ok": ok,
            "latency_ms": adapter_mod.read_latency_timer(port),
            "instructions": "" if ok else adapter_mod.latency_fix_instructions(port),
        }

    def post_tools_canlog(self, body: dict) -> tuple[int, dict]:
        """Analyse a passively sniffed CAN capture: which ids are the pair?

        Accepts a file ``path`` (candump, SavvyCAN CSV or CRTD) or pasted
        ``text``. Read-only by construction: it never touches hardware.
        """
        path, text = body.get("path"), body.get("text")
        if not path and not text:
            return 400, {"error": "a capture 'path' or pasted 'text' is required"}
        try:
            if path:
                result = canlog.analyze_capture_file(path)
            else:
                result = canlog.analyze_capture_text(str(text))
        except canlog.CanLogError as exc:
            return 400, {"error": str(exc)}
        return 200, result

    def get_gearing(self, query: dict) -> tuple[int, dict]:
        def number(name, default):
            try:
                return float((query.get(name) or [default])[0])
            except (TypeError, ValueError):
                return default

        gearing = tools.Gearing(
            final_drive=number("final_drive", 4.125),
            tyre=(query.get("tyre") or ["180/55-17"])[0],
        )
        return 200, gearing.table()

    def get_export(self, query: dict) -> tuple[int, dict]:
        name = (query.get("name") or [""])[0]
        fmt = (query.get("format") or ["csv"])[0]
        if fmt not in tools.EXPORTERS:
            return 400, {"error": f"unknown format {fmt!r}"}
        path = Path(self.ws.session_dir) / name
        if not name or not path.is_file() or path.parent != Path(self.ws.session_dir):
            return 404, {"error": "no such session"}
        events = list(SessionLog.read(path))
        return 200, {"format": fmt, "name": name,
                     "content": tools.EXPORTERS[fmt](events)}


ROUTES_GET = {
    "/api/catalog": "get_catalog",
    "/api/catalog/resolve": "get_resolve",
    "/api/status": "get_status",
    "/api/identify": "get_identify",
    "/api/live": "get_live",
    "/api/parameters": "get_parameters",
    "/api/dtcs": "get_dtcs",
    "/api/actuators": "get_actuators",
    "/api/routines": "get_routines",
    "/api/sessions": "get_sessions",
    "/api/sessions/events": "get_session_events",
    "/api/report": "get_report",
    "/api/maps": "get_maps",
    "/api/memory": "get_memory",
    "/api/memory/progress": "get_memory_progress",
    "/api/security": "get_security",
    "/api/adapter": "get_adapter",
    "/api/tools/gearing": "get_gearing",
    "/api/sessions/export": "get_export",
}

ROUTES_POST = {
    "/api/select": "post_select",
    "/api/connect": "post_connect",
    "/api/disconnect": "post_disconnect",
    "/api/checklist": "post_checklist",
    "/api/dtcs/clear": "post_dtcs_clear",
    "/api/actuators/pulse": "post_actuator_pulse",
    "/api/actuators/release": "post_actuator_release",
    "/api/routines/run": "post_routine_run",
    "/api/discover": "post_discover",
    "/api/memory/backup": "post_memory_backup",
    "/api/memory/read": "post_memory_read",
    "/api/memory/validate": "post_memory_validate",
    "/api/memory/write": "post_memory_write",
    "/api/memory/check-write": "post_memory_check_write",
    "/api/maps/render": "post_maps_render",
    "/api/maps/diff": "post_maps_diff",
    "/api/programming/enable": "post_programming_enable",
    "/api/programming/disable": "post_programming_disable",
    "/api/adapter/latency": "post_adapter_latency",
    "/api/tools/canlog": "post_tools_canlog",
}


def make_handler(workstation: Workstation):
    api = Api(workstation)

    class Handler(BaseHTTPRequestHandler):
        server_version = "GuzziOnBoard"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        # -- helpers ------------------------------------------------------
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # Local tool: no third-party origins, no framing surprises.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(
                status,
                json.dumps(payload, default=str).encode("utf-8"),
                "application/json",
            )

        def _dispatch(self, table: dict, name: str, arg) -> None:
            handler = getattr(api, table[name])
            try:
                status, payload = handler(arg)
            except NotConnected as exc:
                status, payload = 409, {"error": str(exc), "code": "not_connected"}
            except SafetyViolation as exc:
                status, payload = 403, {
                    "error": str(exc), "code": "safety",
                    "decision": exc.decision.as_dict(),
                }
            except PermissionError as exc:
                status, payload = 403, {"error": str(exc), "code": "refused"}
            except (CatalogError, ValueError, KeyError) as exc:
                status, payload = 400, {"error": str(exc), "code": "bad_request"}
            except TransportUnavailable as exc:
                status, payload = 501, {"error": str(exc), "code": "no_driver"}
            except TransportError as exc:
                status, payload = 502, {"error": str(exc), "code": "transport"}
            except SecurityUnavailable as exc:
                status, payload = 501, {"error": str(exc), "code": "no_key_provider"}
            except (ProgrammingError, FirmwareError) as exc:
                status, payload = 409, {"error": str(exc), "code": "programming"}
            except PermissionError as exc:
                status, payload = 403, {"error": str(exc), "code": "token"}
            except Exception as exc:  # pragma: no cover - last resort
                traceback.print_exc()
                status, payload = 500, {"error": str(exc), "code": "internal"}
            self._json(status, payload)

        # -- verbs --------------------------------------------------------
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ROUTES_GET:
                self._dispatch(ROUTES_GET, parsed.path, parse_qs(parsed.query))
                return
            if parsed.path.startswith("/api/"):
                self._json(404, {"error": f"no route {parsed.path}"})
                return
            self._serve_static(parsed.path)

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path not in ROUTES_POST:
                self._json(404, {"error": f"no route {parsed.path}"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError as exc:
                self._json(400, {"error": f"bad JSON body: {exc}"})
                return
            self._dispatch(ROUTES_POST, parsed.path, body)

        # -- static -------------------------------------------------------
        def _serve_static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / rel).resolve()
            try:
                target.relative_to(WEB_ROOT.resolve())
            except ValueError:
                self._send(403, b"forbidden", "text/plain")
                return
            if not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            suffix = target.suffix
            content_type = CONTENT_TYPES.get(
                suffix, mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
            self._send(200, target.read_bytes(), content_type)

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8000, *, record: bool = True) -> None:
    workstation = Workstation(record=record)
    summary = workstation.catalog.summary()
    print(f"GuzziOnBoard {workstation.status()['version']}")
    print(
        f"  catalog: {summary['ecu_count']} ECU families, "
        f"{summary['vehicle_count']} model variants, "
        f"{summary['year_range'][0]}-{summary['year_range'][1]}"
    )
    print(f"  listening on http://{host}:{port}")
    print("  simulator mode is the default; no serial port is opened until you ask.")
    server = ThreadingHTTPServer((host, port), make_handler(workstation))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        workstation.disconnect()
        server.server_close()


if __name__ == "__main__":
    serve()
