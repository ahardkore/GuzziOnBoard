"""Triumph CAN broadcast decoder (offline, read-only research).

Sources (Round 28, docs/CAPTURE_SEARCH_2026-11-03.md):
  * talss89/motorcycle-canbus-info @ main, Motorcycles/triumph-tiger-1200-gen3.md
    (MIT, LICENSES/MotorcycleCanbusInfo-MIT.txt) — 2017-2021 Tiger 1200 Gen 3
    sniffing notes: 0x500 brake light (D4.B3), 0x567 handlebar controls
    (2-bit crumb per button, 1=inactive/2=pressed), 0x600 TPMS full byte map,
    0x210 ABS brake pressure (bytes unresolved).
  * triumph675.net forum "ECU to DASH CAN bus Message IDs" (2018, Daytona 675 /
    Street Triple 2013 era, cross-checked with TobiasRad triumphrat.net 2019
    Street Triple 2013 dash-eliminator work): 0x518 RPM/4 candidate,
    0x519 TPS-ish candidate, 0x540 gear bits 6..4 + neutral light B1 + CEL B2,
    0x550 coolant bars bits 2..0 + warning light B3, 0x570 coolant temp
    BE16/10 at D2-3.

Reimplemented and cited, not vendored. Single-model sniffing notes plus one
forum observation set — candidate-grade, not verified captures. Passive
only; no diagnostic session, no write path.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'triumph_can_broadcast'

FRAME_LENGTHS = {0x210: 8, 0x500: 8, 0x567: 8, 0x600: 8,
                 0x518: 8, 0x519: 8, 0x540: 8, 0x550: 8, 0x570: 8}
MAX_EVENTS = 200

# 0x567 button crumbs: (byte, bit_low_of_pair) -> name; value 1=inactive, 2=pressed
_BUTTONS = [
    (1, 0, 'horn'), (1, 2, 'joystick_press'), (1, 4, 'indicator_left'),
    (1, 6, 'fog_light'), (2, 0, 'joystick_left'), (2, 2, 'joystick_right'),
    (2, 6, 'home'), (3, 0, 'joystick_up'), (3, 2, 'indicator_cancel'),
    (3, 4, 'headlight_flash'), (3, 6, 'joystick_down'), (4, 0, 'indicator_right'),
    (4, 2, 'heated_seat'), (4, 4, 'mode'),
]


def decode_frame(frame: CanFrame) -> dict | None:
    if frame.extended or frame.id not in FRAME_LENGTHS:
        return None
    data = bytes(frame.data)
    if len(data) != 8:
        return None
    fid = frame.id
    if fid == 0x567:
        values = {}
        for byte, bit, name in _BUTTONS:
            crumb = (data[byte] >> bit) & 0x3
            values[f'btn_{name}'] = {1: 'inactive', 2: 'pressed'}.get(crumb, f'raw_{crumb}')
    elif fid == 0x600:
        values = {
            'tyre': 'front' if data[1] == 0x00 else 'rear' if data[1] == 0x10 else 'unknown',
            'pressure_psi_candidate': data[2] / 5.0,
            'temperature_c_candidate': data[3] - 50,
            'pressure_status_candidate': (data[4] >> 4) & 0xF,
            'battery_status_candidate': data[4] & 0xF,
            # doc bytes 6+7 (1-indexed) = data[5], data[6] uint16 counter; byte 8 = data[7] faults
            'data_counter': (data[5] << 8) | data[6],
            'fault_status_candidate': ((data[7] >> 4) & 0xF, data[7] & 0xF),
        }
    elif fid == 0x500:
        values = {'brake_light_candidate': bool((data[4] >> 3) & 1)}
    elif fid == 0x210:
        values = {'abs_brake_pressure_raw_candidate': (data[0] << 8) | data[1]}
    elif fid == 0x518:
        values = {'rpm_candidate': (((data[0] << 8) | data[1]) / 4.0)}
    elif fid == 0x519:
        values = {'tps_raw_candidate': (data[0] << 8) | data[1]}
    elif fid == 0x540:
        values = {'gear_candidate': (data[0] >> 4) & 0x7, 'neutral_light': bool(data[0] & 2),
                  'check_engine_candidate': bool(data[0] & 4)}
    elif fid == 0x550:
        values = {'coolant_bars_candidate': data[0] & 0x7, 'warning_light': bool((data[0] >> 3) & 1)}
    elif fid == 0x570:
        values = {'coolant_c_candidate': (((data[2] << 8) | data[3]) / 10.0)}
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
