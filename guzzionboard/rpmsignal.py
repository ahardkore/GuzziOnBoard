"""Bench RPM trigger-signal generator (audio WAV), covering RPMSensorEmu's job.

The reference tool (``RPMSensorEmu_V0.17``, mirrored in
``vendor/guzzidiag/tools/``) drives dedicated hardware to feed an ECU a
believable crank or cam position signal on the bench. This module covers
the same need with the hardware a laptop already has: it renders the
trigger pattern to a plain 16-bit PCM WAV. Played through an AC-coupled
buffer/attenuator into the sensor input, the ECU "sees" a running engine.

**This is a bench aid, not an ECU driver.** Sound cards output ~1 V RMS
AC-coupled; never wire a laptop output straight into a harness. Use a
series capacitor and attenuator, stay within the sensor input's voltage
range, and remember the generator shares the engine-safety rules: an ECU
that believes the engine turns may fire coils and injectors.

Wheel geometry is imported verbatim from the reference tool's own config
files (``vendor/guzzidiag/tools/RPMSensorEmu_V0.17.zip``):

- Moto Guzzi / Ducati / Moto Morini: 46 present teeth, 2 missing, *camshaft*
  (pattern repeats once per cycle: two crank revolutions)
- MV Agusta: 22 present teeth, 2 missing, *crankshaft*

Its batch files (``duration_ms | rpm1 | optional rpm2``, 100 ms quanta, a
linear ramp between the two RPMs) are the ``events`` format here too.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import time
import wave

DEFAULT_SIGNAL_DIR = Path.home() / ".guzzionboard" / "signals"
DEFAULT_SAMPLE_RATE = 44100
BATCH_QUANTUM_MS = 100  # the reference batch format resolves 100 ms steps


class SignalError(ValueError):
    """The requested pattern or event list cannot be rendered."""


@dataclass(frozen=True)
class TriggerWheel:
    teeth: int          # present teeth (N)
    missing: int        # consecutive missing teeth (M)
    wheel: str          # "crankshaft" or "camshaft"

    @property
    def slots(self) -> int:
        return self.teeth + self.missing

    def pattern_rev_rate(self, rpm: float) -> float:
        """Wheel revolutions per second at an engine speed."""
        per_minute = rpm if self.wheel == "crankshaft" else rpm / 2.0
        return per_minute / 60.0


#: Presets transcribed from the reference tool's config files.
PRESETS: dict[str, TriggerWheel] = {
    "motoguzzi": TriggerWheel(46, 2, "camshaft"),  # MotoGuzzi.cfg
    "ducati": TriggerWheel(46, 2, "camshaft"),     # Ducati.cfg
    "motomorini": TriggerWheel(46, 2, "camshaft"),  # MotoMorini.cfg
    "mvagusta": TriggerWheel(22, 2, "crankshaft"),  # MVAgusta.cfg
}


def parse_events(spec: list[list[float]]) -> list[tuple[int, float, float]]:
    """Reference batch semantics: ``duration_ms | rpm1 | optional rpm2``.

    Durations must be multiples of 100 ms (the reference tool's own rule);
    ``rpm2`` absent means hold ``rpm1``. Returns
    ``(duration_ms, rpm_start, rpm_end)`` triples.
    """
    events: list[tuple[int, float, float]] = []
    for row in spec:
        if len(row) not in (2, 3):
            raise SignalError(
                f"batch row {row!r}: expected duration|rpm1[|rpm2]"
            )
        duration_ms = int(row[0])
        if duration_ms <= 0 or duration_ms % BATCH_QUANTUM_MS:
            raise SignalError(
                f"duration {duration_ms} ms is not a multiple of "
                f"{BATCH_QUANTUM_MS} ms"
            )
        r1, r2 = float(row[1]), float(row[2]) if len(row) == 3 else float(row[1])
        if r1 <= 0 or r2 <= 0:
            raise SignalError("rpm values must be positive")
        events.append((duration_ms, r1, r2))
    if not events:
        raise SignalError("no events to render")
    return events


def render_samples(
    wheel: TriggerWheel,
    events: list[tuple[int, float, float]],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    duty: float = 0.5,
    amplitude: float = 0.7,
) -> dict:
    """Render the trigger train to 16-bit PCM samples.

    The generator integrates slot position continuously (phase-correct even
    across ramps): ``pos`` counts slots elapsed, each wheel revolution is
    ``wheel.slots`` slots, a tooth's high phase occupies ``duty`` of its
    slot, missing slots stay low — producing the long gap synchronisation
    point every wheel revolution.
    """
    if not 0.05 <= duty <= 0.95:
        raise SignalError("duty must be between 0.05 and 0.95")
    if not 0.0 < amplitude <= 1.0:
        raise SignalError("amplitude must be in (0, 1]")
    if sample_rate < 8000:
        raise SignalError("sample_rate must be at least 8000 Hz")

    hi = int(amplitude * 32767)
    lo = -hi  # bipolar square: AC-coupling friendly, matches VR-ish polarity

    samples = bytearray()
    pos = 0.0  # slot position; floor(pos) % slots = slot index
    total = 0
    for duration_ms, r1, r2 in events:
        n = int(sample_rate * duration_ms / 1000)
        for i in range(n):
            # linear rpm ramp across the segment
            seg_frac = (i / n) if n else 0.0
            rpm = r1 + (r2 - r1) * seg_frac
            slot_rate = wheel.pattern_rev_rate(rpm) * wheel.slots
            pos += slot_rate / sample_rate
            slot = int(pos) % wheel.slots
            within = pos - int(pos)
            level = hi if (slot < wheel.teeth and within < duty) else lo
            samples += struct.pack("<h", level)
        total += n

    return {
        "pcm": bytes(samples),
        "sample_rate": sample_rate,
        "duration_s": total / sample_rate,
        "events": events,
    }


def write_wav(rendered: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rendered["sample_rate"])
        w.writeframes(rendered["pcm"])
    return path


def generate(
    wheel: TriggerWheel,
    events: list[list[float]],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    duty: float = 0.5,
    amplitude: float = 0.7,
    out_dir: Path = DEFAULT_SIGNAL_DIR,
    name: str = "",
) -> dict:
    """Render a batch event list and write a mono 16-bit WAV file."""
    parsed = parse_events(events)
    rendered = render_samples(
        wheel, parsed, sample_rate=sample_rate, duty=duty, amplitude=amplitude
    )
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = name or f"{wheel.teeth}-{wheel.missing}missing-{wheel.wheel}"
    path = write_wav(rendered, Path(out_dir) / f"rpmsim-{tag}-{stamp}.wav")
    return {
        "path": str(path),
        "pattern": tag,
        "wheel": wheel.wheel,
        "teeth": wheel.teeth,
        "missing": wheel.missing,
        "slots": wheel.slots,
        "duration_s": round(rendered["duration_s"], 3),
        "sample_rate": rendered["sample_rate"],
        "duty": duty,
        "amplitude": amplitude,
        "events": parsed,
        "safety": (
            "Bench aid: AC-couple and attenuate into the sensor input, never "
            "drive a harness directly. An ECU that believes the engine turns "
            "can energise coils and injectors — disconnect the outputs you do "
            "not want live."
        ),
        "note": (
            f"Gap length is {wheel.missing + 1}x the tooth period "
            f"({wheel.missing} missing teeth + the low halves of the "
            "neighbouring duty cycles); wheel geometric data from the "
            "reference tool's config files."
        ),
    }
