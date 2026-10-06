"""Standalone calculators and exporters.

The small utilities that ship alongside the GuzziDiag toolchain: a gearing
and road-speed calculator, and log export so recorded sessions can leave this
program for a spreadsheet or a plotting tool.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Gearing and road speed
# --------------------------------------------------------------------------

#: Tyre sizes in the usual "190/55-17" marking.
def tyre_circumference_m(marking: str) -> float:
    """Rolling circumference in metres from a tyre marking like 180/55-17."""
    try:
        section, rest = marking.split("/", 1)
        aspect, rim = rest.replace("ZR", "-").replace("R", "-").split("-")[:2]
        width_mm = float(section)
        aspect_pct = float(aspect)
        rim_in = float(rim)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"cannot parse tyre marking {marking!r}") from exc
    sidewall_mm = width_mm * aspect_pct / 100.0
    diameter_mm = rim_in * 25.4 + 2 * sidewall_mm
    return math.pi * diameter_mm / 1000.0


@dataclass
class Gearing:
    """A driveline, from crankshaft to tyre.

    Shaft-drive Guzzis use a bevel box rather than a chain and sprockets, so
    the final drive is a ratio rather than a tooth count.
    """

    primary: float = 1.0
    final_drive: float = 4.125           # typical Guzzi bevel box, e.g. 33/8
    gears: list[float] = field(
        default_factory=lambda: [2.308, 1.619, 1.250, 1.038, 0.870, 0.750]
    )
    tyre: str = "180/55-17"

    @property
    def circumference_m(self) -> float:
        return tyre_circumference_m(self.tyre)

    def speed_kmh(self, rpm: float, gear: int) -> float:
        """Road speed at a given engine rpm in a given gear (1-based)."""
        if not 1 <= gear <= len(self.gears):
            raise ValueError(f"gear {gear} outside 1..{len(self.gears)}")
        ratio = self.primary * self.gears[gear - 1] * self.final_drive
        wheel_rpm = rpm / ratio
        return wheel_rpm * self.circumference_m * 60.0 / 1000.0

    def rpm_at(self, speed_kmh: float, gear: int) -> float:
        per_rpm = self.speed_kmh(1000.0, gear) / 1000.0
        return speed_kmh / per_rpm if per_rpm else 0.0

    def table(self, rpm_values: list[int] | None = None) -> dict:
        rpm_values = rpm_values or list(range(1000, 8001, 500))
        return {
            "tyre": self.tyre,
            "circumference_m": round(self.circumference_m, 3),
            "final_drive": self.final_drive,
            "rpm": rpm_values,
            "gears": {
                f"gear{g}": [round(self.speed_kmh(r, g), 1) for r in rpm_values]
                for g in range(1, len(self.gears) + 1)
            },
        }

    def infer_gear(self, rpm: float, speed_kmh: float, *, tolerance: float = 0.12):
        """Which gear best explains an rpm/speed pair.

        Useful for sanity-checking a speed sensor, and for labelling logged
        data that has no gear-position signal.
        """
        if speed_kmh <= 0 or rpm <= 0:
            return None
        best, best_error = None, tolerance
        for gear in range(1, len(self.gears) + 1):
            predicted = self.speed_kmh(rpm, gear)
            error = abs(predicted - speed_kmh) / speed_kmh
            if error < best_error:
                best, best_error = gear, error
        return best


#: Per-model gearbox ratio sets, read out of the mirrored reference app
#: GearSpeed_V1.55 (vendor/guzzidiag/tools/GearSpeed_V1.55.zip) — the same
#: table that app ships, so the gearing view presets feel familiar to anyone
#: coming from it. Ratios are exactly as published there; entries that pad a
#: 5-speed box to six slots with "0.0000" are trimmed to the real gear count.
GEARING_PRESETS: dict[str, dict] = {
    "Moto Guzzi — 1000 G5":          {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — 1200 Sport":       {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9355, 0.8000], "max_rpm": 8750},
    "Moto Guzzi — Bellagio":         {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Breva 750":        {"gears": [2.3636, 1.6429, 1.2778, 1.0556, 0.9000], "max_rpm": 8750},
    "Moto Guzzi — Breva 850":        {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Breva 1100":       {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8000], "max_rpm": 8750},
    "Moto Guzzi — Breva 1200":       {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9355, 0.8000], "max_rpm": 8750},
    "Moto Guzzi — California III early": {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — California EV / Special / Jackal / Vintage (-2000)": {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — California 2001 EV": {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — California 1400":  {"gears": [2.235, 1.7, 1.347, 1.115, 0.967, 0.8], "max_rpm": 7000},
    "Moto Guzzi — Daytona":          {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Daytona RS":       {"gears": [1.8125, 1.2500, 1.0000, 0.8333, 0.7308], "max_rpm": 8750},
    "Moto Guzzi — Griso 850":        {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Griso 1100":       {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Griso 1200":       {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Le Mans I":        {"gears": [2.0000, 1.3888, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — Le Mans II":       {"gears": [2.0000, 1.3888, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — Le Mans III":      {"gears": [2.0000, 1.3888, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — Le Mans 1000":     {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — MGS01":            {"gears": [2.4000, 1.7778, 1.3636, 1.1111, 0.9655, 0.8519], "max_rpm": 8750},
    "Moto Guzzi — Norge 1200 early": {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — Norge 1200 late":  {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9355, 0.8000], "max_rpm": 8750},
    "Moto Guzzi — Quota 1100 ES":    {"gears": [2.0000, 1.3158, 1.0000, 0.8462, 0.7308], "max_rpm": 8750},
    "Moto Guzzi — Sport 1100 i":     {"gears": [1.8125, 1.2500, 1.0000, 0.8333, 0.7308], "max_rpm": 8750},
    "Moto Guzzi — Stelvio":          {"gears": [2.2353, 1.7000, 1.3478, 1.1154, 0.9677, 0.8621], "max_rpm": 8750},
    "Moto Guzzi — V7":               {"gears": [2.3636, 1.6429, 1.2778, 1.0556, 0.9000], "max_rpm": 7500},
    "Moto Guzzi — V7 II":            {"gears": [2.6429, 1.7778, 1.3333, 1.0833, 0.9600, 0.8889], "max_rpm": 7500},
    "Moto Guzzi — V7 III":           {"gears": [2.4375, 1.7778, 1.3333, 1.0833, 0.9600, 0.8571], "max_rpm": 7500},
    "Moto Guzzi — V7 850":           {"gears": [2.4375, 1.7778, 1.3333, 1.0833, 0.9600, 0.8571], "max_rpm": 7500},
    "Moto Guzzi — V9":               {"gears": [2.4375, 1.7778, 1.3333, 1.0833, 0.9600, 0.8571], "max_rpm": 7500},
    "Moto Guzzi — V10 Centauro":     {"gears": [2.0000, 1.3158, 1.0000, 0.8462, 0.7692], "max_rpm": 8750},
    "Moto Guzzi — V10 Centauro CH":  {"gears": [2.0000, 1.3889, 1.0476, 0.8696, 0.7500], "max_rpm": 8750},
    "Moto Guzzi — V11 (170/60-17)":  {"gears": [2.4000, 1.7778, 1.3636, 1.1111, 0.9655, 0.8519], "max_rpm": 8750},
    "Moto Guzzi — V11 (180/55-17)":  {"gears": [2.4000, 1.7778, 1.3636, 1.1111, 0.9655, 0.8519], "max_rpm": 8750},
    "Moto Guzzi — V35 / V35TT / V50": {"gears": [2.727, 1.733, 1.277, 1.045, 0.909], "max_rpm": 8000},
    "Moto Guzzi — V65 / V65 Lario":  {"gears": [2.3636, 1.6428, 1.2777, 1.0555, 0.9000], "max_rpm": 8000},
    "Moto Guzzi — V85TT":            {"gears": [2.4375, 1.7778, 1.3333, 1.0833, 0.9600, 0.8889], "max_rpm": 7500},
    "Aprilia — RSV4 Factory":        {"gears": [2.3750, 1.9444, 1.6471, 1.4545, 1.3077, 1.2222], "max_rpm": 14000},
    "BMW — HP4 Race":                {"gears": [2.3889, 2.0000, 1.7273, 1.5455, 1.4000, 1.2917], "max_rpm": 14500},
    "BMW — S 1000 RR":               {"gears": [2.647, 2.091, 1.727, 1.500, 1.360, 1.261], "max_rpm": 14000},
    "MV Agusta — Brutale 1090RR (2010)": {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.211], "max_rpm": 13500},
    "MV Agusta — Brutale 989 / 1078": {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.211], "max_rpm": 12000},
    "MV Agusta — Brutale 990 ET 1090": {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.211], "max_rpm": 13500},
    "MV Agusta — Brutale 1090RR Y12 + CORSA": {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.211], "max_rpm": 13500},
    "MV Agusta — Brutale 920":       {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.211], "max_rpm": 13500},
    "MV Agusta — Brutale 910":       {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.19], "max_rpm": 12000},
    "MV Agusta — B4 750":            {"gears": [2.92, 2.21, 1.78, 1.5, 1.32, 1.21], "max_rpm": 12000},
    "MV Agusta — F4 1000 Y04 + AGO + SENNA": {"gears": [2.92, 2.12, 1.78, 1.5, 1.32, 1.19], "max_rpm": 14000},
    "MV Agusta — F4 1000 Y05 + TAMBURINI": {"gears": [2.923, 2.125, 1.778, 1.5, 1.318, 1.19], "max_rpm": 14000},
    "MV Agusta — F4 312 / 1000 / 1078 Y08": {"gears": [2.923, 2.06, 1.778, 1.5, 1.318, 1.19], "max_rpm": 14000},
    "MV Agusta — F4S Y10":           {"gears": [2.64, 2.06, 1.72, 1.5, 1.318, 1.19], "max_rpm": 15000},
    "MV Agusta — F4 Y10":            {"gears": [2.643, 2.062, 1.722, 1.5, 1.318, 1.19], "max_rpm": 15000},
    "MV Agusta — B3 800 / Dragster / Rivale (<Y16)": {"gears": [2.846, 2.125, 1.778, 1.579, 1.429, 1.318], "max_rpm": 13000},
    "MV Agusta — Dragster RR":       {"gears": [2.846, 2.125, 1.778, 1.579, 1.429, 1.318], "max_rpm": 14000},
    "MV Agusta — Turismo Veloce":    {"gears": [2.846, 2.188, 1.778, 1.5, 1.318, 1.19], "max_rpm": 13000},
    "MV Agusta — B3 675 (<Y16)":     {"gears": [2.846, 2.125, 1.778, 1.579, 1.429, 1.318], "max_rpm": 13000},
    "MV Agusta — F3 675 / 800":      {"gears": [2.846, 2.125, 1.778, 1.579, 1.429, 1.318], "max_rpm": 15000},
}


# --------------------------------------------------------------------------
# Log export
# --------------------------------------------------------------------------


def samples_to_csv(events: list[dict], *, include_raw: bool = False) -> str:
    """Flatten session-log sample events into a wide CSV, one row per instant.

    Each sample event carries one channel, so they are bucketed by timestamp
    to produce the column-per-channel layout a spreadsheet expects.
    """
    rows: dict[float, dict] = {}
    channels: list[str] = []
    for event in events:
        if event.get("kind") != "sample":
            continue
        # Session files timestamp with "t"; the older in-memory shape used
        # "at". Reading only one of them silently collapsed every sweep of a
        # real recording into a single row at time zero.
        at = round(float(event.get("at", event.get("t", 0))), 2)
        key = event.get("key") or event.get("parameter") or "value"
        row = rows.setdefault(at, {"time": at})
        row[key] = event.get("value")
        if include_raw and event.get("raw"):
            row[f"{key}_raw"] = event["raw"]
        if key not in channels:
            channels.append(key)

    if not rows:
        return ""

    header = ["time"]
    for channel in channels:
        header.append(channel)
        if include_raw:
            header.append(f"{channel}_raw")

    first = min(rows)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for at in sorted(rows):
        row = dict(rows[at])
        row["time"] = round(at - first, 2)
        writer.writerow(row)
    return buffer.getvalue()


def samples_to_json(events: list[dict]) -> str:
    rows: dict[float, dict] = {}
    for event in events:
        if event.get("kind") != "sample":
            continue
        at = round(float(event.get("at", event.get("t", 0))), 2)
        rows.setdefault(at, {"time": at})[
            event.get("key") or "value"
        ] = event.get("value")
    return json.dumps([rows[a] for a in sorted(rows)], indent=2)


def samples_to_analysis_csv(events: list[dict]) -> str:
    """The wide CSV with a units row and the raw bytes beside every value."""
    from .replay import to_csv

    return to_csv(events)


#: Export formats offered to the UI. "csv" is the one with provenance in it:
#: units on the second row and the raw bytes next to every value.
EXPORTERS = {
    "csv": samples_to_analysis_csv,
    "csv_plain": samples_to_csv,
    "json": samples_to_json,
}
