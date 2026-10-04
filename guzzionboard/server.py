"""Dependency-free local HTTP API and static file server.

This is the seam a desktop shell would replace. It binds locally, speaks JSON,
and holds exactly one :class:`~guzzionboard.workstation.Workstation`.
"""
from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import CatalogError
from .diagnostics import NotConnected
from .safety import SafetyViolation
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


class Api:
    """Route table. Each handler returns ``(status, payload)``."""

    def __init__(self, workstation: Workstation):
        self.ws = workstation

    # -- catalog ----------------------------------------------------------
    def get_catalog(self, query: dict) -> tuple[int, dict]:
        catalog = self.ws.catalog
        return 200, {
            "summary": catalog.summary(),
            "models": [
                {
                    "model": model,
                    "variants": [v.as_dict() for v in catalog.find(model)],
                }
                for model in catalog.models()
            ],
            "ecus": [e.as_dict() for e in catalog.ecus.values()],
        }

    def get_resolve(self, query: dict) -> tuple[int, dict]:
        model = (query.get("model") or [""])[0]
        year = int((query.get("year") or ["0"])[0] or 0)
        matches = self.ws.catalog.find(model, year or None)
        return 200, {
            "model": model,
            "year": year,
            "ambiguous": len(matches) > 1,
            "matches": [
                {**m.as_dict(), "ecu_detail": self.ws.catalog.ecu(m.ecu).as_dict()}
                for m in matches
            ],
        }

    # -- lifecycle --------------------------------------------------------
    def post_select(self, body: dict) -> tuple[int, dict]:
        return 200, self.ws.select(
            model=body.get("model", ""),
            year=int(body.get("year") or 0),
            ecu=body.get("ecu", ""),
            transport=body.get("transport", "simulator"),
            device=body.get("device", ""),
        )

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
