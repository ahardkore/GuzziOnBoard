"""Kawasaki KDS3-era CAN broadcast decoder (offline, read-only research).

Source: Arduino forum thread "Kawasaki KDS3 CAN protocol"
(forum.arduino.cc/t/1455097, user ec2021, 2026-08) — observed message table;
cited in docs/CAPTURE_SEARCH_2026-11-03.md Round 25. No license (forum post);
treated as open per project policy, cited only. Candidate-grade: one
forum observation set, not a verified capture.

Broadcast IDs (11-bit, classic CAN):
  0x010 front/rear wheel speed; 0x018 brake status (byte0: 8=off, 0=depressed)
  0x050 KTRC button, 0x058 KACT button, 0x060 mode/ECO button (state tables in source)
  0x100 RPM: bytes0-1 big-endian, ~1 rpm/bit
  0x110 vehicle speed: bytes0-1
  0x120 water temp: raw - 40 degC
  0x121 gear: byte0 gear (0=N, 1-6), byte1 neutral flag
  0x130 TPMS display: front/rear pressure in 0.2 PSI increments + warning bits
  0x220-0x227 ignition/steering-lock/KTRC/KACT/ECO statuses
  0x321 engine status (1=cranking/running, 5=stopped)
  0x695/0x696 front/rear TPMS sensor messages
  0x700-0x7FF diagnostic request/response range (not decoded here)

Passive only; no diagnostic session, no write path.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'kawasaki_kds3_can_broadcast'

FRAME_LENGTHS = {
    0x010: 8, 0x018: 8, 0x050: 8, 0x058: 8, 0x060: 8,
    0x100: 6, 0x110: 6, 0x120: 6, 0x121: 2, 0x130: 4,
    0x220: 8, 0x221: 8, 0x223: 8, 0x224: 8, 0x225: 8, 0x227: 8,
    0x321: 8, 0x695: 8, 0x696: 8,
}
MAX_EVENTS = 200


def decode_frame(frame: CanFrame) -> dict | None:
    if frame.extended or frame.id not in FRAME_LENGTHS:
        return None
    data = bytes(frame.data)
    if len(data) != FRAME_LENGTHS[frame.id]:
        return None
    fid = frame.id
    if fid == 0x100:
        values = {'rpm_candidate': (data[0] << 8) | data[1]}
    elif fid == 0x110:
        values = {'speed_raw_candidate': (data[0] << 8) | data[1]}
    elif fid == 0x120:
        values = {'coolant_c_candidate': ((data[0] << 8) | data[1]) - 40}
    elif fid == 0x121:
        values = {'gear_candidate': data[0], 'neutral_flag': bool(data[1])}
    elif fid == 0x130:
        values = {'tpms_front_psi_candidate': data[0] * 0.2,
                  'tpms_rear_psi_candidate': data[1] * 0.2,
                  'tpms_front_warn': bool(data[2]), 'tpms_rear_warn': bool(data[3])}
    elif fid == 0x018:
        values = {'brake_depressed': data[0] == 0}
    elif fid == 0x321:
        values = {'engine_running': data[0] == 1, 'engine_stopped': data[0] == 5}
    elif fid in (0x220, 0x221, 0x223, 0x224, 0x225, 0x227):
        names = {0x220: 'ignition_on', 0x221: 'steering_unlocked', 0x223: 'steering_unlocked',
                 0x224: 'ktrc_enabled', 0x225: 'kact_high_combined', 0x227: 'eco_on'}
        values = {names[fid]: bool(data[0])}
    elif fid in (0x695, 0x696):
        values = {'tpms_sensor_psi_candidate': data[5] * 0.2, 'counter': data[6],
                  'side': 'front' if fid == 0x695 else 'rear'}
    else:
        values = {'button_state_raw': data[0]}
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
