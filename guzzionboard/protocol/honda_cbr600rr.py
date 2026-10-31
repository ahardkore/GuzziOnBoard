"""2005 CBR600RR Honda K-Line table polling.

Adapted from Honda ECU Manager, Copyright (C) 2025 andreibaw,
GPL-3.0-or-later, revision f3bd42ff438e840e4da3802dd5038a195f3d67be.
See LICENSES/Honda-KLine-GPL-3.0.txt. Synthetic tests only, no bike test.
This is a live diagnostic table, not an ECU flash-memory dump.
"""
from __future__ import annotations

from .kwp2000 import KWP2000Session, ProtocolError


def read_honda_frame(connection, timeout: float) -> bytes:
    header = connection.read_bytes(2, timeout)
    if len(header) != 2:
        raise ProtocolError('Honda response header timed out or is truncated')
    length = header[1]
    if not 3 <= length <= 64:
        raise ProtocolError('Honda response length outside allowed range')
    body = connection.read_bytes(length - 2, timeout)
    if len(body) != length - 2:
        raise ProtocolError('Honda response body timed out or is truncated')
    frame = header + body
    if sum(frame) & 0xFF:
        raise ProtocolError('Honda response checksum mismatch')
    return frame


class HondaCBR600RRSession(KWP2000Session):
    FIELDS = {'rpm': (0, 2), 'tps': (3, 1), 'coolant': (5, 1),
              'airtemp': (7, 1), 'map': (9, 1), 'battery': (12, 1),
              'speed': (13, 1)}
    STATUS_FIELDS = {'gear_status': (0, 1), 'engine_status': (4, 1)}
    TABLE_LENGTHS = {0x00: None, 0x10: 22, 0xD1: 10}
    SENSOR_TABLE = 0x10

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        if len(payload) != 2 or payload[0] != 0x71 or payload[1] not in self.TABLE_LENGTHS:
            raise PermissionError('Honda read-only session refuses this request')
        table = payload[1]
        body = bytes([0x72, 0x05, 0x71, table])
        request = body + bytes([(-sum(body)) & 255])
        self._log('tx', request)
        self.connection.write(request)
        result = read_honda_frame(self.connection, 1.0 if timeout is None else timeout)
        self._log('rx', result)
        length = self.TABLE_LENGTHS[table]
        if (result[0] != 0x02 or result[2:4] != bytes([0x71, table])
                or (length is None and len(result) < 10)
                or (length is not None and len(result) != length)):
            raise ProtocolError('Honda table response header or length mismatch')
        return result

    def read_identity_candidate(self):
        # HondaECU source takes five bytes after the 71 00 response prefix.
        return self.request(b"\x71\x00")[4:9]

    def read_snapshot(self, table=None):
        if table is None:
            table = self.SENSOR_TABLE
        if table not in (self.SENSOR_TABLE, 0xD1):
            raise PermissionError('Honda live table is not allowlisted')
        data = self.request(bytes([0x71, table]))[4:-1]
        fields = self.FIELDS if table == self.SENSOR_TABLE else self.STATUS_FIELDS
        return {key: data[offset:offset + size] for key, (offset, size) in fields.items()}

    def tester_present(self):
        return self.request(bytes([0x71, self.SENSOR_TABLE]))


def decode_honda(key: str, raw: bytes) -> float:
    if key == 'rpm':
        return raw[0] * 256 + raw[1]
    if key == 'tps':
        return raw[0] * 10 / 16
    if key in ('coolant', 'airtemp'):
        return raw[0] - 40
    if key == 'battery':
        return raw[0] / 10
    return raw[0]


class HondaCB500FDashSession(HondaCBR600RRSession):
    """Source-reported CB500F, year/ECU unspecified; synthetic tests only.

    DashBle and Dash, copyright 2018 atoid, MIT, revisions
    9c65818d13dde39b8d8203736b43109eb84a9651 and
    532d0f4fef1b2e11a15f1c6663fb5351757f87b8.
    License: LICENSES/DashBle-MIT.txt.
    """
    TABLE_LENGTHS = {0x00: None, 0x11: 25, 0xD1: 11}
    SENSOR_TABLE = 0x11
    FIELDS = {'rpm': (0, 2), 'tps_raw': (3, 1), 'coolant': (5, 1),
              'airtemp': (7, 1), 'map': (9, 1), 'battery': (12, 1), 'speed': (13, 1)}

class HondaCTX700Session(HondaCBR600RRSession):
    """CTX700 tables, adapted from seife/honda-ecu-minidash (MIT).

    Revision 01610247, copyright 2026 Stefan Seyfried; see
    LICENSES/Honda-ECU-Minidash-MIT.txt. Source does not state year/ECU.
    This adaptation is synthetic-tested only; data and units are candidates.
    """
    TABLE_LENGTHS = {0x11: 25, 0xD1: 11}
    SENSOR_TABLE = 0x11
    FIELDS = {'rpm': (0, 2), 'tps_ctx': (3, 1), 'coolant': (5, 1),
              'airtemp': (7, 1), 'map': (9, 1), 'battery': (12, 1),
              'speed': (13, 1), 'injector_raw': (14, 2)}


def decode_honda_ctx(key, raw):
    if key == 'tps_ctx':
        return raw[0] / 16
    if key == 'injector_raw':
        return int.from_bytes(raw, 'big')
    return decode_honda(key, raw)


# Source-scoped, experimental MGZ-A03 image read. These constants come from
# HondaECU's ECM ID table and a 256 KiB source image, not from this project
# testing a physical ECU. The security/read framing follows WiseNoodle's
# honda-moto-ecu-suite and PhatDatPQ/eculib. See the accompanying licenses
# and research documentation. This code cannot send arbitrary addresses or
# expose a write/erase command.
MGZ_A03_ECM_ID = bytes.fromhex('01 01 25 05 01')
MGZ_A03_IMAGE_SIZE = 0x40000
MGZ_A03_ECM_ID_OFFSET = 0x17FC7


def _honda_security_step(connection, data, log):
    body = bytes([0x27, len(data) + 3]) + data
    message = body + bytes([(-sum(body)) & 0xff])
    log('tx', message)
    connection.write(message)
    reply = read_honda_frame(connection, 1.0)
    log('rx', reply)
    if reply[0] != 0x07:
        raise ProtocolError('Honda read security exchange was rejected or malformed; do not retry automatically')


def _honda_read_block(connection, address, size, log):
    if not (0 <= address < MGZ_A03_IMAGE_SIZE and 1 <= size <= 12
            and address + size <= MGZ_A03_IMAGE_SIZE):
        raise PermissionError('Honda read address outside the fixed MGZ-A03 image')
    # Honda uses address bytes high, low, middle rather than big endian.
    body = bytes([0x82, 0x82, 0x00, 0x09,
                  (address >> 16) & 0xff, address & 0xff, (address >> 8) & 0xff, size])
    request = body + bytes([(-sum(body)) & 0xff])
    log('tx', request)
    connection.write(request)
    head = connection.read_bytes(4, 1.0)
    if len(head) != 4 or head[:2] != b'\x92\x92' or head[3] != size + 5:
        raise ProtocolError('Honda flash-read reply header or length mismatch')
    tail = connection.read_bytes(size + 1, 1.0)
    response = head + tail
    log('rx', response)
    if len(tail) != size + 1 or sum(response) & 0xff:
        raise ProtocolError('Honda flash-read reply truncated or checksum mismatch')
    return tail[:-1]


def read_mgz_a03_research_image(session: HondaCB500FDashSession, progress=None) -> bytes:
    """Read the fixed image, failing closed; caller must hold the session lock.

    This is not a verified backup or proof that every ECU byte was acquired.
    There are no retries, writes, erases, arbitrary addresses or fallback probes.
    """
    if type(session) is not HondaCB500FDashSession:
        raise PermissionError('MGZ-A03 read requires the CB500F DashBle session')
    if session.read_identity_candidate() != MGZ_A03_ECM_ID:
        raise ProtocolError('Live ECM ID does not match the source-reported MGZ-A03 ID')
    _honda_security_step(session.connection, b'\xe0HelloHo', session._log)
    _honda_security_step(session.connection, b'\xe0wAreYou', session._log)
    output = bytearray()
    while len(output) < MGZ_A03_IMAGE_SIZE:
        offset = len(output)
        size = min(12, MGZ_A03_IMAGE_SIZE - offset)
        output.extend(_honda_read_block(session.connection, offset, size, session._log))
        if progress:
            progress(len(output), MGZ_A03_IMAGE_SIZE)
    if output[MGZ_A03_ECM_ID_OFFSET:MGZ_A03_ECM_ID_OFFSET + 5] != MGZ_A03_ECM_ID:
        raise ProtocolError('Read image ECM ID bytes do not match the source-reported offset')
    if sum(output) & 0xff:
        raise ProtocolError('Read image fails the source-reported whole-image checksum')
    return bytes(output)
