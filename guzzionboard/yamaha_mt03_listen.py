"""Source-scoped Yamaha MT-03 2010 receive-only serial observation.

Checksum stream framing and RPM formula adapted from smiddelkoop/
Yamaha-kline-ubuntu commit 0f7fef82d1987923198b53ffa001d09ed1ceae4e,
Copyright (c) 2026 Sven Middelkoop, MIT; see LICENSES/Yamaha-KLine-Ubuntu-MIT.txt.
Source credits terrafirma2021's Yamaha K-Line Tool and Sniffer. No ECU request,
initialization, write, immobilizer action, fault-code inference or memory access.
A checksum match is not proof of frame alignment or vehicle fitment.
"""
from __future__ import annotations

import os
import re
import sys
import time

from .transports.base import TransportError, TransportUnavailable

BAUD = 16064
DURATION = 2.0
MAX_BYTES = 65536


class FrameSync:
    """Bounded sliding checksum synchronizer; matches may be false positives."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        output = []
        while len(self.buffer) >= 5:
            b = self.buffer
            if b[0] == 1 and len(b) >= 6 and sum(b[1:5]) & 0xff == b[5]:
                output.append(bytes(b[:6])); del b[:6]
            elif sum(b[:4]) & 0xff == b[4]:
                output.append(bytes(b[:5])); del b[:5]
            elif b[0] == 1 and len(b) < 6:
                break
            else:
                del b[0]
        return output


def decode(frame: bytes) -> dict | None:
    if len(frame) == 6 and frame[0] == 1:
        data = frame[1:]
    elif len(frame) == 5:
        data = frame
    else:
        return None
    if sum(data[:4]) & 0xff != data[4]:
        return None
    # Source excludes uniform payload and RPM > 9000 as likely non-telemetry;
    # it does not prove that remaining checksum-valid bytes are true telemetry.
    if len(set(data[:4])) == 1 or data[0] * 50 > 9000:
        return None
    return {'raw': frame.hex().upper(), 'rpm_candidate': data[0] * 50,
            'speed_byte_raw': data[1], 'status_byte_raw': data[2],
            'temperature_byte_raw': data[3], 'temperature_ff_unavailable_candidate': data[3] == 0xff}


def listen(port: str) -> dict:
    if not sys.platform.startswith('linux'):
        raise TransportUnavailable('Yamaha observation currently supports Linux FTDI KKL interfaces only.')
    if not isinstance(port, str) or len(port) > 255 or '\x00' in port:
        raise ValueError('Select an explicit Linux FTDI /dev/ttyUSB device.')
    device = os.path.realpath(port)
    if not re.fullmatch(r'/dev/ttyUSB[0-9]+', device):
        raise ValueError('Select an explicit Linux FTDI /dev/ttyUSB device (or a symlink to one).')
    try:
        import serial
    except ImportError as exc:
        raise TransportUnavailable('pyserial is not installed; install the hardware extra.') from exc
    try:
        connection = serial.Serial(port=device, baudrate=BAUD, bytesize=serial.EIGHTBITS,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                   timeout=0.05, exclusive=True)
    except (serial.SerialException, ValueError, OSError) as exc:
        raise TransportError(f'Cannot open {device} at {BAUD} baud: {exc}') from exc
    sync = FrameSync()
    latest = None
    count = total = 0
    started = time.monotonic()
    try:
        while total < MAX_BYTES and time.monotonic() < started + DURATION:
            chunk = connection.read(min(max(connection.in_waiting, 1), 4096, MAX_BYTES - total))
            if not chunk:
                continue
            total += len(chunk)
            for frame in sync.feed(chunk):
                candidate = decode(frame)
                if candidate is not None:
                    latest = candidate
                    count += 1
    except (serial.SerialException, OSError) as exc:
        raise TransportError(f'Yamaha serial observation failed: {exc}') from exc
    finally:
        connection.close()
    return {'port': device, 'duration_seconds': DURATION, 'bytes_received': total,
            'candidate_frames': count, 'byte_limit_reached': total >= MAX_BYTES, 'latest': latest,
            'note': 'Checksum-based synchronization is heuristic; candidate values are not verified ECU data. No request bytes are sent by this application.'}
