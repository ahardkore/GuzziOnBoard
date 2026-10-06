"""Offline log overlays and bounded, review-only fuel correction proposals.

This module deliberately does not write calibration images.  It bins measured and
TARGET air/fuel ratio samples against an already-rendered XDF table and reports a
proposal that still has to pass the normal evidence, preview, fitment, and
liability gates in :mod:`guzzionboard.tuning`.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
import math
import statistics
from typing import Any


class LogAnalysisError(ValueError):
    """Raised when a log cannot support a defensible correction proposal."""


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LogAnalysisError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise LogAnalysisError(f"{label} must be finite")
    return number


def _numeric_axis(table: dict, name: str) -> list[float]:
    try:
        values = [_number(value, f"{name}-axis value") for value in table[name]]
    except KeyError as exc:
        raise LogAnalysisError(f"table has no {name} axis") from exc
    if not values:
        raise LogAnalysisError(f"table has an empty {name} axis")
    if len(set(values)) != len(values):
        raise LogAnalysisError(f"table {name} axis contains duplicate values")
    return values


def _nearest(values: list[float], sample: float) -> int | None:
    low, high = min(values), max(values)
    if sample < low or sample > high:
        return None
    return min(range(len(values)), key=lambda index: abs(values[index] - sample))


def analyze_fuel_log(
    table: dict,
    rows: list[dict],
    *,
    x_channel: str,
    y_channel: str,
    measured_afr_channel: str,
    target_afr_channel: str,
    min_samples: int = 3,
    max_correction_percent: float = 10.0,
    max_afr_stddev: float = 0.5,
    time_channel: str = "",
    timestamp_unit: str = "seconds",
    wideband_delay_ms: float = 0.0,
    settle_time_ms: float = 500.0,
    max_time_gap_ms: float = 250.0,
    min_cell_duration_ms: float = 1000.0,
    max_x_rate_per_s: float | None = None,
    max_y_rate_per_s: float | None = None,
) -> dict:
    """Bin an offline log and return bounded fuel correction proposals.

    The conventional fuel-duration relationship is used: ``measured / target``.
    A lean sample (measured AFR above target) therefore proposes more fuel.  No
    claim is made that the selected map is a fuel-duration map; that semantic
    review remains the operator's responsibility.
    """

    if not isinstance(rows, list) or not rows:
        raise LogAnalysisError("at least one log row is required")
    if len(rows) > 200_000:
        raise LogAnalysisError("log analysis is limited to 200000 rows")
    required = {
        "x_channel": x_channel,
        "y_channel": y_channel,
        "measured_afr_channel": measured_afr_channel,
        "target_afr_channel": target_afr_channel,
    }
    for label, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise LogAnalysisError(f"{label} is required")
    if measured_afr_channel == target_afr_channel:
        raise LogAnalysisError("measured and target AFR must use different columns")
    if not isinstance(min_samples, int) or not 1 <= min_samples <= 1000:
        raise LogAnalysisError("min_samples must be an integer from 1 to 1000")
    limit = _number(max_correction_percent, "max_correction_percent")
    if not 0 < limit <= 15:
        raise LogAnalysisError("max_correction_percent must be greater than 0 and at most 15")
    deviation_limit = _number(max_afr_stddev, "max_afr_stddev")
    if not 0.05 <= deviation_limit <= 3:
        raise LogAnalysisError("max_afr_stddev must be from 0.05 to 3 AFR")
    time_channel = str(time_channel or "").strip()
    timestamp_unit = str(timestamp_unit or "").strip().lower()
    if timestamp_unit not in ("seconds", "milliseconds"):
        raise LogAnalysisError("timestamp_unit must be seconds or milliseconds")
    delay_s = _number(wideband_delay_ms, "wideband_delay_ms") / 1000.0
    settle_s = _number(settle_time_ms, "settle_time_ms") / 1000.0
    gap_s = _number(max_time_gap_ms, "max_time_gap_ms") / 1000.0
    duration_s = _number(min_cell_duration_ms, "min_cell_duration_ms") / 1000.0
    if not 0 <= delay_s <= 5:
        raise LogAnalysisError("wideband_delay_ms must be from 0 to 5000")
    if not 0 <= settle_s <= 5:
        raise LogAnalysisError("settle_time_ms must be from 0 to 5000")
    if not 0.001 <= gap_s <= 5:
        raise LogAnalysisError("max_time_gap_ms must be from 1 to 5000")
    if not 0 <= duration_s <= 60:
        raise LogAnalysisError("min_cell_duration_ms must be from 0 to 60000")
    x_rate_limit = None if max_x_rate_per_s in (None, "") else _number(
        max_x_rate_per_s, "max_x_rate_per_s"
    )
    y_rate_limit = None if max_y_rate_per_s in (None, "") else _number(
        max_y_rate_per_s, "max_y_rate_per_s"
    )
    if x_rate_limit is not None and x_rate_limit <= 0:
        raise LogAnalysisError("max_x_rate_per_s must be greater than 0")
    if y_rate_limit is not None and y_rate_limit <= 0:
        raise LogAnalysisError("max_y_rate_per_s must be greater than 0")
    if not time_channel and (delay_s or x_rate_limit is not None or y_rate_limit is not None):
        raise LogAnalysisError(
            "time_channel is required for delay compensation or rate filtering"
        )

    x_values = _numeric_axis(table, "x")
    y_values = _numeric_axis(table, "y")
    buckets: dict[
        tuple[int, int], list[tuple[float, float, float, float, float | None]]
    ] = defaultdict(list)
    skipped = {
        "invalid": 0,
        "invalid_timestamp": 0,
        "alignment_gap": 0,
        "transient": 0,
        "outside_axes": 0,
        "afr_out_of_range": 0,
    }
    parsed: list[dict[str, float | None]] = []
    timeline_rows: list[dict[str, float | None]] = []
    time_scale = 0.001 if timestamp_unit == "milliseconds" else 1.0
    original_times: list[float] = []
    state_only_rows = 0
    for source in rows:
        if not isinstance(source, dict):
            skipped["invalid"] += 1
            continue
        if time_channel:
            try:
                at = _number(source.get(time_channel), time_channel) * time_scale
            except LogAnalysisError:
                skipped["invalid_timestamp"] += 1
                continue
            try:
                state: dict[str, float | None] = {
                    "x": _number(source.get(x_channel), x_channel),
                    "y": _number(source.get(y_channel), y_channel),
                    "target": _number(
                        source.get(target_afr_channel), target_afr_channel
                    ),
                    "time": at,
                }
            except LogAnalysisError:
                skipped["invalid"] += 1
                continue
            # State rows remain useful interpolation anchors even when that
            # logger tick has no valid wideband observation.
            timeline_rows.append(state)
            original_times.append(at)
            try:
                measured = _number(
                    source.get(measured_afr_channel), measured_afr_channel
                )
            except LogAnalysisError:
                skipped["invalid"] += 1
                state_only_rows += 1
                continue
            parsed.append({**state, "measured": measured})
        else:
            try:
                parsed.append({
                    "x": _number(source.get(x_channel), x_channel),
                    "y": _number(source.get(y_channel), y_channel),
                    "measured": _number(
                        source.get(measured_afr_channel), measured_afr_channel
                    ),
                    "target": _number(
                        source.get(target_afr_channel), target_afr_channel
                    ),
                    "time": None,
                })
            except LogAnalysisError:
                skipped["invalid"] += 1

    timeline_reordered = False
    duplicate_timestamps = 0
    timeline: list[dict[str, float | None]] = []
    times: list[float] = []
    if time_channel:
        # Loggers can emit more than one state sample at the same clock tick.
        # Keep every AFR observation, but use the final state at that instant
        # so interpolation is deterministic.
        by_time = {sample["time"]: sample for sample in timeline_rows}
        times = sorted(by_time)
        timeline = [by_time[at] for at in times]
        duplicate_timestamps = len(timeline_rows) - len(timeline)
        if len(timeline) < 2:
            raise LogAnalysisError(
                "time-aware analysis needs at least two valid, distinct timestamps"
            )
        timeline_reordered = (
            original_times != sorted(original_times)
            or duplicate_timestamps > 0
        )

    def timeline_value(at: float) -> dict[str, float] | None:
        """Linearly align state channels and expose local axis rates."""
        position = bisect_left(times, at)
        if position < len(times) and math.isclose(
            times[position], at, abs_tol=1e-12
        ):
            exact = timeline[position]
            if position == 0:
                before, after = timeline[0], timeline[1]
            elif position == len(timeline) - 1:
                before, after = timeline[-2], timeline[-1]
            else:
                before, after = timeline[position - 1], timeline[position + 1]
                if (times[position] - times[position - 1] > gap_s
                        or times[position + 1] - times[position] > gap_s):
                    return None
            delta = after["time"] - before["time"]
            if delta <= 0 or (
                position in (0, len(timeline) - 1) and delta > gap_s
            ):
                return None
            return {
                "x": exact["x"],
                "y": exact["y"],
                "target": exact["target"],
                "x_rate": (after["x"] - before["x"]) / delta,
                "y_rate": (after["y"] - before["y"]) / delta,
            }
        if position == 0 or position == len(times):
            return None
        before, after = timeline[position - 1], timeline[position]
        delta = after["time"] - before["time"]
        if delta <= 0 or delta > gap_s:
            return None
        fraction = (at - before["time"]) / delta
        return {
            key: before[key] + (after[key] - before[key]) * fraction
            for key in ("x", "y", "target")
        } | {
            "x_rate": (after["x"] - before["x"]) / delta,
            "y_rate": (after["y"] - before["y"]) / delta,
        }

    for sample in parsed:
        measured = sample["measured"]
        aligned_time = sample["time"]
        state = sample
        x_rate = y_rate = 0.0
        if time_channel:
            aligned_time = sample["time"] - delay_s
            aligned = timeline_value(aligned_time)
            if aligned is None:
                skipped["alignment_gap"] += 1
                continue
            state = aligned
            x_rate, y_rate = aligned["x_rate"], aligned["y_rate"]
        x_sample, y_sample, target = state["x"], state["y"], state["target"]
        if not (6 <= measured <= 30 and 6 <= target <= 30):
            skipped["afr_out_of_range"] += 1
            continue
        col = _nearest(x_values, x_sample)
        row = _nearest(y_values, y_sample)
        if col is None or row is None:
            skipped["outside_axes"] += 1
            continue
        transient = (
            (x_rate_limit is not None and abs(x_rate) > x_rate_limit)
            or (y_rate_limit is not None and abs(y_rate) > y_rate_limit)
        )
        if time_channel and settle_s:
            settled_before = timeline_value(aligned_time - settle_s)
            settled_after = timeline_value(aligned_time + settle_s)
            transient = transient or (
                settled_before is None
                or settled_after is None
                or _nearest(x_values, settled_before["x"]) != col
                or _nearest(y_values, settled_before["y"]) != row
                or _nearest(x_values, settled_after["x"]) != col
                or _nearest(y_values, settled_after["y"]) != row
            )
        if transient:
            skipped["transient"] += 1
            continue
        buckets[(row, col)].append(
            (measured, target, x_sample, y_sample, aligned_time)
        )

    cells = []
    proposals = []
    for (row, col), samples in sorted(buckets.items()):
        measured_values = [sample[0] for sample in samples]
        target_values = [sample[1] for sample in samples]
        measured = statistics.fmean(measured_values)
        target = statistics.fmean(target_values)
        measured_stddev = statistics.pstdev(measured_values)
        target_stddev = statistics.pstdev(target_values)
        unbounded = (measured / target - 1.0) * 100.0
        correction = max(-limit, min(limit, unbounded))
        enough = len(samples) >= min_samples
        stable = (measured_stddev <= deviation_limit
                  and target_stddev <= deviation_limit)
        sample_times = [sample[4] for sample in samples if sample[4] is not None]
        time_span_s = (
            max(sample_times) - min(sample_times)
            if len(sample_times) > 1 else 0.0
        )
        duration_met = not time_channel or time_span_s + 1e-12 >= duration_s
        eligible = enough and stable and duration_met
        reasons = []
        if not enough:
            reasons.append(f"needs at least {min_samples} samples")
        if not duration_met:
            reasons.append(
                f"needs at least {round(duration_s * 1000)} ms of aligned dwell"
            )
        if measured_stddev > deviation_limit:
            reasons.append("measured AFR is too variable")
        if target_stddev > deviation_limit:
            reasons.append("target AFR is too variable")
        cell = {
            "row": row,
            "col": col,
            "x": table["x"][col],
            "y": table["y"][row],
            "samples": len(samples),
            "time_span_s": round(time_span_s, 4) if time_channel else None,
            "duration_eligible": duration_met,
            "measured_afr": round(measured, 4),
            "target_afr": round(target, 4),
            "measured_afr_stddev": round(measured_stddev, 4),
            "target_afr_stddev": round(target_stddev, 4),
            "error_percent": round(unbounded, 4),
            "correction_percent": round(correction, 4),
            "clamped": correction != unbounded,
            "eligible": eligible,
            "eligibility": "eligible" if eligible else "; ".join(reasons),
        }
        cells.append(cell)
        if eligible:
            before = _number(table["values"][row][col], "table value")
            proposals.append({
                **cell,
                "kind": "table",
                "id": table["id"],
                "title": table["title"],
                "units": table.get("units", ""),
                "expected_raw": table["raw_values"][row][col],
                "before": before,
                "proposed_value": before * (1.0 + correction / 100.0),
            })

    return {
        "table": {
            "id": table["id"],
            "title": table["title"],
            "units": table.get("units", ""),
            "x_units": table.get("x_units", ""),
            "y_units": table.get("y_units", ""),
        },
        "rows_received": len(rows),
        "rows_used": sum(len(samples) for samples in buckets.values()),
        "skipped": skipped,
        "min_samples": min_samples,
        "max_correction_percent": limit,
        "max_afr_stddev": deviation_limit,
        "time_alignment": {
            "enabled": bool(time_channel),
            "time_channel": time_channel,
            "timestamp_unit": timestamp_unit,
            "wideband_delay_ms": delay_s * 1000.0,
            "settle_time_ms": settle_s * 1000.0,
            "max_time_gap_ms": gap_s * 1000.0,
            "min_cell_duration_ms": duration_s * 1000.0 if time_channel else None,
            "max_x_rate_per_s": x_rate_limit,
            "max_y_rate_per_s": y_rate_limit,
            "timeline_points": len(timeline),
            "duplicate_timestamps": duplicate_timestamps,
            "state_only_rows": state_only_rows,
            "timeline_reordered": timeline_reordered,
            "method": (
                "measured AFR at t; linearly interpolated x/y/target at "
                "t minus wideband delay"
                if time_channel else "row-synchronous; no timestamp alignment"
            ),
        },
        "cells": cells,
        "proposals": proposals,
        "formula": "fuel change percent = clamp((mean measured AFR / mean target AFR - 1) * 100)",
        "review_only": True,
        "warnings": [
            "No image was changed. These are review-only mathematical proposals.",
            "Confirm that the selected table controls fuel quantity in the logged operating state.",
            "Cells whose measured or target AFR population standard deviation exceeds the configured limit are not eligible.",
            (
                "Timestamp alignment compensates the configured wideband delay, "
                "rejects unsettled/rate-limited samples, and requires the configured "
                "per-cell dwell duration; inspect the diagnostics and skipped counts."
                if time_channel else
                "No timestamp channel was selected, so sensor delay and transient "
                "alignment were not evaluated."
            ),
            "Closed-loop correction, bad sensors, exhaust leaks, and incorrect delay settings can invalidate AFR corrections.",
            "A proposal still requires configuration-specific evidence, exact preview review, and liability acknowledgement before a separate build.",
        ],
    }
