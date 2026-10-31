"""Bounded receive-only SocketCAN observation of candidate motorcycle CAN frames.

Decoding uses the separately attributed HarleyDroid EVO, Sportster and Ducati
Mitsubishi community maps. This module never sends CAN frames; a normal CAN controller can still ACK traffic.
It does not identify a bike or establish the integrity of CAN broadcasts.
"""
from __future__ import annotations

import re
import time

from .canlog import CanFrame
from .harley_hdlan_can import MIN_LENGTH, decode_capture
from .ducati_panigale_can import decode_capture as decode_ducati
from .yamaha_r9_can import FRAME_LENGTHS as R9_LENGTH, decode_capture as decode_r9
from .indian_springfield_can import FILTER_IDS as INDIAN_IDS, MASK as INDIAN_MASK, decode_capture as decode_indian
from .transports.can import _require_can
from .transports.base import TransportError

DURATION = 2.0
MAX_FRAMES = 10000
DUCATI_LENGTH = {0x18: 6, 0x80: 7, 0x100: 6}
SPORTSTER_LENGTH = {0x550: (6, 8), 0x544: (8,), 0x542: (8,), 0x530: (8,)}


def decode_sportster(frames):
    """2017 XL1200X raw observations, from earnaz/Harley-Davidson-CAN-Bus.

    Copyright (c) 2023 Chrisisbrown, MIT; see LICENSES/Harley-Sportster-CAN-MIT.txt.
    The source reports observations, not complete switch bit or voltage scaling.
    """
    events = []
    for frame in frames:
        data = frame.data
        if frame.id == 0x550:
            values = {"switch_byte0_raw": data[0],
                      "high_beam_0x08_candidate": True if data[0] == 8 else None}
        elif frame.id == 0x542:
            values = {"stand_byte0_raw": data[0],
                      "jiffy_stand_candidate": "up" if data[0] == 0 else "down" if data[0] == 0x30 else None}
        elif frame.id == 0x544:
            values = {"throttle_frame_byte0_raw": data[0]}
        else:
            values = {"battery_frame_byte5_raw": data[5], "neutral_status_byte2_raw": data[2],
                      "neutral_0x81_candidate": True if data[2] == 0x81 else None}
        events.append({"timestamp": frame.timestamp, "id": f"0x{frame.id:X}",
                       "direction": "Rx", "raw": data.hex().upper(), "values": values})
    return events


def listen(channel: str, profile: str = "community") -> dict:
    if not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', channel):
        raise ValueError('Enter a valid existing SocketCAN interface name (1–15 characters).')
    if profile not in ('community', 'sportster_2017', 'ducati_mitsubishi', 'yamaha_r9_2026', 'indian_springfield_2017'):
        raise ValueError('Unknown CAN observation profile.')
    filters = {'community': MIN_LENGTH, 'ducati_mitsubishi': DUCATI_LENGTH,
               'sportster_2017': SPORTSTER_LENGTH, 'yamaha_r9_2026': R9_LENGTH,
               'indian_springfield_2017': INDIAN_IDS}[profile]
    can = _require_can()
    try:
        # SocketCAN bitrate and controller listen-only mode must already be
        # configured by the OS/operator. Do not configure or transmit here.
        bus = can.interface.Bus(interface='socketcan', channel=channel,
                                can_filters=[{'can_id': i, 'can_mask': INDIAN_MASK if profile == 'indian_springfield_2017' else 0x7ff,
                                              'extended': profile == 'indian_springfield_2017'} for i in filters])
    except Exception as exc:
        raise TransportError(f'Cannot open SocketCAN interface {channel}: {exc}') from exc
    latest: dict[int, CanFrame] = {}
    count = invalid = 0
    started = time.monotonic()
    try:
        while count < MAX_FRAMES:
            remaining = started + DURATION - time.monotonic()
            if remaining <= 0:
                break
            msg = bus.recv(timeout=remaining)
            if msg is None:
                break
            count += 1
            if ((bool(getattr(msg, 'is_extended_id', False)) != (profile == 'indian_springfield_2017'))
                    or getattr(msg, 'is_remote_frame', False) or getattr(msg, 'is_error_frame', False)
                    or getattr(msg, 'is_fd', False) or getattr(msg, 'is_rx', True) is False
                    or ((msg.arbitration_id & INDIAN_MASK) if profile == 'indian_springfield_2017' else msg.arbitration_id) not in filters):
                continue
            data = bytes(msg.data)
            valid_length = (len(data) == 8 if profile == 'indian_springfield_2017'
                            else len(data) in SPORTSTER_LENGTH[msg.arbitration_id] if profile == 'sportster_2017'
                            else len(data) == R9_LENGTH[msg.arbitration_id] if profile == 'yamaha_r9_2026'
                            else filters[msg.arbitration_id] <= len(data) <= 8)
            if not valid_length:
                invalid += 1
                continue
            latest[msg.arbitration_id] = CanFrame(float(getattr(msg, 'timestamp', 0.0)),
                                                   msg.arbitration_id, profile == 'indian_springfield_2017', data, 'Rx')
    except Exception as exc:
        raise TransportError(f'SocketCAN receive failed: {exc}') from exc
    finally:
        bus.shutdown()
    events = (decode_capture(latest.values())['events'] if profile == 'community'
              else decode_ducati(latest.values())['events'] if profile == 'ducati_mitsubishi'
              else decode_r9(latest.values())['events'] if profile == 'yamaha_r9_2026'
              else decode_indian(latest.values()) if profile == 'indian_springfield_2017'
              else decode_sportster(latest.values()))
    return {'channel': channel, 'profile': profile, 'duration_seconds': DURATION, 'frames_received': count,
            'invalid_length_frames': invalid, 'frame_limit_reached': count >= MAX_FRAMES,
            'events': events,
            'note': 'Candidate source mappings only; not an ECU response, bike identification or safety measurement. No CAN frames were sent by this application. A normal controller may still acknowledge bus traffic.'}
