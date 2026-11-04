"""Marelli IAW 59M broadcast CAN candidates (Ducati 998/999 CAN-output mod).

Signal layout reimplemented from the DBC at
billyjack2/CAN-DBC-Collection, path DUCATI/Marelli_IAW59M_C/can1v3.dbc,
commit 6e2f88fd6cd9c1f47d0db7bd022711b106f27027. That collection ships no
root license, so the facts are reimplemented here and only cited, not copied
(see docs/CAPTURE_SEARCH_2026-11-03.md). This is the *broadcast* bus the 59M
can be modded to emit - it is NOT the K-Line diagnostic session, so it does
not unlock the `59m` profile's physical session. Synthetic tests only;
ID match or decoding does not identify a vehicle.

DBC messages (8-byte frames, 11-bit IDs):

* 0x020: IntakeAirTemp, byte 0, raw - 40 in °C
* 0x100: Neutral bits 5-7; Speed bits 8-18 (raw * 0.25 km/h);
         RPM bits 32-47 (raw rpm); OilLight byte 5
* 0x200: WaterTemp byte 0 (raw - 40 °C); VBatt byte 1 (raw * 100 mV)
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'marelli_iaw59m_can_broadcast'

FRAME_LENGTHS = {0x020: 8, 0x100: 8, 0x200: 8}
MAX_EVENTS = 200


def _u(raw: bytes, bit_start: int, bits: int) -> int:
    """Little-endian (Intel) unsigned field, as DBC @1+ signals use."""
    value = 0
    for i in range(bits):
        pos = bit_start + i
        if raw[pos // 8] & (1 << (pos % 8)):
            value |= 1 << i
    return value


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in FRAME_LENGTHS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        data = frame.data
        if len(data) != FRAME_LENGTHS[frame.id]:
            invalid += 1
            continue
        if frame.id == 0x020:
            values = {'intake_air_temp_c_candidate': data[0] - 40}
        elif frame.id == 0x100:
            values = {'neutral_raw_candidate': _u(data, 5, 3),
                      'speed_kmh_candidate': round(_u(data, 8, 11) * 0.25, 2),
                      'rpm_candidate': _u(data, 32, 16),
                      'oil_light_raw_candidate': data[5]}
        else:
            values = {'water_temp_c_candidate': data[0] - 40,
                      'vbatt_mv_candidate': data[1] * 100}
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({'timestamp': frame.timestamp, 'id': f'0x{frame.id:X}',
                           'direction': frame.direction or 'unknown', 'raw': data.hex().upper(),
                           'values': values})
    return {'profile': PROFILE, 'events': events, 'recognized_frames': recognized,
            'invalid_length_frames': invalid, 'ignored_tx_frames': ignored_tx,
            'omitted_events': max(0, recognized - len(events))}
