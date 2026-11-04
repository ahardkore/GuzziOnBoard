"""KTM 690 Enduro R CAN broadcast decoder (offline, read-only research).

Source: blalor/ktm-can @ 299b4e080168986ab535b81b81e2a9196f0c8c66
(no license stated — treated as open per project policy; reimplemented and
cited, Round 27 in docs/CAPTURE_SEARCH_2026-11-03.md). Extended/confirmed by
ChickenPoptart/KTMComputer (2020 690 Enduro R ride logs) and Dan Plastina's
SuperDuke 1290 ADVrider work. Single-model observation set (2020 690 Enduro
R) — candidate-grade, not a verified capture for all KTM models.

Broadcast IDs (11-bit, 8-byte frames):
  0x120 20ms  RPM BE16 (D0-1), throttle raw D2, kill switch D3.B4,
              throttle map D4.B0
  0x129 20ms  gear hi-nibble D0 (0=N), clutch D0.B3
  0x12A 50ms  throttle_open D0.B1 (inverted), requested map D1.B6
  0x12B 10ms  front/rear wheel speed BE16 (D0-3), tilt signed12 (D5,D6 hi),
              lean signed12 (D6 lo, D7)
  0x290 10ms  front brake pressure BE16 (D0-1)
  0x450 50ms  traction control button D2.B0
  0x540 100ms RPM BE16 (D1-2), gear lo-nibble D3, kickstand up/err D4,
              coolant °C BE16/10 (D6-7)

Passive only; no diagnostic session, no write path.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'ktm_690_can_broadcast'

FRAME_LENGTHS = {0x120: 8, 0x129: 8, 0x12A: 8, 0x12B: 8, 0x290: 8, 0x450: 8, 0x540: 8}
MAX_EVENTS = 200


def _signed12(v: int) -> int:
    return -(v & 0x800) | (v & 0x7FF)


def decode_frame(frame: CanFrame) -> dict | None:
    if frame.extended or frame.id not in FRAME_LENGTHS:
        return None
    data = bytes(frame.data)
    if len(data) != 8:
        return None
    fid = frame.id
    if fid == 0x120:
        values = {'rpm_candidate': (data[0] << 8) | data[1], 'throttle_raw': data[2],
                  'kill_switch_run': bool((data[3] >> 4) & 1), 'throttle_map_candidate': data[4] & 1}
    elif fid == 0x129:
        values = {'gear_candidate': (data[0] >> 4) & 0xF, 'clutch_in': bool((data[0] >> 3) & 1)}
    elif fid == 0x12A:
        values = {'throttle_open': ((data[0] >> 1) & 1) == 0, 'requested_map_candidate': (data[1] >> 6) & 1}
    elif fid == 0x12B:
        values = {'front_wheel_raw_candidate': (data[0] << 8) | data[1],
                  'rear_wheel_raw_candidate': (data[2] << 8) | data[3],
                  'tilt_candidate': _signed12((data[5] << 4) | (data[6] >> 4)),
                  'lean_candidate': _signed12(((data[6] & 0xF) << 8) | data[7])}
    elif fid == 0x290:
        values = {'front_brake_raw_candidate': (data[0] << 8) | data[1]}
    elif fid == 0x450:
        values = {'traction_button_candidate': data[2] & 1}
    elif fid == 0x540:
        values = {'rpm_candidate': (data[1] << 8) | data[2], 'gear_candidate': data[3] & 0xF,
                  'kickstand_up': bool(data[4] & 1), 'kickstand_err': bool((data[4] >> 7) & 1),
                  'coolant_c_candidate': (((data[6] << 8) | data[7]) / 10.0)}
    else:
        return None
    return {'id': fid, 'values': values}


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in FRAME_LENGTHS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        decoded = decode_frame(frame)
        if decoded is None:
            invalid += 1
            continue
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append(decoded)
    return {'profile': PROFILE, 'recognized': recognized, 'invalid': invalid,
            'ignored_tx': ignored_tx, 'events': events}
