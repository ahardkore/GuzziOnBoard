"""Offline Harley HDLAN community decoder, not an ECU session.

Adapted from HarleyDroid EVO HarleyCan.kt, commit
668b63efc05977eb65cb8e84e597ae2205355d4c. Copyright (C) 2010-2012
Stelian Pop and (C) 2026 Quickosss, GPL-3.0-or-later; see
LICENSES/HarleyDroidEVO-GPL-3.0.txt. Source calls its CAN mappings
best-effort and states layouts vary across models and years.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = "harley_hdlan_community"
MAX_EVENTS = 200
MIN_LENGTH = {0x521: 2, 0x5C0: 8, 0x541: 6, 0x550: 1, 0x530: 3, 0x5C1: 2}


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events: list[dict] = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in MIN_LENGTH:
            continue
        if frame.direction.lower().startswith("t"):
            ignored_tx += 1
            continue
        data = frame.data
        if not MIN_LENGTH[frame.id] <= len(data) <= 8:
            invalid += 1
            continue
        if frame.id == 0x521:
            # Source's best-effort fallback, not an inferred signal definition.
            byte_index = 2 if data[1] == 0 and len(data) >= 3 and data[2] else 1
            values = {"speed_kmh_candidate": data[byte_index], "source_byte_index": byte_index}
        elif frame.id == 0x5C0:
            values = {"odometer_km_candidate": int.from_bytes(data[5:8], "big")}
        elif frame.id == 0x541:
            values = {"engine_temp_c_candidate": data[5]}
        elif frame.id == 0x550:
            values = {"clutch_candidate": bool(data[0] & 1)}
        elif frame.id == 0x530:
            values = {"neutral_candidate": bool(data[2] & 0x81), "status_byte": data[2]}
        else:
            # RPM is explicitly tentative upstream; preserve source's bounds
            # and expose the byte pair chosen, never estimate gear.
            rpm = int.from_bytes(data[0:2], "big") // 4
            byte_index = 0
            if not 1 <= rpm <= 9000 and len(data) >= 4:
                rpm = int.from_bytes(data[2:4], "big") // 4
                byte_index = 2
            values = {"rpm_candidate": rpm if 1 <= rpm <= 9000 else None,
                      "source_byte_index": byte_index}
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({"timestamp": frame.timestamp, "id": f"0x{frame.id:X}",
                           "direction": frame.direction or "unknown", "raw": data.hex().upper(),
                           "values": values})
    return {"profile": PROFILE, "events": events, "recognized_frames": recognized,
            "invalid_length_frames": invalid, "ignored_tx_frames": ignored_tx,
            "omitted_events": max(0, recognized - len(events))}
