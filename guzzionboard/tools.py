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
        at = round(float(event.get("at", 0)), 2)
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
        at = round(float(event.get("at", 0)), 2)
        rows.setdefault(at, {"time": at})[
            event.get("key") or "value"
        ] = event.get("value")
    return json.dumps([rows[a] for a in sorted(rows)], indent=2)


#: Export formats offered to the UI.
EXPORTERS = {
    "csv": samples_to_csv,
    "json": samples_to_json,
}
