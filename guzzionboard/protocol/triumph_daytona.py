"""2012 Daytona 675 read-only ISO 9141/OBD; adapted from daytona-kline.

Copyright (C) 2026 Andrew Wilke; GPL-3.0-or-later. See
LICENSES/Daytona-Kline-GPL-3.0.txt and docs/EXTERNAL_MOTORCYCLE_RESEARCH.md.
The source reports one tested motorcycle. This implementation uses synthetic
fixtures only; its gauge formulas were not compared with the bike's dash.
"""
from __future__ import annotations

import time
from .kwp2000 import KWP2000Session, NegativeResponse, ProtocolError, checksum


class TriumphDaytonaSession(KWP2000Session):
    # SAE mode 01, source's non-unlock gauge set. 00 is the support bitmap.
    LENGTHS = {0x00: 4, 0x01: 4, 0x04: 1, 0x05: 1, 0x06: 1, 0x0B: 1,
               0x0C: 2, 0x0D: 1, 0x0E: 1, 0x0F: 1, 0x11: 1}
    supported: set[int] | None = None

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        if not (payload == b'\x03' or len(payload) == 2 and payload[0] == 1 and payload[1] in self.LENGTHS):
            raise PermissionError('Daytona read-only ISO session refuses this request')
        if (len(payload) == 2 and payload[1] not in (0, 1) and self.supported is not None
                and payload[1] not in self.supported):
            raise ProtocolError(f'ECU support bitmap does not list PID 0x{payload[1]:02X}')
        data = bytes([0x68, 0x6a, 0xf1]) + payload
        raw = data + bytes([checksum(data)])
        time.sleep(0.060)
        self._log('tx', raw)
        self.connection.write(raw)
        burst = self.connection.read_iso9141_burst(0.8 if timeout is None else timeout)
        if not burst:
            raise ProtocolError('Daytona ISO 9141 response timed out')
        self._log('rx', burst)
        frames = parse_iso_burst(burst)
        for frame in frames:
            if len(frame) >= 3 and frame[0] == 0x7f:
                raise NegativeResponse(frame[1], frame[2])
            if not frame or frame[0] != (payload[0] | 0x40):
                raise ProtocolError('Daytona ISO 9141 response service mismatch')
            if payload[0] == 1 and (len(frame) != 2 + self.LENGTHS[payload[1]] or frame[1] != payload[1]):
                raise ProtocolError('Daytona PID response identifier or length mismatch')
            if payload[0] == 3 and (len(frame) < 3 or (len(frame) - 1) % 2):
                raise ProtocolError('Daytona DTC response has a partial code')
        return frames

    def initialise(self):
        frames = self.request([1, 0])
        if len(frames) != 1:
            raise ProtocolError('Daytona support bitmap must have one response')
        bitmap = frames[0][2:]
        self.supported = {i + 1 for i in range(32) if bitmap[i // 8] & (0x80 >> (i % 8))}

    def read_data_by_local_id(self, local_id):
        frames = self.request([1, local_id])
        if len(frames) != 1:
            raise ProtocolError('Daytona PID yielded multiple responses')
        return frames[0][2:]

    def tester_present(self):
        return self.request([1, 0])

    def read_stored_codes(self):
        frames = self.request([3])
        codes = []
        for frame in frames:
            for index in range(1, len(frame), 2):
                a, b = frame[index:index + 2]
                if not (a or b):
                    continue
                code = f"{'PCBU'[a >> 6]}{(a >> 4) & 3}{a & 15:X}{b:02X}"
                codes.append({'code': code, 'description': '', 'status_byte': None,
                              'kind': 'OBD stored', 'status': 'stored', 'warning_indicator': False})
        return codes


def parse_iso_burst(raw: bytes) -> list[bytes]:
    """Split checksum-delimited frames at reply headers, rejecting bad bursts."""
    raw = bytes(raw)
    if not raw or len(raw) > 512:
        raise ProtocolError('Invalid ISO 9141 response burst')
    frames, start = [], 0
    header = b'\x48\x6b\xd1'
    while start < len(raw):
        if raw[start:start + 3] != header:
            raise ProtocolError('Unexpected ISO 9141 reply header')
        end = None
        for candidate in range(start + 5, len(raw) + 1):
            if candidate < len(raw) and raw[candidate:candidate + 3] != header:
                continue
            if checksum(raw[start:candidate - 1]) == raw[candidate - 1]:
                end = candidate
                break
        if end is None:
            raise ProtocolError('ISO 9141 checksum mismatch or truncated burst')
        frames.append(raw[start + 3:end - 1])
        start = end
    return frames
