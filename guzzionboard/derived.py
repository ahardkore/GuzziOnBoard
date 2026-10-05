"""Derived channels and plausibility checks.

Nothing in here talks to an ECU. It takes the samples the diagnostics service
already read - values that came from real bytes, with a catalogued scaling -
and does arithmetic on them.

That distinction is the whole point of keeping this in its own module:

* a **sample** is something the ECU said;
* a **derived channel** is something *we* worked out, and it is labelled as
  such everywhere it is shown, carrying the keys it was computed from;
* a **finding** is an opinion - "this looks wrong, here is what it usually
  means" - and it never claims to be a measurement.

A derived channel inherits the *worst* confidence of its inputs, because a
number computed from an inferred scaling is an inferred number no matter how
clean the arithmetic looks.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .catalog import EcuProfile, confidence_rank

#: How much history the windowed channels (swing, warm-up rate, closed-loop
#: share) look back over. Long enough to see a lambda sensor switch a few
#: times, short enough to react while somebody is holding a throttle open.
WINDOW_S = 60.0


# --------------------------------------------------------------- the view

class Readings:
    """The values available to a rule: now, and over the recent window."""

    def __init__(self, now: dict, history: deque, profile: EcuProfile | None):
        self._now = now
        self._history = history
        self.profile = profile
        self._texts: dict = {}

    def has(self, *keys: str) -> bool:
        return all(isinstance(self._now.get(k), (int, float)) for k in keys)

    def v(self, key: str, default: float | None = None) -> float | None:
        value = self._now.get(key)
        return float(value) if isinstance(value, (int, float)) else default

    def text(self, key: str) -> str:
        entry = self._texts.get(key, "")
        return entry

    def series(self, key: str) -> list[tuple[float, float]]:
        """``[(t, value)]`` for one key over the window, oldest first."""
        out = []
        for t, values in self._history:
            value = values.get(key)
            if isinstance(value, (int, float)):
                out.append((t, float(value)))
        return out

    def span(self, key: str) -> float | None:
        """Peak-to-peak of a channel over the window."""
        values = [v for _, v in self.series(key)]
        if len(values) < 3:
            return None
        return max(values) - min(values)

    def rate_per_min(self, key: str) -> float | None:
        """Slope of a channel in units/minute, from the window endpoints."""
        points = self.series(key)
        if len(points) < 3:
            return None
        (t0, v0), (t1, v1) = points[0], points[-1]
        if t1 - t0 < 5.0:
            return None
        return (v1 - v0) / (t1 - t0) * 60.0


# ---------------------------------------------------------- the channels

@dataclass(frozen=True)
class DerivedChannel:
    key: str
    name: str
    unit: str
    sources: tuple[str, ...]
    compute: Callable[[Readings], float | None]
    digits: int = 1
    group: str = "derived"
    #: True when the number is a *difference* of two temperatures, so a
    #: display converting to Fahrenheit must scale it without the offset.
    delta: bool = False
    note: str = ""


def _inj_duty(r: Readings) -> float | None:
    """Injector duty cycle.

    A four-stroke injects once every two crank revolutions, so the available
    window is ``120 / rpm`` seconds. Anything approaching 100% means the
    injector is open essentially all the time and cannot add more fuel.
    """
    if not r.has("injection_ms", "rpm") or r.v("rpm") < 200:
        return None
    return r.v("injection_ms") * r.v("rpm") / 1200.0


def _idle_error(r: Readings) -> float | None:
    if not r.has("rpm", "idle_target") or r.v("rpm") < 200:
        return None
    return r.v("rpm") - r.v("idle_target")


def _stepper_drift(r: Readings) -> float | None:
    if not r.has("stepper_position", "stepper_base"):
        return None
    return r.v("stepper_position") - r.v("stepper_base")


def _temp_split(r: Readings) -> float | None:
    if not r.has("coolant_temp", "air_temp"):
        return None
    return r.v("coolant_temp") - r.v("air_temp")


def _warmup_rate(r: Readings) -> float | None:
    return r.rate_per_min("coolant_temp")


def _bank_balance(r: Readings) -> float | None:
    if not r.has("lambda_int_f", "lambda_int_r"):
        return None
    return r.v("lambda_int_f") - r.v("lambda_int_r")


def _lambda_swing(bank: str) -> Callable[[Readings], float | None]:
    def compute(r: Readings) -> float | None:
        return r.span(f"lambda_{bank}")
    return compute


def _closed_loop_share(r: Readings) -> float | None:
    points = r.series("lambda_loop")
    if len(points) < 3:
        return None
    closed = sum(1 for _, v in points if v >= 2)
    return closed / len(points) * 100.0


def _advance_split(r: Readings) -> float | None:
    if not r.has("advance", "advance_latched"):
        return None
    return r.v("advance") - r.v("advance_latched")


def _charge_margin(r: Readings) -> float | None:
    """Battery volts above the 12.8 V a healthy resting battery holds."""
    if not r.has("battery"):
        return None
    return r.v("battery") - 12.8


CHANNELS: tuple[DerivedChannel, ...] = (
    DerivedChannel(
        "inj_duty", "Injector duty cycle", "%", ("injection_ms", "rpm"),
        _inj_duty, digits=1, group="fuelling",
        note="Injection time as a fraction of the 120/rpm window a four-stroke gives it.",
    ),
    DerivedChannel(
        "idle_error", "Idle error", "rpm", ("rpm", "idle_target"),
        _idle_error, digits=0, group="idle",
        note="Measured speed minus the target the ECU is aiming at.",
    ),
    DerivedChannel(
        "stepper_drift", "Idle stepper drift", "steps",
        ("stepper_position", "stepper_base"), _stepper_drift, digits=0, group="idle",
        note="How far the stepper has moved from its base position to hold idle. "
             "A large positive drift is the ECU compensating for an air leak.",
    ),
    DerivedChannel(
        "temp_split", "Coolant - air split", "\u00b0C", ("coolant_temp", "air_temp"),
        _temp_split, digits=1, group="engine", delta=True,
        note="On a cold bike both sensors should read within a few degrees of "
             "each other. If they do not, one of them is lying.",
    ),
    DerivedChannel(
        "warmup_rate", "Warm-up rate", "\u00b0C/min", ("coolant_temp",),
        _warmup_rate, digits=1, group="engine", delta=True,
        note="Slope of the head temperature over the last minute.",
    ),
    DerivedChannel(
        "bank_balance", "Bank trim split", "%", ("lambda_int_f", "lambda_int_r"),
        _bank_balance, digits=1, group="lambda",
        note="Front integrator minus rear. Two cylinders fed by one map should "
             "need similar correction.",
    ),
    DerivedChannel(
        "lambda_swing_f", "Lambda swing front", "mV", ("lambda_f",),
        _lambda_swing("f"), digits=0, group="lambda",
        note="Peak-to-peak over the last minute. A healthy switching sensor "
             "sweeps most of its range; a lazy one goes quiet.",
    ),
    DerivedChannel(
        "lambda_swing_r", "Lambda swing rear", "mV", ("lambda_r",),
        _lambda_swing("r"), digits=0, group="lambda",
        note="Peak-to-peak over the last minute.",
    ),
    DerivedChannel(
        "closed_loop_share", "Closed-loop share", "%", ("lambda_loop",),
        _closed_loop_share, digits=0, group="lambda",
        note="Fraction of the last minute the ECU trusted the lambda sensors.",
    ),
    DerivedChannel(
        "advance_split", "Advance vs latched", "\u00b0",
        ("advance", "advance_latched"), _advance_split, digits=1, group="ignition",
        note="Live advance minus the latched value. They track each other at "
             "steady state.",
    ),
    DerivedChannel(
        "charge_margin", "Charging margin", "V", ("battery",),
        _charge_margin, digits=2, group="electrical",
        note="Volts above a healthy resting battery (12.8 V). Running, the "
             "alternator should be holding this well above +0.5 V.",
    ),
)

CHANNELS_BY_KEY = {c.key: c for c in CHANNELS}


# ------------------------------------------------------------- the rules

@dataclass
class Finding:
    key: str
    level: str            # "ok" | "info" | "warn" | "bad"
    title: str
    detail: str
    suspects: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "level": self.level, "title": self.title,
            "detail": self.detail, "suspects": list(self.suspects),
            "evidence": dict(self.evidence),
        }


Rule = Callable[[Readings, dict], Finding | None]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _running(r: Readings) -> bool | None:
    """Engine state, preferring what the ECU said over what we inferred."""
    text = r.text("stop_state")
    if text:
        return text == "Running"
    if r.has("rpm"):
        return r.v("rpm") > 200
    return None


@rule
def _coolant_sensor_range(r: Readings, d: dict) -> Finding | None:
    c = r.v("coolant_temp")
    if c is None:
        return None
    if c <= -30 or c >= 130:
        return Finding(
            "coolant_sensor_range", "bad",
            "Head temperature is outside anything physical",
            f"{c:.0f} \u00b0C is the rail, not a temperature. An open circuit "
            "reads one end of the scale and a short reads the other, and the "
            "ECU will be fuelling to that number.",
            ["Head temperature sensor", "Sensor wiring or connector"],
            {"coolant_temp": f"{c:.1f} \u00b0C"},
        )
    return None


@rule
def _sensor_disagreement(r: Readings, d: dict) -> Finding | None:
    split = d.get("temp_split")
    if split is None or _running(r) is not False:
        return None
    # Engine stopped: unless it was just shut down hot, the two sensors should
    # be close. A large negative split (head colder than the airbox) is not a
    # thing that happens to a real motorcycle.
    if split < -8:
        return Finding(
            "sensor_disagreement", "warn",
            "Head reads colder than the intake air",
            f"A {abs(split):.0f} \u00b0C split the wrong way on a stopped "
            "engine means one of the two sensors, or its scaling, is wrong.",
            ["Head temperature sensor", "Air temperature sensor",
             "Catalog scaling for this family"],
            {"temp_split": f"{split:.1f} \u00b0C"},
        )
    return None


@rule
def _battery_health(r: Readings, d: dict) -> Finding | None:
    v = r.v("battery")
    if v is None:
        return None
    running = _running(r)
    if running and v < 13.0:
        return Finding(
            "charging", "bad",
            "Not charging",
            f"{v:.1f} V with the engine running. A healthy charging system "
            "holds 13.5-14.5 V; below 13 V the bike is running off the "
            "battery and will eventually stop.",
            ["Alternator or stator", "Regulator/rectifier", "Charging wiring"],
            {"battery": f"{v:.1f} V"},
        )
    if running and v > 15.2:
        return Finding(
            "overcharge", "bad",
            "Charging voltage too high",
            f"{v:.1f} V will cook the battery and can take electronics with it.",
            ["Regulator/rectifier", "Earth connections"],
            {"battery": f"{v:.1f} V"},
        )
    if running is False and v < 12.0:
        return Finding(
            "battery_low", "warn",
            "Resting battery is low",
            f"{v:.1f} V with the engine stopped. Below about 12.0 V the "
            "battery is flat enough to confuse every other reading here, and "
            "actuator tests will brown out the ECU.",
            ["Battery", "Parasitic drain"],
            {"battery": f"{v:.1f} V"},
        )
    return None


@rule
def _idle_control(r: Readings, d: dict) -> Finding | None:
    error = d.get("idle_error")
    if error is None or not _running(r):
        return None
    if r.text("throttle_closed") not in ("", "Shut"):
        return None            # rider is on the throttle; the target is moot
    if abs(error) < 200:
        return None
    drift = d.get("stepper_drift")
    suspects = ["Idle stepper", "Throttle body balance", "Air leak"]
    if error > 0 and (drift is None or drift > 0):
        suspects = ["Air leak after the throttle", "Throttle stop adjustment",
                    "Idle stepper stuck open"]
    return Finding(
        "idle_control", "warn",
        "Idle is not sitting on its target",
        f"{error:+.0f} rpm away from the ECU's target"
        + (f", with the stepper {drift:+.0f} steps off its base" if drift is not None else "")
        + ". The ECU is asking for one speed and getting another.",
        suspects,
        {"idle_error": f"{error:+.0f} rpm"}
        | ({"stepper_drift": f"{drift:+.0f} steps"} if drift is not None else {}),
    )


@rule
def _injector_duty(r: Readings, d: dict) -> Finding | None:
    duty = d.get("inj_duty")
    if duty is None:
        return None
    if duty > 85:
        return Finding(
            "inj_duty", "bad",
            "Injectors are nearly flat out",
            f"{duty:.0f}% duty leaves no headroom: the injector is open "
            "almost continuously and cannot deliver more fuel.",
            ["Fuel pressure", "Blocked injectors", "Undersized injectors for "
             "a modified engine", "Lean-biased map"],
            {"inj_duty": f"{duty:.0f} %"},
        )
    return None


@rule
def _lambda_dead(r: Readings, d: dict) -> Finding | None:
    if not _running(r):
        return None
    share = d.get("closed_loop_share")
    if share is None or share < 50:
        return None            # open loop: a quiet sensor is expected
    for bank, label in (("f", "front"), ("r", "rear")):
        swing = d.get(f"lambda_swing_{bank}")
        if swing is not None and swing < 100:
            return Finding(
                f"lambda_lazy_{bank}", "warn",
                f"Lambda sensor ({label}) is barely moving",
                f"{swing:.0f} mV of swing over the last minute while the ECU "
                "says it is in closed loop. A working narrowband sensor "
                "sweeps several hundred millivolts as the mixture crosses "
                "stoichiometric.",
                [f"Lambda sensor, {label} bank", "Sensor heater", "Exhaust leak "
                 "upstream of the sensor"],
                {f"lambda_swing_{bank}": f"{swing:.0f} mV"},
            )
    return None


@rule
def _bank_split(r: Readings, d: dict) -> Finding | None:
    split = d.get("bank_balance")
    if split is None or not _running(r):
        return None
    if abs(split) < 10:
        return None
    lean = "front" if split > 0 else "rear"
    return Finding(
        "bank_split", "warn",
        f"The {lean} cylinder needs much more correction",
        f"{abs(split):.1f} percentage points between the two integrators. "
        "Both cylinders run off one map, so a persistent split is a mechanical "
        "or air-path difference, not a mapping one.",
        [f"Air leak on the {lean} cylinder", f"Injector, {lean} cylinder",
         "Throttle body balance", "Valve clearances"],
        {"bank_balance": f"{split:+.1f} %"},
    )


@rule
def _never_closes_loop(r: Readings, d: dict) -> Finding | None:
    share = d.get("closed_loop_share")
    coolant = r.v("coolant_temp")
    if share is None or coolant is None or not _running(r):
        return None
    if coolant > 70 and share < 10:
        return Finding(
            "open_loop", "warn",
            "Still open loop on a warm engine",
            f"The head is at {coolant:.0f} \u00b0C but the ECU stayed in open "
            f"loop for {100 - share:.0f}% of the last minute. It is fuelling "
            "from the map alone and ignoring the sensors.",
            ["Lambda sensors or heaters", "A stored fault forcing open loop",
             "Decatted or modified exhaust"],
            {"closed_loop_share": f"{share:.0f} %",
             "coolant_temp": f"{coolant:.0f} \u00b0C"},
        )
    return None


# ------------------------------------------------------------- the engine

class Analyzer:
    """Keeps a short rolling window and turns samples into derived values."""

    def __init__(self, profile: EcuProfile | None = None, window_s: float = WINDOW_S):
        self.profile = profile
        self.window_s = window_s
        self._history: deque = deque()
        self._texts: dict = {}

    def reset(self) -> None:
        self._history.clear()
        self._texts.clear()

    # -- feeding ---------------------------------------------------------
    def update(self, samples) -> dict:
        """Record one sweep and return ``{"derived": [...], "findings": [...]}``.

        ``samples`` is a list of :class:`~guzzionboard.diagnostics.Sample` or
        of the dicts they serialise to, so the server and the tests can both
        use it.
        """
        now, texts = {}, {}
        for s in samples:
            d = s if isinstance(s, dict) else s.as_dict()
            if d.get("error"):
                continue
            now[d["key"]] = d.get("value")
            if d.get("text"):
                texts[d["key"]] = d["text"]

        t = time.monotonic()
        self._history.append((t, now))
        while self._history and t - self._history[0][0] > self.window_s:
            self._history.popleft()
        self._texts.update(texts)

        readings = Readings(now, self._history, self.profile)
        readings._texts = self._texts

        derived = self.derive(readings)
        values = {c["key"]: c["value"] for c in derived}
        findings = [f.as_dict() for f in self.findings(readings, values)]
        return {"derived": derived, "findings": findings}

    # -- computing -------------------------------------------------------
    def derive(self, r: Readings) -> list[dict]:
        out = []
        for channel in CHANNELS:
            if not all(k in r._now for k in channel.sources):
                continue
            try:
                value = channel.compute(r)
            except (TypeError, ZeroDivisionError):
                value = None
            if value is None:
                continue
            value = round(value, channel.digits) if channel.digits else int(round(value))
            out.append({
                "key": channel.key,
                "name": channel.name,
                "value": value,
                "unit": channel.unit,
                "group": channel.group,
                "delta": channel.delta,
                "note": channel.note,
                "sources": list(channel.sources),
                "confidence": self.confidence_of(channel),
                "derived": True,
            })
        return out

    def confidence_of(self, channel: DerivedChannel) -> str:
        """The worst confidence among the channel's inputs."""
        if self.profile is None:
            return "documented"
        worst = "verified-bench"
        for key in channel.sources:
            try:
                param = self.profile.parameter(key)
            except Exception:
                return "unknown"
            if confidence_rank(param.confidence) > confidence_rank(worst):
                worst = param.confidence
        return worst

    def findings(self, r: Readings, values: dict) -> list[Finding]:
        out = []
        for check in RULES:
            try:
                finding = check(r, values)
            except (TypeError, ZeroDivisionError):
                finding = None
            if finding is not None:
                out.append(finding)
        order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
        out.sort(key=lambda f: order.get(f.level, 4))
        return out
