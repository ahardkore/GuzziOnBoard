"""Read-only KDS/SDS exchanges from aster94/Keyword-Protocol-2000.

Copyright (c) Aster94. Source files carry an MIT notice; repository is GPL-3.0.
Pinned revision 94c4ff0675cc24d7b21c98da0fca2d14b892d5f3.
See LICENSES/Keyword-Protocol-2000-source-MIT.txt and
LICENSES/Keyword-Protocol-2000-GPL-3.0.txt and research notes. The
upstream reports testing 2012 Versys 650 and 2011 GSX-R600. This adaptation
has synthetic tests only; sensor conversions are source-reported candidates.
"""
from __future__ import annotations

import time
from .kwp2000 import KWP2000Session, ProtocolError, NegativeResponse, checksum, decode_frame


class AsterKLineSession(KWP2000Session):
    target = None
    allowed = frozenset()

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        if payload not in self.allowed:
            raise PermissionError('Source-scoped K-Line read-only session refuses this request')
        body = bytes([0x80, self.target, 0xF1, len(payload)]) + payload
        frame = body + bytes([checksum(body)])
        time.sleep(0.055)
        self._log('tx', frame)
        self.connection.write(frame)
        reply = self.connection.read_frame(2.0 if timeout is None else timeout)
        if not reply:
            raise ProtocolError('Source-scoped K-Line response timed out')
        self._log('rx', reply)
        result = decode_frame(reply)
        if result.source != self.target or result.target != 0xF1:
            raise ProtocolError('K-Line response address mismatch')
        if result.is_negative:
            if len(result.payload) != 3 or result.payload[1] != payload[0]:
                raise ProtocolError('Malformed or mismatched negative response')
            raise NegativeResponse(result.payload[1], result.payload[2])
        if payload == b'\x10\x80':
            if result.payload != b'\x50\x80':
                raise ProtocolError('KDS session start mismatch')
        elif payload == b'\x3e\x01':
            if result.payload != b'\x7e\x01':
                raise ProtocolError('SDS tester-present response mismatch')
        elif result.payload[:2] != bytes([0x61, payload[1]]):
            raise ProtocolError('Sensor response service or identifier mismatch')
        else:
            # Upstream sensor offsets are based on explicitly length-prefixed replies.
            if result.format_byte != 0x80:
                raise ProtocolError('Expected extended-length addressed sensor response')
            self.validate_data(payload[1], result.payload[2:])
        return result


class Versys2012Session(AsterKLineSession):
    target = 0x11
    SIZES = {0x04: (1, 2), 0x05: (1,), 0x06: (1,), 0x07: (1,),
             0x09: (2,), 0x0b: (1,), 0x0c: (1, 2)}
    allowed = frozenset([b'\x10\x80'] + [bytes([0x21, pid]) for pid in SIZES])

    def validate_data(self, pid, data):
        if len(data) not in self.SIZES[pid]:
            raise ProtocolError('Versys KDS response data length mismatch')

    def tester_present(self):
        return self.request(b'\x21\x0b')


class KawasakiKdsResearchSession(Versys2012Session):
    """Raw KDS attempts on separately source-listed model/year selections.

    The fitment vendor does not specify these frames; they are adapted from
    the Aster94 2012 Versys source and may not work on a selected ECU.
    """
    def read_raw(self, pid):
        if pid not in self.SIZES:
            raise PermissionError("KDS identifier is not allowlisted")
        return self.request(bytes([0x21, pid])).payload[2:]

    def tester_present(self):
        return self.request(b'\x21\x09')


def decode_versys(pid, raw):
    if pid == 9:
        return (raw[0] * 255 + raw[1]) * 100 / 255
    if pid in (5, 6):
        return (raw[0] - 48) / 1.6
    if pid == 7:
        return raw[0] * 4 * 0.136
    return raw[0]


class Gsxr6002011Session(AsterKLineSession):
    target = 0x12
    allowed = frozenset((b'\x21\x08', b'\x3e\x01'))
    # Raw reply offsets from upstream translated to data offsets after 61 08.
    FIELDS = {'rpm': (11, 2), 'speed': (10, 1), 'tps': (13, 1), 'map': (14, 1),
              'coolant': (15, 1), 'airtemp': (16, 1), 'gear': (20, 1), 'battery_raw': (18, 1)}

    def validate_data(self, pid, data):
        if len(data) != 50:
            raise ProtocolError('GSX-R SDS all-sensors response must contain 50 data bytes')

    def read_snapshot(self):
        data = self.request(b'\x21\x08').payload[2:]
        return {key: data[offset:offset + length] for key, (offset, length) in self.FIELDS.items()}

    def tester_present(self):
        return self.request(b'\x3e\x01')


def decode_gsxr(key, raw):
    a = raw[0]
    if key == 'rpm':
        return a * 10 + raw[1] / 10
    if key == 'speed':
        return a * 2
    if key == 'tps':
        return 125 * (a - 55) / 201
    if key == 'map':
        return a * 4 * 0.136
    if key in ('coolant', 'airtemp'):
        return (a - 48) / 1.6
    if key == 'battery_raw':
        return a  # Source labels a*100/126 as voltage; expose raw until units are clear.
    return a


class Gsxr10002004Session(AsterKLineSession):
    """2004 GSX-R1000 SDS diagnostic snapshot attempt, raw bytes only.

    Request/target facts described in uronour/suzuki-Kawasaki-ecu-tool,
    revision 4f92cc2adab254595b08c21e2c90b4c57d2e9cc6. The source reserves
    all rights: no upstream code or captured data is copied. Its 2004 sensor
    offset references are internally inconsistent, so no values are decoded.
    This integration has not been tested on a physical ECU.
    """
    target = 0x12
    allowed = frozenset((b'\x21\x08',))

    def validate_data(self, pid, data):
        if pid != 0x08 or not 1 <= len(data) <= 60:
            raise ProtocolError('GSX-R1000 raw snapshot length is outside bounds')

    def read_snapshot(self):
        return self.request(b'\x21\x08').payload[2:]

    def tester_present(self):
        return self.request(b'\x21\x08')


class SuzukiGsxrResearchSession(Gsxr10002004Session):
    """Raw SDS attempt for AiM-listed GSX-R and Hayabusa models.

    AiM lists SDS fitment but does not document this exact request or the
    response shape for each model; those come from separate Suzuki sources.
    This integration and cross-model compatibility have synthetic tests only.
    """
    def validate_data(self, pid, data):
        if pid != 0x08 or len(data) != 50:
            raise ProtocolError('SDS all-sensors response must contain 50 data bytes')


class Sv6502003Session(Gsxr10002004Session):
    """Raw 03–05 SV650 SDS; source capture 32920-17G2, GPL-3.0.

    synfinatic/sv650sds revision bacf803a9056241ef270acf0e7e31467961aeba5.
    This integration is not hardware-tested; no 2007 decoder is applied.
    """
    def request(self, payload, *, timeout=None):
        if bytes(payload) not in self.allowed:
            raise PermissionError("SV650 session allows only the all-sensors read")
        time.sleep(0.2)
        return super().request(payload, timeout=timeout)

    def validate_data(self, pid, data):
        if pid != 0x08 or len(data) != 50:
            raise ProtocolError('SV650 SDS all-sensors response must contain 50 data bytes')


class Sv650Ak7Session(AsterKLineSession):
    """Read-only 2007 SV650AK7 SDS, adapted from SV650overlay GPL-3.0.

    BananaJoh/sv650overlay revision cc80f0d35abd60255bbcd74cdddef515ed4945ce;
    see LICENSES/SV650overlay-GPL-3.0.txt. No GuzziOnBoard hardware test.
    """
    target = 0x12
    allowed = frozenset((b'\x21\x08',))
    FIELDS = {'rpm': (11, 1), 'tps': (13, 1), 'coolant': (15, 1),
              'airtemp': (16, 1), 'battery': (18, 1), 'gear_status': (20, 1)}

    def request(self, payload, *, timeout=None):
        if bytes(payload) not in self.allowed:
            raise PermissionError("SV650AK7 session allows only the all-sensors read")
        # Source waits at least 200 ms after each frame; unlike the source,
        # never retry or automatically reinitialize after a failure.
        time.sleep(0.2)
        return super().request(payload, timeout=timeout)

    def validate_data(self, pid, data):
        if pid != 0x08 or len(data) != 50:
            raise ProtocolError('SV650AK7 SDS all-sensors response must contain 50 data bytes')

    def read_snapshot(self):
        data = self.request(b'\x21\x08').payload[2:]
        return {key: data[offset:offset + length] for key, (offset, length) in self.FIELDS.items()}

    def tester_present(self):
        return self.request(b'\x21\x08')


def decode_sv650ak7(key, raw):
    value = raw[0]
    if key == 'rpm': return value * 69 // 10 * 10
    if key == 'tps': return int((value - 58) * 6 / 10)
    if key in ('coolant', 'airtemp'): return value - 40
    if key == 'battery': return (value + 109) * 5 / 100 if value else 0
    return value
