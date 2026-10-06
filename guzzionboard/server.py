"""Dependency-free local HTTP API and static file server.

This is the seam a desktop shell would replace. It binds locally, speaks JSON,
and holds exactly one :class:`~guzzionboard.workstation.Workstation`.
"""
from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import adapter as adapter_mod
from . import canlog
from . import klinelog
from . import logconvert
from . import rpmsignal
from . import tools
from .basemap import BaseMapError
from .catalog import CatalogError
from .derived import CHANNELS as DERIVED_CHANNELS, Analyzer
from .transports.simulator import FAULTS as SIM_FAULTS, FAULTS_BY_KEY as SIM_FAULTS_BY_KEY
from .diagnostics import NotConnected
from .firmware import FirmwareImage, FirmwareError
from .maps import (
    BUNDLED_XDF_DIR,
    XDF_DIR,
    XdfError,
    XdfFile,
    available_xdfs,
    fitment,
    group_xdfs,
)
from .checksums import (
    PLUGIN_DIR as CHECKSUM_PLUGIN_DIR,
    ChecksumUnavailable,
    load_providers as load_checksum_providers,
    provider_by_id as checksum_provider_by_id,
)
from .map_analysis import LogAnalysisError, analyze_fuel_log
from .programming import ProgrammingError, ProgrammingService
from .physical_validation import (
    VALIDATION_DIR as PHYSICAL_VALIDATION_DIR,
    PhysicalValidationError,
    load_manifests as load_physical_validation,
    validate_manifest as validate_physical_manifest,
)
from .recommendations import (
    PACKAGE_DIR as RECOMMENDATION_PACKAGE_DIR,
    RecommendationPackageError,
    load_packages as load_recommendation_packages,
    validate_package as validate_recommendation_package,
)
from .tuning import (
    TUNING_ACKNOWLEDGEMENT,
    TuningError,
    build_tune,
    prepare_tune,
)
from .safety import SafetyViolation, TokenError
from .security import SecurityUnavailable, describe_all, load_plugins
from . import procedures
from . import replay
from . import sessiondiff
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


#: The workstation page ships with ``web/demo-api.js``, an in-browser stand-in
#: for this server used when the page is hosted statically (GitHub Pages).
#: When *this* process is serving the page there is a real backend, so the
#: body is marked and the shim stands down. One marker, no guessing from
#: hostnames or ports.
LIVE_BACKEND_MARKER = b'<body data-backend="live">'


def mark_live_backend(body: bytes) -> bytes:
    """Tag the served workstation page as backed by this process."""
    if LIVE_BACKEND_MARKER in body:
        return body
    return body.replace(b"<body>", LIVE_BACKEND_MARKER, 1)


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
        #: Derived channels and plausibility checks keep a short rolling
        #: window, so the analyzer outlives a single request but is thrown
        #: away whenever the underlying conversation changes.
        self._analyzer: Analyzer | None = None
        self._analyzer_for = None
        #: The guided procedure currently being worked through, if any.
        self._run: procedures.ProcedureRun | None = None
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

    def _analysis(self) -> Analyzer:
        service = self.ws.require_service()
        if self._analyzer is None or self._analyzer_for is not service:
            self._analyzer = Analyzer(service.profile)
            self._analyzer_for = service
        return self._analyzer

    def get_live(self, query: dict) -> tuple[int, dict]:
        keys = (query.get("keys") or [""])[0]
        selected = [k for k in keys.split(",") if k] or None
        service = self.ws.require_service()
        samples = service.read_parameters(selected)
        analysis = self._analysis().update(samples)
        return 200, {
            "at": samples[0].at if samples else 0,
            "samples": [s.as_dict() for s in samples],
            "derived": analysis["derived"],
            "findings": analysis["findings"],
            "analysis_note": (
                "Derived values are computed by the workstation from the "
                "samples above, not read from the ECU. Findings are "
                "interpretations, not measurements."
            ),
        }

    # -- the simulated motorcycle -----------------------------------------
    #
    # Controls for the built-in simulator only. There is deliberately no
    # equivalent for a real bike: nothing here may ever reach down a K-Line.

    def _simulated_ecu(self):
        """The :class:`SimulatedEcu` behind the current connection, if any."""
        service = self.ws.service
        transport = getattr(service, "transport", None) if service else None
        return getattr(transport, "ecu", None)

    def _sim_payload(self, ecu) -> dict:
        return {
            "available": True,
            "transport": self.ws.selection.transport_kind,
            "engine": ecu.engine.as_dict(),
            "faults": [
                {**f.as_dict(), "active": f.key in ecu.engine.faults}
                for f in SIM_FAULTS
            ],
            "comms": {
                "drop_rate": ecu.drop_rate,
                "corrupt_rate": ecu.corrupt_rate,
                "pending_rate": ecu.pending_rate,
                "extra_latency": ecu.extra_latency,
            },
            "dtc_timing": {
                "pending_after": ecu.dtc_pending_after,
                "confirm_after": ecu.dtc_confirm_after,
            },
            "note": (
                "This is the simulated motorcycle, not a setting on a real "
                "one. Seeded faults change the live channels first and mature "
                "into fault memory afterwards."
            ),
        }

    def get_sim(self, query: dict) -> tuple[int, dict]:
        ecu = self._simulated_ecu()
        if ecu is None:
            return 200, {
                "available": False,
                "transport": self.ws.selection.transport_kind,
                "faults": [f.as_dict() for f in SIM_FAULTS],
                "reason": (
                    "Connect with the simulator (or the virtual CAN bus) to "
                    "drive the simulated engine."
                ),
            }
        return 200, self._sim_payload(ecu)

    def post_sim_engine(self, body: dict) -> tuple[int, dict]:
        ecu = self._simulated_ecu()
        if ecu is None:
            return 400, {"error": "not connected to a simulated ECU"}
        engine = ecu.engine
        if "running" in body:
            engine.start() if bool(body["running"]) else engine.stop()
        if "throttle_pct" in body:
            engine.throttle_pct = max(0.0, min(100.0, float(body["throttle_pct"])))
            engine.auto_blip = False
        if "ambient_c" in body:
            engine.ambient_c = max(-30.0, min(55.0, float(body["ambient_c"])))
        if "battery_health" in body:
            engine.battery_health = max(0.5, min(1.1, float(body["battery_health"])))
        if "in_gear" in body:
            engine.in_gear = bool(body["in_gear"])
        if "auto_blip" in body:
            engine.auto_blip = bool(body["auto_blip"])
        if "advance_s" in body:
            engine.advance(max(0.0, min(3600.0, float(body["advance_s"]))))
        return 200, self._sim_payload(ecu)

    def post_sim_faults(self, body: dict) -> tuple[int, dict]:
        ecu = self._simulated_ecu()
        if ecu is None:
            return 400, {"error": "not connected to a simulated ECU"}
        if "faults" in body:
            requested = list(body["faults"] or [])
        else:
            requested = list(ecu.engine.faults)
            key = body.get("key")
            if key:
                if bool(body.get("active", True)):
                    requested.append(key)
                else:
                    requested = [k for k in requested if k != key]
        unknown = [k for k in requested if k not in SIM_FAULTS_BY_KEY]
        if unknown:
            return 400, {"error": f"unknown fault(s): {', '.join(unknown)}"}
        ecu.engine.set_faults(requested)
        return 200, self._sim_payload(ecu)

    def post_sim_comms(self, body: dict) -> tuple[int, dict]:
        ecu = self._simulated_ecu()
        if ecu is None:
            return 400, {"error": "not connected to a simulated ECU"}
        for key in ("drop_rate", "corrupt_rate", "pending_rate"):
            if key in body:
                setattr(ecu, key, max(0.0, min(1.0, float(body[key]))))
        if "extra_latency" in body:
            ecu.extra_latency = max(0.0, min(2.0, float(body["extra_latency"])))
        return 200, self._sim_payload(ecu)

    def get_derived_catalog(self, query: dict) -> tuple[int, dict]:
        return 200, {"channels": [
            {"key": c.key, "name": c.name, "unit": c.unit, "group": c.group,
             "sources": list(c.sources), "note": c.note, "delta": c.delta}
            for c in DERIVED_CHANNELS
        ]}

    def get_parameters(self, query: dict) -> tuple[int, dict]:
        profile = self.ws.selection.profile
        if profile is None:
            return 400, {"error": "no vehicle selected"}
        return 200, {"parameters": [p.as_dict() for p in profile.live_parameters]}

    def get_dtcs(self, query: dict) -> tuple[int, dict]:
        service = self.ws.require_service()
        result = service.read_dtcs()
        decision = service.check_clear_dtcs()
        return 200, {
            **result,
            "context_note": (
                "Observed by the workstation at read time - these ECUs do not "
                "expose an ECU-stored freeze frame, and this is not one."
            ),
            "clear": decision.as_dict(),
        }

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

    def post_sessions_compare(self, body: dict) -> tuple[int, dict]:
        a, b = body.get("a"), body.get("b")
        if not (a and b):
            return 400, {"error": "two session names, 'a' and 'b', are required"}
        if a == b:
            return 400, {"error": "pick two different sessions"}
        paths = {}
        for name in (a, b):
            candidate = Path(self.ws.session_dir) / name
            if not name or not candidate.is_file() or \
                    candidate.parent != Path(self.ws.session_dir):
                return 404, {"error": f"no such session: {name!r}"}
            paths[name] = candidate
        try:
            return 200, sessiondiff.compare(paths[a], paths[b])
        except sessiondiff.SessionDiffError as exc:
            return 400, {"error": str(exc)}

    def get_session_events(self, query: dict) -> tuple[int, dict]:
        name = (query.get("name") or [""])[0]
        path = Path(self.ws.session_dir) / name
        if not name or not path.is_file() or path.parent != Path(self.ws.session_dir):
            return 404, {"error": "no such session"}
        limit = int((query.get("limit") or ["500"])[0])
        events = list(SessionLog.read(path))
        return 200, {"name": name, "total": len(events), "events": events[-limit:]}

    def _session_path(self, name: str):
        path = Path(self.ws.session_dir) / name
        if not name or not path.is_file() or path.parent != Path(self.ws.session_dir):
            return None
        return path

    def get_session_replay(self, query: dict) -> tuple[int, dict]:
        """Scrubbable snapshots, with derived values and findings redone."""
        name = (query.get("name") or [""])[0]
        path = self._session_path(name)
        if path is None:
            return 404, {"error": "no such session"}
        events = list(SessionLog.read(path))
        profile = self.ws.selection.profile
        payload = replay.frames(events, profile)
        payload["name"] = name
        return 200, payload

    # -- guided procedures ------------------------------------------------

    def get_procedures(self, query: dict) -> tuple[int, dict]:
        run = self._run.as_dict() if self._run else None
        return 200, {
            "procedures": procedures.available(self.ws.selection.profile),
            "run": run,
            "note": (
                "A procedure only puts together things the catalog already "
                "describes. Observations are live reads, outputs go through "
                "the safety gate, and the verdict is an interpretation."
            ),
        }

    def post_procedure_start(self, body: dict) -> tuple[int, dict]:
        key = body.get("key", "")
        procedure = procedures.PROCEDURES_BY_KEY.get(key)
        if procedure is None:
            return 400, {"error": f"unknown procedure {key!r}"}
        service = self.ws.require_service()
        missing = procedure.missing_for(service.profile)
        if missing:
            return 400, {"error": "this ECU family is missing: " + ", ".join(missing)}
        self._run = procedures.ProcedureRun(procedure, service)
        service.log.action("procedure_start", {"key": key, "name": procedure.name})
        return 200, {"run": self._run.as_dict()}

    def post_procedure_advance(self, body: dict) -> tuple[int, dict]:
        if self._run is None:
            return 400, {"error": "no procedure is running"}
        try:
            state = self._run.advance(body.get("value"))
        except procedures.ProcedureError as exc:
            return 400, {"error": str(exc)}
        if state["status"] in ("done", "blocked"):
            self.ws.require_service().log.action(
                "procedure_end",
                {"key": state["procedure"], "status": state["status"],
                 "verdict": state["verdict"]},
            )
        return 200, {"run": state}

    def post_procedure_abort(self, body: dict) -> tuple[int, dict]:
        if self._run is None:
            return 400, {"error": "no procedure is running"}
        state = self._run.abort()
        return 200, {"run": state}

    def get_report(self, query: dict) -> tuple[int, dict]:
        report = self.ws.build_report()
        unit = (query.get("temp_unit") or ["C"])[0]
        return 200, {
            "report": report,
            "temp_unit": "F" if unit.upper().startswith("F") else "C",
            "text": self.ws.report_text(report, temp_unit=unit),
        }

    # -- memory and programming ------------------------------------------
    def _programming(self) -> ProgrammingService:
        if self._prog is None or self._prog.diag is not self.ws.require_service():
            self._prog = ProgrammingService(self.ws.require_service())
        return self._prog

    def get_memory(self, query: dict) -> tuple[int, dict]:
        prog = self._programming()
        return 200, {
            "base_map": prog.base_map_status(
                (query.get("region") or ["flash"])[0]
            ),
            "capabilities": prog.capabilities(),
            "job": self.jobs.status(),
            "checkpoints": {
                name: prog.pending_checkpoint(name)
                for name in prog.regions()
            },
            "acknowledgement": self.ws.gate.PROGRAMMING_ACKNOWLEDGEMENT,
            "programming_enabled": self.ws.gate.allow_programming,
            "unverified_keys_accepted": self.ws.gate.allow_unverified_keys,
        }

    def get_memory_progress(self, query: dict) -> tuple[int, dict]:
        return 200, self.jobs.status()

    def post_memory_backup(self, body: dict) -> tuple[int, dict]:
        prog = self._programming()
        region = body.get("region", "flash")

        def run(report):
            return prog.backup(region, progress=report)

        return 202, self.jobs.start(f"backup:{region}", run)

    # -- base maps (the guaranteed restore image) -------------------------
    def get_basemap(self, query: dict) -> tuple[int, dict]:
        prog = self._programming()
        region = (query.get("region") or ["flash"])[0]
        return 200, {
            "base_map": prog.base_map_status(region),
            "restore": prog.restore_plan(region),
            "vault": prog.vault.all_entries(),
            "directory": str(prog.vault.directory),
        }

    def post_basemap_save(self, body: dict) -> tuple[int, dict]:
        """File an image that is already on disk as this ECU's base map."""
        prog = self._programming()
        region = body.get("region", "flash")
        path = body.get("path") or self.ws.gate.state.backup_path
        if not path:
            return 400, {
                "error": "a 'path' to a verified image is required (or take a "
                         "verified backup first, which saves one automatically)"
            }
        if not body.get("verified", True):
            return 400, {"error": "only a verified image can be a base map"}
        try:
            result = prog.save_base_map(
                path, region, replace=bool(body.get("replace")),
                note=body.get("note", ""),
            )
        except BaseMapError as exc:
            return 400, {"error": str(exc)}
        return 200, {"base_map": prog.base_map_status(region), "result": result}

    def post_basemap_restore(self, body: dict) -> tuple[int, dict]:
        """The plan for putting the base map back.

        It deliberately does not flash anything by itself: restoring runs
        through ``/api/memory/write`` like every other write, with the same
        gate, acknowledgement and validation.
        """
        prog = self._programming()
        region = body.get("region", "flash")
        plan = prog.restore_plan(region)
        if not plan.get("ready"):
            return 400, {
                "error": plan.get("reason")
                or "no intact base map on file for this ECU",
                "base_map": plan,
            }
        return 200, {"restore": plan}

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
        region = body.get("region", "flash")
        image = None
        path = body.get("path")
        if path:
            # With the candidate image the decision includes the
            # hardware-family check, so a cross-family file (an HW1xx image
            # aimed at an HW3xx ECU, say) is refused before the operator
            # ever reaches the confirmation dialog.
            try:
                image = FirmwareImage.from_file(path)
            except OSError as exc:
                return 400, {"error": str(exc)}
        decision = self._programming().check_write(region, image=image)
        return 200, decision.as_dict()

    # -- maps (TunerPro XDF) -----------------------------------------------
    def get_maps(self, query: dict) -> tuple[int, dict]:
        xdfs = available_xdfs()
        described = [x.describe() for x in xdfs]
        # What the bike on the bench is, so the chooser can separate the
        # definitions that belong to it from the ones that do not. A map
        # from the wrong ECU family is not "a slightly wrong map": it is a
        # different calibration layout at the same addresses.
        vehicle = (self.ws.status() or {}).get("selection") or {}
        ecu = vehicle.get("ecu") or {}
        base_map = None
        if self.ws.service is not None:
            try:
                base_map = self._programming().base_map_status("flash")
            except (NotConnected, ProgrammingError):
                base_map = None
        return 200, {
            "directory": str(XDF_DIR),
            "bundled_directory": str(BUNDLED_XDF_DIR),
            "xdfs": described,
            "groups": group_xdfs(described),
            "vehicle": {
                "make": vehicle.get("make", ""),
                "model": vehicle.get("model", ""),
                "ecu_id": ecu.get("id", ""),
                "ecu_family": ecu.get("family", ""),
            },
            "base_map": base_map,
            "build": {
                "available": True,
                "acknowledgement": TUNING_ACKNOWLEDGEMENT,
                "requires_recommendation_evidence": True,
                "note": (
                    "Map builds are new files made from a hashed source. No "
                    "tuning values ship without a traceable recommendation."
                ),
            },
        }

    def _load_xdf(self, ref: str) -> XdfFile:
        """An XDF from the plugin/bundled directories (by filename or title),
        or a path.

        Filenames are tried first and titles only afterwards, because XDF
        titles are not unique - several unrelated files call themselves
        "15M Marelli". An ambiguous title is refused rather than resolved
        by accident: picking the wrong definition silently mislabels every
        table in the dump.
        """
        catalogue = available_xdfs()
        for xdf in catalogue:
            if xdf.path and Path(xdf.path).name == ref:
                return xdf
        by_title = [x for x in catalogue if x.title and x.title == ref]
        if len(by_title) == 1:
            return by_title[0]
        if len(by_title) > 1:
            names = ", ".join(sorted(Path(x.path).name for x in by_title))
            raise XdfError(
                f"{ref!r} is the title of {len(by_title)} different "
                f"definitions ({names}); select one by filename"
            )
        if Path(ref).suffix.lower() == ".xdf":
            return XdfFile.from_file(ref)
        raise XdfError(
            f"no XDF named {ref!r} in {XDF_DIR} or {BUNDLED_XDF_DIR}, "
            f"and not a .xdf path either"
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

    def _map_source(self, body: dict) -> tuple[FirmwareImage, bool, dict | None]:
        """Resolve an explicit image or the protected base-map vault copy."""
        use_base = bool(body.get("use_base_map"))
        status = None
        if use_base:
            region = str(body.get("region") or "flash")
            status = self._programming().base_map_status(region)
            if not status.get("intact"):
                raise TuningError(
                    status.get("reason") or
                    "no intact base map is available for this ECU"
                )
            path = status.get("path")
        else:
            path = body.get("path")
            if not path:
                raise TuningError(
                    "an image 'path' is required, or set use_base_map=true"
                )
            # Mark an explicitly named vault file accurately.  Failure to ask
            # the vault (for example while working offline) merely leaves it
            # as a non-base source; it never promotes a file by assumption.
            if self.ws.service is not None:
                try:
                    candidate = self._programming().base_map_status(
                        str(body.get("region") or "flash")
                    )
                    if candidate.get("intact"):
                        left = Path(str(path)).expanduser().resolve()
                        right = Path(str(candidate.get("path"))).expanduser().resolve()
                        if left == right:
                            status = candidate
                except (OSError, NotConnected, ProgrammingError):
                    pass
        try:
            image = FirmwareImage.from_file(path)
        except OSError as exc:
            raise TuningError(str(exc)) from exc
        return image, bool(status and status.get("intact")), status

    @staticmethod
    def _family_tokens(value: str) -> set[str]:
        compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
        return set(re.findall(
            r"MIUG3|MIU1|MBC1|5AM2|5AM|16M|15RC|15M|15P|59M|7SM|5SM|5DM|11MP|P7|P8",
            compact,
        ))

    def _check_build_fitment(self, xdf: XdfFile, image: FirmwareImage) -> None:
        """A mismatched XDF may be viewed, but it may never build bytes."""
        xdf_family = str(fitment(xdf.path).get("family") or "")
        if not xdf_family:
            raise TuningError(
                "this XDF has no cataloged ECU-family fitment; it may be "
                "rendered, but not used to build a flashable image"
            )
        expected: set[str] = set()
        if self.ws.selection.profile is not None:
            # A selected/connected bench is authoritative. Do not let a file
            # labelled as another ECU widen this set and make either family
            # appear acceptable.
            expected = self._family_tokens(self.ws.selection.profile.family)
        elif image.ecu_id:
            try:
                expected = self._family_tokens(self.ws.catalog.ecu(image.ecu_id).family)
            except CatalogError:
                pass
        actual = self._family_tokens(xdf_family)
        if expected and not (expected & actual):
            raise TuningError(
                f"the selected XDF is for {xdf_family}, but the source/bench "
                f"ECU is {'/'.join(sorted(expected))}; mismatched definitions "
                "can be rendered for inspection but cannot build a map"
            )

    def post_maps_render(self, body: dict) -> tuple[int, dict]:
        ref = body.get("xdf")
        if not ref:
            return 400, {"error": "an 'xdf' (title or .xdf path) is required"}
        try:
            image, is_base, base_status = self._map_source(body)
            xdf = self._load_xdf(ref)
            render = xdf.render(image, address_base=self._address_base(body))
            render["xdf"]["sha256"] = hashlib.sha256(
                Path(xdf.path).read_bytes()
            ).hexdigest() if xdf.path and Path(xdf.path).is_file() else ""
        except (XdfError, TuningError, OSError) as exc:
            return 400, {"error": str(exc)}
        return 200, {
            **render,
            "image": image.describe(),
            "source": {
                "path": image.path,
                "sha256": image.sha256,
                "is_base_map": is_base,
                "base_map": base_status,
            },
        }

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

    def post_maps_validate_definition(self, body: dict) -> tuple[int, dict]:
        ref = body.get("xdf")
        if not ref:
            return 400, {"error": "an 'xdf' (filename or .xdf path) is required"}
        try:
            xdf = self._load_xdf(ref)
            image = None
            if body.get("path") or body.get("use_base_map"):
                image, _, _ = self._map_source(body)
            report = xdf.validate_definition(
                image, address_base=self._address_base(body)
            )
            providers, provider_errors = load_checksum_providers()
            report["checksum"] = {
                "declared": list(xdf.checksums),
                "compatible_providers": [
                    provider.as_dict() for provider in providers
                    if provider.supports(xdf.checksums)
                ],
                "plugin_errors": provider_errors,
                "selection_required": bool(xdf.checksums),
            }
        except (XdfError, TuningError, OSError) as exc:
            return 400, {"error": str(exc)}
        return 200, report

    def post_maps_analyze_log(self, body: dict) -> tuple[int, dict]:
        """Overlay an offline log and propose bounded, non-writing fuel edits."""
        ref = body.get("xdf")
        table_ref = str(body.get("table") or "")
        if not ref or not table_ref:
            return 400, {"error": "'xdf' and 'table' are required"}
        try:
            image, _, _ = self._map_source(body)
            xdf = self._load_xdf(ref)
            render = xdf.render(image, address_base=self._address_base(body))
            tables = [table for table in render["tables"] if
                      table.get("id") == table_ref or table.get("title") == table_ref]
            if len(tables) != 1:
                raise LogAnalysisError(
                    f"no unique rendered table matches {table_ref!r}"
                )
            report = analyze_fuel_log(
                tables[0], body.get("rows"),
                x_channel=str(body.get("x_channel") or ""),
                y_channel=str(body.get("y_channel") or ""),
                measured_afr_channel=str(body.get("measured_afr_channel") or ""),
                target_afr_channel=str(body.get("target_afr_channel") or ""),
                min_samples=body.get("min_samples", 3),
                max_correction_percent=body.get("max_correction_percent", 10),
                max_afr_stddev=body.get("max_afr_stddev", 0.5),
                time_channel=str(body.get("time_channel") or ""),
                timestamp_unit=str(body.get("timestamp_unit") or "seconds"),
                wideband_delay_ms=body.get("wideband_delay_ms", 0),
                settle_time_ms=body.get("settle_time_ms", 500),
                max_time_gap_ms=body.get("max_time_gap_ms", 250),
                max_x_rate_per_s=body.get("max_x_rate_per_s"),
                max_y_rate_per_s=body.get("max_y_rate_per_s"),
            )
        except (XdfError, TuningError, LogAnalysisError, OSError) as exc:
            return 400, {"error": str(exc)}
        return 200, report

    def get_physical_validation(self, query: dict) -> tuple[int, dict]:
        records, errors = load_physical_validation()
        return 200, {
            "directory": str(PHYSICAL_VALIDATION_DIR),
            "records": records,
            "errors": errors,
            "physically_validated": False,
            "complete_evidence_records": sum(
                record.get("result") == "pass"
                and record.get("registry_status") == "evidence-index-locally-complete"
                for record in records
            ),
            "note": (
                "Operator-supplied manifests index evidence but do not create a "
                "GuzziOnBoard certification. This repository bundles no real-ECU "
                "or dyno validation record."
            ),
        }

    def post_physical_validation_validate(self, body: dict) -> tuple[int, dict]:
        try:
            record = validate_physical_manifest(body.get("manifest"))
        except (PhysicalValidationError, KeyError, TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}
        return 200, {"valid": True, "record": record}

    def get_recommendation_packages(self, query: dict) -> tuple[int, dict]:
        packages, errors = load_recommendation_packages()
        return 200, {
            "directory": str(RECOMMENDATION_PACKAGE_DIR),
            "packages": packages,
            "errors": errors,
            "bundled": 0,
            "note": (
                "Packages are user-supplied and unendorsed. No tune values ship "
                "with GuzziOnBoard; package claims still require fitment, source-lock, "
                "evidence, preview, and liability review."
            ),
        }

    def post_recommendation_validate(self, body: dict) -> tuple[int, dict]:
        try:
            package = validate_recommendation_package(body.get("package"))
        except (RecommendationPackageError, KeyError, TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}
        return 200, {"valid": True, "package": package}

    def get_checksum_providers(self, query: dict) -> tuple[int, dict]:
        providers, errors = load_checksum_providers()
        return 200, {
            "directory": str(CHECKSUM_PLUGIN_DIR),
            "providers": [provider.as_dict() for provider in providers],
            "errors": errors,
            "note": (
                "No calibration checksum algorithm is bundled or guessed. "
                "Plugins run in fresh resource-limited, audit-guarded subprocesses; "
                "they remain local code, and self-verification does not prove "
                "correctness on physical ECU hardware."
            ),
        }

    @staticmethod
    def _checksum_provider(body: dict):
        provider_id = str(body.get("checksum_provider") or "").strip()
        if not provider_id:
            return None
        try:
            return checksum_provider_by_id(provider_id)
        except ChecksumUnavailable as exc:
            raise TuningError(str(exc)) from exc

    @staticmethod
    def _package_change_identity(change: dict) -> tuple:
        if not isinstance(change, dict):
            raise TuningError("recommendation package change is not an object")
        kind = str(change.get("kind") or "").lower()
        item_id = str(change.get("id") or change.get("item_id") or "")
        if kind == "table":
            return kind, item_id, int(change.get("row")), int(change.get("col"))
        if kind == "axis":
            return kind, item_id, str(change.get("axis") or "").lower(), int(change.get("index"))
        if kind == "constant":
            return kind, item_id
        raise TuningError(f"recommendation package contains unknown change kind {kind!r}")

    def _recommendation_package(
        self, body: dict, xdf: XdfFile, source: FirmwareImage
    ) -> dict | None:
        """Resolve and lock a local recommendation package to this exact plan."""
        ref = body.get("recommendation_package")
        if ref in (None, ""):
            return None
        if not isinstance(ref, dict):
            raise TuningError("recommendation_package must identify a local package")
        package_id = str(ref.get("id") or "").strip()
        version = str(ref.get("version") or "").strip()
        digest = str(ref.get("package_sha256") or "").strip().lower()
        packages, errors = load_recommendation_packages()
        matches = [package for package in packages
                   if package["id"] == package_id and package["version"] == version]
        if len(matches) != 1:
            suffix = f" ({len(errors)} package file(s) failed validation)" if errors else ""
            raise TuningError(
                f"no unique local recommendation package {package_id!r} {version!r}{suffix}"
            )
        package = matches[0]
        if digest != package.get("package_sha256"):
            raise TuningError(
                "recommendation package SHA-256 changed; reload and review it again"
            )
        xdf_path = Path(xdf.path) if xdf.path else None
        if xdf_path is None or not xdf_path.is_file():
            raise TuningError("recommendation packages require a file-backed XDF")
        xdf_digest = hashlib.sha256(xdf_path.read_bytes()).hexdigest()
        if (xdf_path.name != package["xdf"]["filename"]
                or xdf_digest != package["xdf"]["sha256"]):
            raise TuningError(
                "recommendation package XDF filename/SHA-256 does not match "
                "the selected definition"
            )
        package_family = self._family_tokens(package["fitment"]["ecu_family"])
        xdf_family = self._family_tokens(str(fitment(xdf.path).get("family") or ""))
        if not package_family or not xdf_family or not (package_family & xdf_family):
            raise TuningError(
                "recommendation package ECU-family fitment does not match the XDF"
            )
        selection = (self.ws.status() or {}).get("selection") or {}
        selected_bike = re.sub(
            r"[^a-z0-9]", "",
            f"{selection.get('make', '')}{selection.get('model', '')}".lower(),
        )
        package_bike = re.sub(
            r"[^a-z0-9]", "", package["fitment"]["motorcycle"].lower()
        )
        if not selected_bike:
            raise TuningError(
                "recommendation package fitment requires a selected motorcycle"
            )
        if not (selected_bike in package_bike or package_bike in selected_bike):
            raise TuningError(
                "recommendation package motorcycle does not match the current selection"
            )
        hardware_values = [
            str(value) for key, value in (source.identity or {}).items()
            if "hardware" in str(key).lower() and str(value).strip()
        ]
        if not hardware_values and self.ws.service is not None:
            identity = getattr(self.ws.service, "identity", None)
            hardware_values = [
                str(value) for key, value in (getattr(identity, "fields", {}) or {}).items()
                if "hardware" in str(key).lower() and str(value).strip()
            ]
        package_hardware = re.sub(
            r"[^A-Z0-9]", "", package["fitment"]["hardware"].upper()
        )
        known_hardware = [
            re.sub(r"[^A-Z0-9]", "", value.upper()) for value in hardware_values
        ]
        if not package_hardware or not known_hardware:
            raise TuningError(
                "recommendation package fitment requires known source/ECU hardware identity"
            )
        if not any(
            package_hardware in known or known in package_hardware
            for known in known_hardware
        ):
            raise TuningError(
                "recommendation package hardware does not match the source/ECU identity"
            )

        requested = body.get("changes")
        if not isinstance(requested, list) or len(requested) != len(package["changes"]):
            raise TuningError(
                "recommendation package builds must contain exactly the package's changes"
            )
        try:
            incoming = {
                self._package_change_identity(change): change for change in requested
            }
        except (TypeError, ValueError) as exc:
            raise TuningError("recommendation package change coordinates are invalid") from exc
        if len(incoming) != len(requested):
            raise TuningError("recommendation package build contains duplicate changes")
        for expected in package["changes"]:
            identity = self._package_change_identity(expected)
            actual = incoming.get(identity)
            if actual is None:
                raise TuningError(
                    f"recommendation package change {identity!r} is missing"
                )
            try:
                raw_value = actual.get("expected_raw")
                actual_raw = int(raw_value)
                actual_value = float(actual.get("value"))
            except (TypeError, ValueError) as exc:
                raise TuningError(
                    f"recommendation package change {identity!r} is malformed"
                ) from exc
            if (isinstance(raw_value, bool) or actual_raw != float(raw_value)
                    or actual_raw != expected["expected_raw"]
                    or not math.isfinite(actual_value)
                    or not math.isclose(
                        actual_value, expected["value"], rel_tol=1e-12, abs_tol=1e-12
                    )):
                raise TuningError(
                    f"recommendation package change {identity!r} no longer "
                    "matches its source lock and target value"
                )
        evidence = body.get("recommendation") or {}
        if not any(
            str(evidence.get("title") or "").strip() == source["title"]
            and str(evidence.get("url") or "").strip() == source["url"]
            and str(evidence.get("rationale") or "").strip() == source["rationale"]
            for source in package["evidence"]
        ):
            raise TuningError(
                "recommendation evidence does not match a source in the selected package"
            )
        return {
            key: package[key] for key in (
                "id", "version", "title", "license", "maintainers", "fitment",
                "xdf", "evidence", "validation", "status", "package_sha256",
            )
        }

    def post_maps_preview(self, body: dict) -> tuple[int, dict]:
        """Quantize and diff staged edits without writing a file."""
        ref = body.get("xdf")
        if not ref:
            return 400, {"error": "an 'xdf' (filename or .xdf path) is required"}
        try:
            source, is_base, _ = self._map_source(body)
            xdf = self._load_xdf(ref)
            self._check_build_fitment(xdf, source)
            address_base = self._address_base(body)
            package = self._recommendation_package(body, xdf, source)
            tuned_data, plan = prepare_tune(
                source, xdf, body.get("changes"),
                source_is_base_map=is_base,
                address_base=address_base,
                checksum_provider=self._checksum_provider(body),
                recommendation_package=package,
            )
            diff = xdf.diff(source, tuned_data, address_base=address_base)
        except (XdfError, TuningError, OSError) as exc:
            return 400, {"error": str(exc)}
        return 200, {**plan, "diff": diff, "writes_file": False}

    def post_maps_build(self, body: dict) -> tuple[int, dict]:
        """Create a new, provenance-carrying image from explicit XDF edits."""
        ref = body.get("xdf")
        if not ref:
            return 400, {"error": "an 'xdf' (filename or .xdf path) is required"}
        try:
            source, is_base, _ = self._map_source(body)
            xdf = self._load_xdf(ref)
            self._check_build_fitment(xdf, source)
            package = self._recommendation_package(body, xdf, source)
            result = build_tune(
                source,
                xdf,
                body.get("changes"),
                recommendation=body.get("recommendation"),
                acknowledgement=str(body.get("acknowledgement") or ""),
                source_is_base_map=is_base,
                accept_non_base_source=bool(body.get("accept_non_base_source")),
                address_base=self._address_base(body),
                checksum_provider=self._checksum_provider(body),
                recommendation_package=package,
                expected_plan_sha256=str(body.get("expected_plan_sha256") or ""),
            )
            built = FirmwareImage.from_file(result["path"])
            result["diff"] = xdf.diff(
                source, built, address_base=self._address_base(body)
            )
        except (XdfError, TuningError, OSError) as exc:
            return 400, {"error": str(exc)}
        if self.ws.log is not None:
            self.ws.log.action("map_build", {
                "source_sha256": source.sha256,
                "output_sha256": result["image"]["checksums"]["sha256"],
                "output_path": result["path"],
                "xdf": Path(xdf.path).name,
                "changes": len(result["changes"]),
                "base_map_source": is_base,
                "recommendation": result["manifest"]["recommendation"],
                "recommendation_package": result["manifest"].get("recommendation_package"),
                "liability_acknowledged": True,
            })
        return 201, result

    def post_programming_enable(self, body: dict) -> tuple[int, dict]:
        self.ws.gate.enable_programming(body.get("acknowledgement", ""))
        if body.get("allow_unverified_keys"):
            self.ws.gate.accept_unverified_key_risk(True)
        return 200, {
            "programming_enabled": True,
            "unverified_keys_accepted": self.ws.gate.allow_unverified_keys,
        }

    def post_programming_disable(self, body: dict) -> tuple[int, dict]:
        self.ws.gate.disable_programming()
        return 200, {"programming_enabled": False}

    def get_security(self, query: dict) -> tuple[int, dict]:
        load_plugins()
        return 200, {
            "providers": describe_all(),
            "plugin_dir": str(__import__("guzzionboard.security",
                                         fromlist=["PLUGIN_DIR"]).PLUGIN_DIR),
            "unverified_keys_accepted": self.ws.gate.allow_unverified_keys,
        }

    def post_security_unverified(self, body: dict) -> tuple[int, dict]:
        """The operator's explicit, audited, session-scoped acceptance of key
        providers that are not bench-verified on Guzzi-fitted hardware. This
        is what unblocks 5AM flash reads/writes over HTTP: the refusal message
        from the provider registry points here."""
        accept = bool(body.get("accept"))
        self.ws.gate.accept_unverified_key_risk(accept)
        return 200, {
            "allow_unverified_keys": accept,
            "note": (
                "Session-scoped. The shipped key algorithm matches the "
                "published pairs from the reference tool it was transcribed "
                "from, but it is not bench-verified on a Guzzi-fitted ECU. "
                "Repeated wrong keys can lock the security gate."
            ),
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

    def post_tools_klinelog(self, body: dict) -> tuple[int, dict]:
        """Characterise a K-Line capture: which local identifiers answered?

        This is how the 5AM table was built, made repeatable. Give it a tap
        of a diagnostic session (``path`` or pasted ``text``); give it the
        CSV the other tool wrote at the same time (``reference`` /
        ``reference_path``) and the scalings are solved rather than guessed.
        Read-only: it touches files, never hardware.
        """
        path, text = body.get("path"), body.get("text")
        if not path and not text:
            return 400, {"error": "a capture 'path' or pasted 'text' is required"}
        family = str(body.get("family") or "unknown")
        try:
            if path:
                result = klinelog.analyze_file(
                    str(path), body.get("reference_path"), family=family)
            else:
                reference = body.get("reference")
                if not reference and body.get("reference_path"):
                    from pathlib import Path as _Path
                    ref_file = _Path(str(body["reference_path"]))
                    if not ref_file.is_file():
                        return 400, {"error": f"no such reference log: {ref_file}"}
                    reference = ref_file.read_text(encoding="utf-8", errors="replace")
                result = klinelog.analyze(
                    str(text), str(reference) if reference else None, family=family)
        except klinelog.KLineLogError as exc:
            return 400, {"error": str(exc)}
        return 200, result

    def post_tools_z2dif(self, body: dict) -> tuple[int, dict]:
        """Convert a Zeitronix ZT-2 (ZDL) CSV log to LogWorks DIF.

        What the mirrored ZT2CSVToLogWorksDIF tool does — with its documented
        factor-4 timeline error corrected by default (``timeline_factor=1.0``
        reproduces the reference tool's output). Accepts pasted ``text`` or
        a CSV ``path``; strict file-in/text-out, never hardware.
        """
        path, text = body.get("path"), body.get("text")
        if not path and not text:
            return 400, {"error": "a ZT-2 CSV 'path' or pasted 'text' is required"}
        try:
            rate = float(body.get("sample_rate", logconvert.DEFAULT_SAMPLE_RATE))
            factor = float(
                body.get("timeline_factor", logconvert.DEFAULT_TIMELINE_FACTOR)
            )
            if path:
                source = Path(str(path)).read_text(
                    encoding="utf-8", errors="replace"
                )
            else:
                source = str(text)
            result = logconvert.convert_z2csv_to_dif(
                source, sample_rate=rate, timeline_factor=factor
            )
        except (OSError, logconvert.LogConvertError, ValueError) as exc:
            return 400, {"error": str(exc)}
        return 200, result

    def post_tools_rpmsignal(self, body: dict) -> tuple[int, dict]:
        """Render a bench RPM trigger signal to a WAV file.

        What the mirrored RPMSensorEmu does with dedicated hardware, done
        with the sound card everyone has: a crank/cam trigger pattern
        (geometry presets transcribed from the reference tool's config
        files), constant RPM or reference-style batch ramps.
        """
        try:
            if body.get("pattern"):
                try:
                    wheel = rpmsignal.PRESETS[str(body["pattern"]).lower()]
                except KeyError:
                    return 400, {
                        "error": f"unknown pattern {body['pattern']!r}",
                        "presets": sorted(rpmsignal.PRESETS),
                    }
            else:
                wheel = rpmsignal.TriggerWheel(
                    int(body["teeth"]), int(body.get("missing", 0)),
                    str(body.get("wheel", "crankshaft")),
                )
                if wheel.wheel not in ("crankshaft", "camshaft"):
                    return 400, {"error": "'wheel' must be crankshaft or camshaft"}
            if body.get("events") is not None:
                events = body["events"]
            else:
                rpm = float(body.get("rpm", 0))
                seconds = float(body.get("seconds", 0))
                if rpm <= 0 or seconds <= 0:
                    return 400, {
                        "error": "pass 'rpm' + 'seconds', or 'events': "
                        "[[duration_ms, rpm (, rpm_end)], ...]"
                    }
                duration_ms = int(round(seconds * 10) * 100)  # 100 ms quanta
                events = [[duration_ms, rpm]]
            result = rpmsignal.generate(
                wheel,
                events,
                sample_rate=int(body.get("sample_rate", rpmsignal.DEFAULT_SAMPLE_RATE)),
                duty=float(body.get("duty", 0.5)),
                amplitude=float(body.get("amplitude", 0.7)),
                name=str(body.get("name", "")),
            )
        except (KeyError, TypeError) as exc:
            return 400, {
                "error": f"missing field {exc}; need a preset 'pattern' or "
                "'teeth' (+ 'missing', 'wheel')"
            }
        except (ValueError, rpmsignal.SignalError) as exc:
            return 400, {"error": str(exc)}
        return 200, result

    def get_gearing(self, query: dict) -> tuple[int, dict]:
        def number(name, default):
            try:
                return float((query.get(name) or [default])[0])
            except (TypeError, ValueError):
                return default

        def floats(name):
            out = []
            for part in str((query.get(name) or [""])[0]).replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    value = float(part)
                except ValueError:
                    continue
                if value > 0:
                    out.append(value)
            return out

        preset = (query.get("preset") or [""])[0]
        preset_data = tools.GEARING_PRESETS.get(preset, {})
        gears = floats("gears") or preset_data.get("gears")
        rpm_values = [int(v) for v in floats("rpm")] or None
        kwargs = {
            "final_drive": number("final_drive", 4.125),
            "tyre": (query.get("tyre") or ["180/55-17"])[0],
            "primary": number("primary", 1.0),
        }
        if gears:
            kwargs["gears"] = gears
        result = tools.Gearing(**kwargs).table(rpm_values)
        if preset and preset_data:
            result["preset"] = preset
            result["max_rpm"] = preset_data.get("max_rpm")
        # the per-model ratio sets read out of the reference app, so the
        # client can offer them without shipping its own copy
        result["presets"] = tools.GEARING_PRESETS
        result["gear_ratios_used"] = gears or tools.Gearing().gears
        return 200, result

    def get_export(self, query: dict) -> tuple[int, dict]:
        """A recorded session as CSV or JSON.

        The CSV is one row per polling sweep, with a units row and the raw
        bytes beside every value - a spreadsheet that still carries its own
        provenance.
        """
        name = (query.get("name") or [""])[0]
        fmt = (query.get("format") or ["csv"])[0]
        if fmt not in tools.EXPORTERS:
            return 400, {"error": f"unknown format {fmt!r}"}
        path = self._session_path(name)
        if path is None:
            return 404, {"error": "no such session"}
        events = list(SessionLog.read(path))
        content = tools.EXPORTERS[fmt](events)
        header_rows = 2 if fmt == "csv" else 1
        return 200, {
            "format": fmt,
            "name": name,
            "filename": f"{Path(name).stem}.{'json' if fmt == 'json' else 'csv'}",
            "rows": max(0, content.count("\n") - header_rows),
            "content": content,
            "csv": content if fmt != "json" else "",
            "note": (
                "One row per polling sweep. The second row carries the units, "
                "and the raw bytes travel with every value."
            ),
        }


ROUTES_GET = {
    "/api/catalog": "get_catalog",
    "/api/catalog/resolve": "get_resolve",
    "/api/status": "get_status",
    "/api/identify": "get_identify",
    "/api/live": "get_live",
    "/api/derived": "get_derived_catalog",
    "/api/sim": "get_sim",
    "/api/parameters": "get_parameters",
    "/api/dtcs": "get_dtcs",
    "/api/actuators": "get_actuators",
    "/api/routines": "get_routines",
    "/api/sessions": "get_sessions",
    "/api/sessions/events": "get_session_events",
    "/api/sessions/replay": "get_session_replay",
    "/api/procedures": "get_procedures",
    "/api/report": "get_report",
    "/api/maps": "get_maps",
    "/api/checksum-providers": "get_checksum_providers",
    "/api/recommendations": "get_recommendation_packages",
    "/api/physical-validation": "get_physical_validation",
    "/api/memory": "get_memory",
    "/api/memory/progress": "get_memory_progress",
    "/api/memory/basemap": "get_basemap",
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
    "/api/memory/basemap": "post_basemap_save",
    "/api/memory/basemap/restore": "post_basemap_restore",
    "/api/memory/read": "post_memory_read",
    "/api/memory/validate": "post_memory_validate",
    "/api/memory/write": "post_memory_write",
    "/api/memory/check-write": "post_memory_check_write",
    "/api/maps/render": "post_maps_render",
    "/api/maps/diff": "post_maps_diff",
    "/api/maps/validate-definition": "post_maps_validate_definition",
    "/api/maps/analyze-log": "post_maps_analyze_log",
    "/api/maps/preview": "post_maps_preview",
    "/api/maps/build": "post_maps_build",
    "/api/recommendations/validate": "post_recommendation_validate",
    "/api/physical-validation/validate": "post_physical_validation_validate",
    "/api/programming/enable": "post_programming_enable",
    "/api/programming/disable": "post_programming_disable",
    "/api/security/unverified": "post_security_unverified",
    "/api/adapter/latency": "post_adapter_latency",
    "/api/tools/canlog": "post_tools_canlog",
    "/api/tools/klinelog": "post_tools_klinelog",
    "/api/tools/z2dif": "post_tools_z2dif",
    "/api/tools/rpmsignal": "post_tools_rpmsignal",
    "/api/sessions/compare": "post_sessions_compare",
    "/api/sim/engine": "post_sim_engine",
    "/api/sim/faults": "post_sim_faults",
    "/api/sim/comms": "post_sim_comms",
    "/api/procedures/start": "post_procedure_start",
    "/api/procedures/advance": "post_procedure_advance",
    "/api/procedures/abort": "post_procedure_abort",
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
            except TokenError as exc:
                status, payload = 403, {"error": str(exc), "code": "token"}
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
            body = target.read_bytes()
            if target.name == "index.html":
                body = mark_live_backend(body)
            self._send(200, body, content_type)

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
