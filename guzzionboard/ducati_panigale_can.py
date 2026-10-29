"""Opt-in offline Ducati Mitsubishi CAN capture interpretation.

Adapted from DucatiPanigaleCanBus, src/canbusble.cpp and
src/DucatiPanigaleCanbus.lua, commit 03e7127c69ee3398c03076352ac93bbd3f795ce2.
Copyright (c) 2021 Renato Bonomini, MIT; see LICENSES/DucatiPanigaleCanBus-MIT.txt.
No live transport, vehicle identification, diagnostic ID inference or ECU write.
Values are research leads; this is not a Moto Guzzi profile.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = "ducati_panigale_mitsubishi"
MAX_EVENTS = 200


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    """Interpret selected standard data frames, with original bytes retained.

    The upstream Arduino code stores temperatures in unsigned bytes; here
    offsets are computed as signed integers so below-zero values do not wrap.
    APS integer truncation and all other bit/byte choices follow upstream.
    """
    events: list[dict] = []
    recognized = short = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in (0x18, 0x80, 0x100):
            continue
        if frame.direction.lower().startswith("t"):
            ignored_tx += 1
            continue
        data = frame.data
        minimum = 7 if frame.id == 0x80 else 6
        if len(data) < minimum or len(data) > 8:
            short += 1
            continue
        if frame.id == 0x80:
            values = {"throttle_percent": data[4] // 2, "rpm": data[5] * 256 + data[6]}
        elif frame.id == 0x18:
            values = {"rear_wheel_speed_kmh": ((data[4] & 0x1f) << 4) + (data[5] >> 4),
                      "gear_raw": data[4] // 32}
        else:
            values = {"coolant_c": data[3] - 40, "air_c": data[5] - 40,
                      "battery_v": data[4] / 10}
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({"timestamp": frame.timestamp, "id": f"0x{frame.id:X}",
                           "direction": frame.direction or "unknown", "raw": data.hex().upper(),
                           "values": values})
    return {"profile": PROFILE, "events": events, "recognized_frames": recognized,
            "invalid_length_frames": short, "ignored_tx_frames": ignored_tx,
            "omitted_events": max(0, recognized - len(events))}
