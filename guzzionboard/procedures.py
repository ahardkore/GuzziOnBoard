"""Guided test procedures.

An actuator pulse on its own is a twitch; a *procedure* is the thing a
workshop manual actually asks for - put the engine in a known state, do one
bounded thing, watch the right channels, and say what the result means.

Everything here is composed from capabilities that already exist and are
already gated:

* observations are ordinary live reads through :class:`DiagnosticsService`;
* actuator steps go through the safety gate and the workstation's own output
  deadline, exactly like a single pulse from the Service view;
* a verdict is an interpretation, reported in the same language as the
  plausibility checks - a place to start looking, never a diagnosis.

A procedure is only offered when the catalog says this ECU family has the
channels and actuators it needs. No procedure invents a local identifier.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Callable

from .catalog import EcuProfile


class ProcedureError(RuntimeError):
    pass


# --------------------------------------------------------------- the model

@dataclass(frozen=True)
class Step:
    """One thing the operator or the workstation does."""

    key: str
    kind: str                       # instruct | input | observe | actuate | verdict
    title: str
    text: str = ""
    #: observe
    channels: tuple[str, ...] = ()
    seconds: float = 5.0
    #: actuate
    actuator: str = ""
    pulse_s: float = 2.0
    #: input
    input_kind: str = "number"      # number | yesno
    input_label: str = ""
    input_unit: str = ""
    #: verdict
    evaluate: Callable[["Context"], dict] | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key, "kind": self.kind, "title": self.title,
            "text": self.text, "channels": list(self.channels),
            "seconds": self.seconds, "actuator": self.actuator,
            "pulse_s": self.pulse_s, "input_kind": self.input_kind,
            "input_label": self.input_label, "input_unit": self.input_unit,
        }


@dataclass(frozen=True)
class Procedure:
    key: str
    name: str
    purpose: str
    engine: str                     # "off" | "running" | "any"
    steps: tuple[Step, ...]
    caveat: str = ""

    @property
    def channels(self) -> set[str]:
        out: set[str] = set()
        for step in self.steps:
            out.update(step.channels)
        return out

    @property
    def actuators(self) -> set[str]:
        return {s.actuator for s in self.steps if s.actuator}

    def missing_for(self, profile: EcuProfile | None) -> list[str]:
        """What this ECU family would need before the procedure can run."""
        if profile is None:
            return ["no ECU selected"]
        known_channels = {p.key for p in profile.parameters}
        known_actuators = {a.key for a in profile.actuators}
        missing = [f"channel {k}" for k in sorted(self.channels - known_channels)]
        missing += [f"actuator {k}" for k in sorted(self.actuators - known_actuators)]
        return missing

    def as_dict(self, profile: EcuProfile | None = None) -> dict:
        missing = self.missing_for(profile)
        return {
            "key": self.key, "name": self.name, "purpose": self.purpose,
            "engine": self.engine, "caveat": self.caveat,
            "steps": [s.as_dict() for s in self.steps],
            "available": not missing,
            "missing": missing,
        }


@dataclass
class Context:
    """What the running procedure has gathered so far."""

    observations: dict = field(default_factory=dict)   # step -> key -> stats
    inputs: dict = field(default_factory=dict)         # step -> value

    def stat(self, step: str, channel: str, which: str = "mean") -> float | None:
        entry = self.observations.get(step, {}).get(channel)
        if entry is None:
            return None
        value = entry.get(which)
        return float(value) if isinstance(value, (int, float)) else None

    def value(self, step: str):
        return self.inputs.get(step)


def verdict(level: str, title: str, detail: str, suspects=()) -> dict:
    return {
        "level": level, "title": title, "detail": detail,
        "suspects": list(suspects),
    }


# ----------------------------------------------------------- the verdicts

def _idle_verdict(ctx: Context) -> dict:
    rpm = ctx.stat("watch", "rpm")
    target = ctx.stat("watch", "idle_target")
    spread = (ctx.stat("watch", "rpm", "max") or 0) - (ctx.stat("watch", "rpm", "min") or 0)
    position = ctx.stat("watch", "stepper_position")
    base = ctx.stat("watch", "stepper_base")
    if rpm is None or target is None:
        return verdict("info", "Not enough data",
                       "The idle channels did not answer for long enough to judge.")

    error = rpm - target
    drift = None if position is None or base is None else position - base
    bits = [f"{rpm:.0f} rpm against a target of {target:.0f}",
            f"wandering {spread:.0f} rpm"]
    if drift is not None:
        bits.append(f"stepper {drift:+.0f} steps from base")

    if abs(error) < 120 and spread < 180:
        return verdict("ok", "Idle is in control",
                       "Measured " + ", ".join(bits)
                       + ". The ECU is asking for a speed and getting it.")
    if error > 0 and drift is not None and drift < -5:
        return verdict(
            "warn", "Idle high with the stepper closing down",
            "Measured " + ", ".join(bits)
            + ". The controller is shutting its air passage and still cannot "
            "bring the speed down, which is what unmetered air looks like.",
            ["Air leak after the throttle", "Throttle stop adjustment",
             "Throttle plate not closing"],
        )
    if abs(error) >= 120:
        return verdict(
            "warn", "Idle is off target",
            "Measured " + ", ".join(bits) + ".",
            ["Idle stepper", "Throttle body balance", "Air leak"],
        )
    return verdict(
        "warn", "Idle is hunting",
        "Measured " + ", ".join(bits)
        + ". The average is fine but it will not sit still.",
        ["Idle stepper", "Lambda control at idle", "Air leak"],
    )


def _charging_verdict(ctx: Context) -> dict:
    rest = ctx.stat("rest", "battery")
    idle = ctx.stat("idle", "battery")
    revs = ctx.stat("revs", "battery")
    if rest is None or idle is None:
        return verdict("info", "Not enough data",
                       "The battery channel did not answer in both states.")

    bits = [f"{rest:.1f} V stopped", f"{idle:.1f} V at idle"]
    if revs is not None:
        bits.append(f"{revs:.1f} V held up")
    measured = ", ".join(bits)

    best = max(v for v in (idle, revs) if v is not None)
    if rest < 12.0:
        return verdict(
            "warn", "The battery was flat before we started",
            f"Measured {measured}. Charge it and repeat: every other reading "
            "on this bike is suspect at this voltage.",
            ["Battery", "Parasitic drain"],
        )
    if best < 13.0:
        return verdict(
            "bad", "Not charging",
            f"Measured {measured}. The alternator is not contributing.",
            ["Alternator or stator", "Regulator/rectifier", "Charging wiring"],
        )
    if best > 15.2:
        return verdict(
            "bad", "Charging too hard",
            f"Measured {measured}. This will boil the battery.",
            ["Regulator/rectifier", "Earth connections"],
        )
    if revs is not None and revs - idle < 0.1 and idle < 13.5:
        return verdict(
            "warn", "Charging does not improve with revs",
            f"Measured {measured}. A healthy system climbs as the rpm comes up.",
            ["Stator windings", "Regulator/rectifier"],
        )
    return verdict("ok", "Charging system is doing its job",
                   f"Measured {measured}.")


def _pump_verdict(ctx: Context) -> dict:
    primed = ctx.value("pressure_primed")
    rested = ctx.value("pressure_rested")
    if primed is None or rested is None:
        return verdict("info", "No readings entered",
                       "Both gauge readings are needed to judge the decay.")
    drop = float(primed) - float(rested)
    measured = f"{primed} bar after priming, {rested} bar sixty seconds later"
    if primed < 2.5:
        return verdict(
            "bad", "Pressure never came up",
            f"{measured}. A 5AM-era Guzzi wants roughly 3 bar at the rail.",
            ["Fuel pump", "Blocked filter", "Pressure regulator", "Weak battery"],
        )
    if drop > 0.5:
        return verdict(
            "warn", "Pressure bleeds away",
            f"{measured} - a {drop:.1f} bar drop. The rail should hold "
            "pressure for minutes, not seconds; this is why it is hard to "
            "start after standing.",
            ["Leaking injector", "Pump non-return valve", "Pressure regulator"],
        )
    return verdict("ok", "Rail holds pressure",
                   f"{measured}. Both the delivery and the seal are good.")


def _injector_verdict(ctx: Context) -> dict:
    front = ctx.value("heard_front")
    rear = ctx.value("heard_rear")
    silent = [name for name, heard in (("front", front), ("rear", rear))
              if heard is False]
    if not silent:
        return verdict("ok", "Both injectors answered",
                       "Each one clicked when it was commanded, so the ECU "
                       "driver, the wiring and the solenoid are all alive.")
    return verdict(
        "bad", f"No click from the {' and '.join(silent)} injector",
        "The ECU commanded it and nothing moved. This is an electrical "
        "result only - a clicking injector can still be blocked.",
        ["Injector connector", "Injector solenoid", "ECU driver stage",
         "Wiring to the injector"],
    )


def _cold_sensor_verdict(ctx: Context) -> dict:
    coolant = ctx.stat("soak", "coolant_temp")
    air = ctx.stat("soak", "air_temp")
    if coolant is None or air is None:
        return verdict("info", "Not enough data",
                       "Both temperature channels are needed.")
    split = coolant - air
    measured = f"head {coolant:.0f} \u00b0C, intake air {air:.0f} \u00b0C"
    if coolant <= -30 or coolant >= 130:
        return verdict(
            "bad", "The head sensor is on a rail",
            f"{measured}. That is an open or shorted circuit, not a temperature.",
            ["Head temperature sensor", "Sensor wiring or connector"],
        )
    if abs(split) > 8:
        return verdict(
            "warn", "The two sensors disagree on a cold engine",
            f"{measured}, a {split:+.0f} \u00b0C split. On a bike that has "
            "stood overnight they should be within a few degrees.",
            ["Head temperature sensor", "Air temperature sensor",
             "Catalog scaling for this family"],
        )
    return verdict("ok", "Both sensors agree",
                   f"{measured}. The ECU is starting from a believable picture.")


# --------------------------------------------------------- the procedures

PROCEDURES: tuple[Procedure, ...] = (
    Procedure(
        "idle_health", "Idle health check",
        "Watch the idle controller work for a few seconds and say whether it "
        "is in control. Read-only: nothing is commanded.",
        "running",
        (
            Step("warm", "instruct", "Warm the engine up",
                 "Run the engine until the head is above 70 \u00b0C and let it "
                 "settle at idle. Hands off the throttle for the next step."),
            Step("watch", "observe", "Watch the idle channels",
                 "Sampling engine speed, the ECU's idle target and the stepper.",
                 channels=("rpm", "idle_target", "stepper_position",
                           "stepper_base", "lambda_int_f", "lambda_int_r"),
                 seconds=6.0),
            Step("result", "verdict", "Result", evaluate=_idle_verdict),
        ),
    ),
    Procedure(
        "charging_system", "Charging system check",
        "Three voltage readings - stopped, idling and held up - which is all "
        "it takes to separate a flat battery from a dead alternator.",
        "any",
        (
            Step("stop", "instruct", "Stop the engine, ignition on",
                 "Leave the ignition on so the ECU keeps answering."),
            Step("rest", "observe", "Measure the resting voltage",
                 channels=("battery",), seconds=4.0),
            Step("start", "instruct", "Start the engine",
                 "Let it settle at idle before continuing."),
            Step("idle", "observe", "Measure at idle",
                 channels=("battery", "rpm"), seconds=4.0),
            Step("hold", "instruct", "Hold about 3000 rpm",
                 "Keep it steady while the next step samples."),
            Step("revs", "observe", "Measure with the revs up",
                 channels=("battery", "rpm"), seconds=4.0),
            Step("result", "verdict", "Result", evaluate=_charging_verdict),
        ),
    ),
    Procedure(
        "fuel_pressure", "Fuel pump prime and pressure decay",
        "Prime the rail, read the gauge, wait a minute and read it again. "
        "Delivery and sealing in one test.",
        "off",
        (
            Step("gauge", "instruct", "Fit a pressure gauge to the rail",
                 "Engine stopped, ignition on. Fuel is about to be "
                 "pressurised: no leaks, no ignition sources, catch tray down."),
            Step("state", "observe", "Confirm the engine really is stopped",
                 "The safety gate will not energise an output on an assumption, "
                 "so the engine state is read from the ECU first.",
                 channels=("rpm", "stop_state"), seconds=2.0),
            Step("prime", "actuate", "Prime the pump",
                 "The workstation owns the deadline and releases the output "
                 "when it expires.",
                 actuator="fuel_pump", pulse_s=3.0),
            Step("pressure_primed", "input", "Read the gauge now",
                 "Take the reading as soon as the pump stops.",
                 input_label="Pressure after priming", input_unit="bar"),
            Step("wait", "instruct", "Wait sixty seconds",
                 "Do not touch anything. The rail should hold its pressure."),
            Step("pressure_rested", "input", "Read the gauge again",
                 input_label="Pressure after sixty seconds", input_unit="bar"),
            Step("result", "verdict", "Result", evaluate=_pump_verdict),
        ),
        caveat="Pressurised fuel. Do not run this with a hot exhaust nearby.",
    ),
    Procedure(
        "injector_click", "Injector circuit test",
        "Command each injector briefly with the engine stopped and confirm it "
        "answers. An electrical test, not a flow test.",
        "off",
        (
            Step("prepare", "instruct", "Engine stopped, ignition on",
                 "Put your ear or a screwdriver against each injector body. "
                 "Fuel pressure may be present, so expect a small squirt if a "
                 "line is open."),
            Step("state", "observe", "Confirm the engine really is stopped",
                 "Read the engine state rather than assuming it.",
                 channels=("rpm", "stop_state"), seconds=2.0),
            Step("pulse_front", "actuate", "Pulse the front injector",
                 actuator="injector_front", pulse_s=0.5),
            Step("heard_front", "input", "Did the front injector click?",
                 input_kind="yesno", input_label="Front injector clicked"),
            Step("pulse_rear", "actuate", "Pulse the rear injector",
                 actuator="injector_rear", pulse_s=0.5),
            Step("heard_rear", "input", "Did the rear injector click?",
                 input_kind="yesno", input_label="Rear injector clicked"),
            Step("result", "verdict", "Result", evaluate=_injector_verdict),
        ),
        caveat="Commands real injectors. Engine stopped, and mind the fuel.",
    ),
    Procedure(
        "cold_sensor_check", "Cold-start sensor plausibility",
        "On a bike that has stood overnight, the head and the intake air must "
        "read nearly the same. This is the cheapest sensor test there is.",
        "off",
        (
            Step("soak_note", "instruct", "Confirm the engine is cold",
                 "The bike must have stood long enough to reach ambient - "
                 "overnight is ideal. A warm engine makes this test meaningless."),
            Step("soak", "observe", "Read both temperature channels",
                 channels=("coolant_temp", "air_temp"), seconds=4.0),
            Step("result", "verdict", "Result", evaluate=_cold_sensor_verdict),
        ),
    ),
)

PROCEDURES_BY_KEY = {p.key: p for p in PROCEDURES}


# ------------------------------------------------------------- the runner

class ProcedureRun:
    """One procedure being worked through, one step at a time."""

    def __init__(self, procedure: Procedure, service, sample_interval: float = 0.4):
        self.procedure = procedure
        self.service = service
        self.sample_interval = sample_interval
        self.context = Context()
        self.index = 0
        self.status = "running"          # running | done | aborted | blocked
        self.results: list[dict] = []
        self.verdict: dict | None = None
        self.started_at = time.time()

    # -- state -----------------------------------------------------------
    @property
    def current(self) -> Step | None:
        if self.index >= len(self.procedure.steps):
            return None
        return self.procedure.steps[self.index]

    def as_dict(self) -> dict:
        step = self.current
        return {
            "procedure": self.procedure.key,
            "name": self.procedure.name,
            "caveat": self.procedure.caveat,
            "status": self.status,
            "step_index": self.index,
            "step_count": len(self.procedure.steps),
            "step": step.as_dict() if step else None,
            "results": self.results,
            "verdict": self.verdict,
            "note": (
                "Observations are ordinary live reads; any output is commanded "
                "through the safety gate with the workstation's own deadline. "
                "The verdict is an interpretation, not a measurement."
            ),
        }

    # -- running ---------------------------------------------------------
    def abort(self) -> dict:
        self.status = "aborted"
        try:
            self.service.release_all_outputs()
        except Exception:                                   # pragma: no cover
            pass
        self.results.append({"step": "abort", "kind": "abort",
                             "detail": "Stopped by the operator; outputs released."})
        return self.as_dict()

    def advance(self, value=None) -> dict:
        """Execute the current step and move to the next one."""
        if self.status != "running":
            raise ProcedureError(f"this run is {self.status}")
        step = self.current
        if step is None:
            self.status = "done"
            return self.as_dict()

        handler = {
            "instruct": self._do_instruct,
            "input": self._do_input,
            "observe": self._do_observe,
            "actuate": self._do_actuate,
            "verdict": self._do_verdict,
        }[step.kind]
        result = handler(step, value)
        self.results.append(result)

        if result.get("blocked"):
            self.status = "blocked"
            return self.as_dict()

        self.index += 1
        if self.current is None:
            self.status = "done"
        return self.as_dict()

    # -- step kinds -------------------------------------------------------
    def _do_instruct(self, step: Step, value) -> dict:
        return {"step": step.key, "kind": "instruct", "title": step.title,
                "detail": "Confirmed by the operator."}

    def _do_input(self, step: Step, value) -> dict:
        if step.input_kind == "yesno":
            if value is None:
                raise ProcedureError(f"{step.key}: answer the question first")
            parsed = bool(value)
            shown = "yes" if parsed else "no"
        else:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                raise ProcedureError(f"{step.key}: a number is needed")
            shown = f"{parsed} {step.input_unit}".strip()
        self.context.inputs[step.key] = parsed
        return {"step": step.key, "kind": "input", "title": step.title,
                "detail": f"Operator entered {shown}.", "value": parsed}

    def _do_observe(self, step: Step, value) -> dict:
        channels = [k for k in step.channels]
        deadline = time.monotonic() + max(0.5, step.seconds)
        collected: dict[str, list[float]] = {k: [] for k in channels}
        errors: dict[str, str] = {}
        sweeps = 0
        while time.monotonic() < deadline:
            for sample in self.service.read_parameters(channels):
                if sample.error:
                    errors[sample.key] = sample.error
                elif isinstance(sample.value, (int, float)):
                    collected[sample.key].append(float(sample.value))
            sweeps += 1
            time.sleep(self.sample_interval)

        stats = {}
        for key, values in collected.items():
            if not values:
                continue
            stats[key] = {
                "mean": round(statistics.fmean(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "count": len(values),
            }
        self.context.observations[step.key] = stats
        detail = ", ".join(
            f"{k} {v['mean']} ({v['min']}…{v['max']})" for k, v in stats.items()
        ) or "nothing answered"
        return {"step": step.key, "kind": "observe", "title": step.title,
                "detail": f"{sweeps} sweeps: {detail}", "stats": stats,
                "errors": errors}

    def _do_actuate(self, step: Step, value) -> dict:
        decision = self.service.check_actuator(step.actuator)
        if not decision.allowed:
            return {
                "step": step.key, "kind": "actuate", "title": step.title,
                "blocked": True,
                "detail": f"Refused by the safety gate: {decision.reason()}",
                "decision": decision.as_dict(),
            }
        outcome = self.service.pulse_actuator(
            step.actuator, decision.token, step.pulse_s
        )
        return {"step": step.key, "kind": "actuate", "title": step.title,
                "detail": f"{step.actuator} energised for "
                          f"{outcome['duration_s']:.1f} s, then released by the "
                          "workstation's deadline.",
                "decision": decision.as_dict()}

    def _do_verdict(self, step: Step, value) -> dict:
        assert step.evaluate is not None
        self.verdict = step.evaluate(self.context)
        return {"step": step.key, "kind": "verdict", "title": step.title,
                "detail": self.verdict["detail"], "verdict": self.verdict}


def available(profile: EcuProfile | None) -> list[dict]:
    return [p.as_dict(profile) for p in PROCEDURES]
