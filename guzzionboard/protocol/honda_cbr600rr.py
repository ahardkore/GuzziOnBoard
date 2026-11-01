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


# Source-scoped, experimental Honda image reads. These constants come from
# HondaECU's ECM ID table and example images, not from this project
# testing a physical ECU. The security/read framing follows WiseNoodle's
# honda-moto-ecu-suite and PhatDatPQ/eculib. See the accompanying licenses
# and research documentation. This code cannot send arbitrary addresses or
# expose a write/erase command.
MGZ_A03_ECM_ID = bytes.fromhex('01 01 25 05 01')
MGZ_ECM_IDS = {
    MGZ_A03_ECM_ID: '38770-MGZ-A03',
    bytes.fromhex('01 01 25 0b 01'): '38770-MGZ-C02',
    bytes.fromhex('01 01 25 0b 02'): '38770-MGZ-C03',
    bytes.fromhex('01 01 25 01 01'): '38770-MGZ-D02',
}
MGZ_A03_IMAGE_SIZE = 0x40000
HONDA_RESEARCH_MAX_END = 0x100000
MGZ_A03_ECM_ID_OFFSET = 0x17FC7

# Most source-named samples have the stated ID at the observed offset and a
# zero 8-bit file sum. Two table-only entries have no independently checked
# examples; sizes derive from source model descriptions. These observations
# do not verify the read path or prove complete memory.
HONDA_RESEARCH_LAYOUTS = {
    **{key: (part, MGZ_A03_ECM_ID_OFFSET) for key, part in MGZ_ECM_IDS.items()},
    bytes.fromhex('01 00 2b 01 01'): ('38770-MEL-D21', 0x23381),
    bytes.fromhex('01 00 2b 03 01'): ('38770-MEL-F21', 0x23381),
    bytes.fromhex('01 00 2b 04 01'): ('38770-MEL-A21', 0x23381),
    bytes.fromhex('01 00 2b 04 02'): ('38770-MEL-A22', 0x23381),
    bytes.fromhex('01 00 2b 05 02'): ('38770-MEL-L22', 0x23381),
    # The following MFL/MGP ID offsets are inferred from the corresponding
    # source-named example images, not specified in the source ID table.
    bytes.fromhex('01 00 5e 03 01'): ('38770-MFL-622', 0x2880A),
    bytes.fromhex('01 00 5e 01 03'): ('38770-MFL-644', 0x2880A),
    bytes.fromhex('01 00 5e 04 01'): ('38770-MFL-671', 0x2880A),
    # This association is commented out upstream; the named example matches.
    bytes.fromhex('01 00 5e 05 03'): ('38770-MFL-773', 0x2880A),
    bytes.fromhex('01 00 b0 03 01'): ('38770-MFL-741', 0x2880A),
    bytes.fromhex('01 00 b0 01 02'): ('38770-MFL-761', 0x2880A),
    bytes.fromhex('01 00 b7 04 01'): ('38770-MFL-A21', 0x2880A),
    bytes.fromhex('01 00 b7 01 01'): ('38770-MFL-D21', 0x2880A),
    # These five associations use IDs at the family offset in named examples,
    # and differ from (or are absent from) the source ID table.
    bytes.fromhex('01 00 b0 04 01'): ('38770-MFL-691', 0x2880A),
    bytes.fromhex('01 00 b0 05 01'): ('38770-MFL-861', 0x2880A),
    bytes.fromhex('01 00 b0 08 01'): ('38770-MFL-871', 0x2880A),
    bytes.fromhex('01 00 b7 03 01'): ('38770-MFL-F21', 0x2880A),
    bytes.fromhex('01 00 b7 05 01'): ('38770-MFL-L21', 0x2880A),
    bytes.fromhex('01 00 f3 01 01'): ('38770-MGP-D01', 0x29089),
    bytes.fromhex('01 00 f3 03 01'): ('38770-MGP-F01', 0x29089),
    bytes.fromhex('01 00 f3 04 01'): ('38770-MGP-A01', 0x29089),
    bytes.fromhex('01 00 f3 05 01'): ('38770-MGP-L01', 0x29089),
    bytes.fromhex('01 01 83 01 01'): ('38770-MGP-D62', 0x26215),
    bytes.fromhex('01 01 83 03 02'): ('38770-MGP-F63', 0x26215),
    bytes.fromhex('01 01 83 04 01'): ('38770-MGP-A92', 0x26215),
    # 1 MiB examples: ID positions are observed in source-named files.
    bytes.fromhex('01 02 49 01 01'): ('38770-MKF-D43', 0x7C745),
    # MKF-L13 source table says 0102490501; its named example contains
    # 0102480501 at the D43 family offset. Preserve both as candidates.
    bytes.fromhex('01 02 48 05 01'): ('38770-MKF-L13', 0x7C745),
    bytes.fromhex('01 02 49 05 01'): ('38770-MKF-L13', 0x7C745),
    bytes.fromhex('01 00 aa 05 01'): ('38770-MGE-773', 0x36B57),
    bytes.fromhex('01 00 aa 06 01'): ('38770-MGE-701', 0x36B7F),
    bytes.fromhex('48 01 01 19 01'): ('38770-MGE-D41', 0x3A563),
    # Source table says MNF; its matching example filenames say MFN.
    bytes.fromhex('01 00 6a 03 01'): ('38770-MNF-F01', 0x21C92),
    bytes.fromhex('01 00 6a 01 01'): ('38770-MNF-D01', 0x21C92),
    bytes.fromhex('01 01 9c 12 01'): ('38770-MJE-G52', 0x15F72),
    bytes.fromhex('01 01 9c 01 01'): ('38770-MJE-D41', 0x15F72),
    bytes.fromhex('01 01 4e 12 01'): ('38770-MJE-G12', 0x15F72),
    bytes.fromhex('01 01 4e 0d 03'): ('38770-MJE-T15', 0x15F72),
    bytes.fromhex('01 01 9c 0d 02'): ('38770-MJE-T52', 0x15F72),
    bytes.fromhex('01 00 e0 01 01'): ('38770-MGM-D11', 0x2290F),
    bytes.fromhex('01 00 33 01 03'): ('38770-MFJ-D04', 0x280B5),
    bytes.fromhex('01 00 33 03 02'): ('38770-MFJ-F03', 0x280B5),
    bytes.fromhex('01 00 33 04 01'): ('38770-MFJ-A02', 0x280B5),
    # Source ID table only, without a named image sample; size from its
    # CBR600RR 2007–2016 256 KiB family entry.
    bytes.fromhex('01 00 7c 01 02'): ('38770-MFJ-D42', 0x25439),
    # Exact source ID/offset and VFR1200F MGE-D02 1 MiB family description.
    bytes.fromhex('01 00 aa 01 02'): ('38770-MGE-D02', 0x7FF5C),
    bytes.fromhex('01 02 f2 05 11'): ('38770-MJW-AQ1', 0x18BB7),
    bytes.fromhex('01 02 f2 01 11'): ('38770-MJW-DR1', 0x18BB7),
    # These three examples are 56 KiB rather than 256 KiB. Source flash
    # reading defaults to address zero but allows a user-specified start;
    # the source does not establish where its example files originated.
    bytes.fromhex('01 00 b8 05 02'): ('38770-KYJ-922', 0xC3EE),
    bytes.fromhex('01 00 fa 10 01'): ('38770-KPP-N02', 0xC3CC),
    bytes.fromhex('01 00 c5 0d 02'): ('38770-KPP-T03', 0xC3CC),
    bytes.fromhex('01 01 11 0f 01'): ('38770-KPP-602', 0xC3CC),
    # Source table provides offsets for these short MSX125 examples; using
    # them as read starts is an inference, not a source-confirmed read map.
    bytes.fromhex('01 01 35 05 01'): ('38770-K26-911', 0x97CD),
    bytes.fromhex('01 01 35 01 01'): ('38770-K26-931', 0x97CD),
    bytes.fromhex('01 02 13 05 01'): ('38770-K26-B13', 0x23B8),
    bytes.fromhex('01 02 57 05 01'): ('38770-K26-C31', 0x260C),
    # Z125 and CRF110F examples supply the inferred ID positions and lengths.
    bytes.fromhex('01 02 ca 05 01'): ('38770-K0F-A01', 0x3233),
    bytes.fromhex('01 02 de 05 01'): ('38770-KYK-D12', 0x3319),
}

# VFR1200F fork starts reads at 128 bytes; each example's size/ID location
# remains an inference, and the MGE-701 definition title conflicts with its name.
HONDA_VFR_RESEARCH_IDS = frozenset(bytes.fromhex(v) for v in (
    '01 00 aa 05 01', '01 00 aa 06 01', '48 01 01 19 01'))
# Candidate IDs extracted at known family offsets in source-named examples,
# but not asserted as active source table ID/part matches. Some conflict.
HONDA_EXAMPLE_ONLY_IDS = frozenset(bytes.fromhex(v) for v in (
    '01 00 b0 04 01', '01 00 b0 05 01', '01 00 b0 08 01',
    '01 00 b7 03 01', '01 00 b7 05 01', '01 02 48 05 01',
    '01 01 11 0f 01', '01 02 f2 01 11', '01 00 33 04 01',
    '01 01 4e 0d 03', '01 01 9c 0d 02'))
# Table ID and part, but image offset/size inferred from a different family
# example. The named MKF-L13 file conflicts with the table's ID.
HONDA_FAMILY_INFERRED_IDS = frozenset({bytes.fromhex('01 02 49 05 01')})
HONDA_SOURCE_CONFLICTS = {
    **{ecm_id: 'Named example ID differs from the commented ID-table association for this part.'
       for ecm_id in (bytes.fromhex(v) for v in ('01 00 b0 04 01', '01 00 b0 05 01',
                                                   '01 00 b0 08 01', '01 00 b7 03 01',
                                                   '01 00 b7 05 01'))},
    bytes.fromhex('01 02 48 05 01'): 'MKF-L13 example ID 0102480501 differs from source-table ID 0102490501.',
    bytes.fromhex('01 02 49 05 01'): 'MKF-L13 source-table ID 0102490501 differs from its named example ID 0102480501.',
}
# No source example for these IDs; the source reports their ID offsets and
# model/family ROM sizes, which are not physical validation of this reader.
HONDA_TABLE_ONLY_IDS = frozenset(bytes.fromhex(v) for v in (
    '01 00 7c 01 02', '01 00 aa 01 02'))

# The source table omits ecmidaddr for these entries. Their positions are
# observations in examples, not source-declared offsets.
HONDA_EXAMPLE_INFERRED_IDS = frozenset(
    ecm_id for ecm_id, (part, _) in HONDA_RESEARCH_LAYOUTS.items()
    if ecm_id in HONDA_EXAMPLE_ONLY_IDS or (ecm_id not in HONDA_TABLE_ONLY_IDS | HONDA_FAMILY_INFERRED_IDS
        and part.startswith(('38770-MFL-', '38770-MGP-', '38770-MKF-', '38770-MGE-',
                             '38770-KPP-', '38770-K0F-', '38770-KYK-')))
)
# Do not present a commented-out association as an active upstream entry.
HONDA_RESEARCH_COMMENTED_IDS = frozenset({bytes.fromhex('01 00 5e 05 03')})
# Keep the contradictory source labels rather than silently correcting them.
HONDA_RESEARCH_EXAMPLE_PARTS = {
    bytes.fromhex('01 00 6a 03 01'): '38770-MFN-F01',
    bytes.fromhex('01 00 6a 01 01'): '38770-MFN-D01',
}
HONDA_RESEARCH_IMAGE_SIZES = {
    **{ecm_id: MGZ_A03_IMAGE_SIZE for ecm_id in HONDA_RESEARCH_LAYOUTS},
    bytes.fromhex('01 00 b8 05 02'): 0xE000,
    bytes.fromhex('01 00 fa 10 01'): 0xE000,
    bytes.fromhex('01 00 c5 0d 02'): 0xE000,
    bytes.fromhex('01 01 11 0f 01'): 0xE000,
    bytes.fromhex('01 01 35 05 01'): 0xC000,
    bytes.fromhex('01 01 35 01 01'): 0xC000,
    bytes.fromhex('01 02 13 05 01'): 0x10000,
    bytes.fromhex('01 02 57 05 01'): 0x10000,
    bytes.fromhex('01 02 ca 05 01'): 0x18000,
    bytes.fromhex('01 02 de 05 01'): 0x10000,
    bytes.fromhex('01 02 49 01 01'): 0x100000,
    bytes.fromhex('01 02 48 05 01'): 0x100000,
    bytes.fromhex('01 02 49 05 01'): 0x100000,
    bytes.fromhex('01 00 aa 05 01'): 0x100000,
    bytes.fromhex('01 00 aa 06 01'): 0x100000,
    bytes.fromhex('48 01 01 19 01'): 0x100000,
    bytes.fromhex('01 00 aa 01 02'): 0x100000,
}
HONDA_RESEARCH_STARTS = {
    **{ecm_id: 0 for ecm_id in HONDA_RESEARCH_LAYOUTS},
    bytes.fromhex('01 01 35 05 01'): 0x4000,
    bytes.fromhex('01 01 35 01 01'): 0x4000,
    bytes.fromhex('01 02 13 05 01'): 0x8000,
    bytes.fromhex('01 02 57 05 01'): 0x8000,
}

# Only nonzero checksum locations explicitly listed in the pinned HondaECU
# fork tables. K26 locations are file offsets from Alex's separate table;
# they are not made into physical memory addresses. Zero/absent locations in
# the other table are not guessed. Whole-file 8-bit sums are research only.
HONDA_RESEARCH_CHECKSUM_OFFSETS = {
    **{ecm_id: 0x3FFF8 for ecm_id, (part, _) in HONDA_RESEARCH_LAYOUTS.items()
       if ecm_id not in HONDA_EXAMPLE_ONLY_IDS and part.startswith(
           ('38770-MGZ-', '38770-MEL-', '38770-MFL-', '38770-MGP-',
            '38770-MNF-', '38770-MJE-', '38770-MGM-', '38770-MFJ-', '38770-MJW-'))},
    bytes.fromhex('01 02 49 01 01'): 0xFFFF8,
    bytes.fromhex('01 02 49 05 01'): 0xFFFF8,
    **{ecm_id: 0x7FFF8 for ecm_id, (part, _) in HONDA_RESEARCH_LAYOUTS.items()
       if part.startswith('38770-MGE-')},
    bytes.fromhex('01 00 b8 05 02'): 0xDFEF,
    bytes.fromhex('01 01 35 05 01'): 0x9FFF,
    bytes.fromhex('01 02 13 05 01'): 0x5FFF,
    bytes.fromhex('01 02 57 05 01'): 0x5FFF,
}


def _honda_security_step(connection, data, log):
    body = bytes([0x27, len(data) + 3]) + data
    message = body + bytes([(-sum(body)) & 0xff])
    log('tx', message)
    connection.write(message)
    reply = read_honda_frame(connection, 1.0)
    log('rx', reply)
    if reply[0] != 0x07:
        raise ProtocolError('Honda read security exchange was rejected or malformed; do not retry automatically')


def _honda_read_block(connection, address, size, log, *, max_size=8):
    if max_size not in (8, 128) or not (0 <= address < HONDA_RESEARCH_MAX_END and 1 <= size <= max_size
            and address + size <= HONDA_RESEARCH_MAX_END):
        raise PermissionError('Honda read address outside the fixed research bound')
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


def read_honda_research_image(session, progress=None) -> tuple[bytes, bytes]:
    """Read the source-sized image, failing closed; caller holds session lock.

    Not a verified backup or proof that every ECU byte was acquired. No
    retries, writes, erases, arbitrary addresses or fallback probes.
    """
    # Local import avoids the session module's import of this module.
    from .honda_pgmfi import HondaPgmfiFlashResearchSession
    if type(session) is HondaCB500FDashSession:
        allowed = MGZ_ECM_IDS
    elif type(session) is HondaPgmfiFlashResearchSession:
        allowed = HONDA_RESEARCH_LAYOUTS
    else:
        raise PermissionError('Honda research read requires its exact research session')
    ecm_id = session.read_identity_candidate()
    if ecm_id not in allowed:
        raise ProtocolError('Live ECM ID does not match a supported source-reported ID')
    _, id_offset = HONDA_RESEARCH_LAYOUTS[ecm_id]
    image_size = HONDA_RESEARCH_IMAGE_SIZES[ecm_id]
    start = HONDA_RESEARCH_STARTS[ecm_id]
    if image_size <= 0 or start < 0 or start + image_size > HONDA_RESEARCH_MAX_END:
        raise PermissionError('Honda source candidate is outside the research read bound')
    _honda_security_step(session.connection, b'\xe0HelloHo', session._log)
    _honda_security_step(session.connection, b'\xe0wAreYou', session._log)
    output = bytearray()
    # The VFR source reader starts at 128 bytes. Other research IDs retain
    # their existing eight-byte policy; no automatic fallback on failures.
    block = 128 if ecm_id in HONDA_VFR_RESEARCH_IDS else 8
    while len(output) < image_size:
        offset = len(output)
        size = min(block, image_size - offset)
        output.extend(_honda_read_block(session.connection, start + offset, size, session._log, max_size=block))
        if progress:
            progress(len(output), image_size)
    if output[id_offset:id_offset + 5] != ecm_id:
        raise ProtocolError('Read image ECM ID bytes do not match the source-reported offset')
    if sum(output) & 0xff:
        raise ProtocolError('Read image fails the candidate whole-image checksum (zero sum observed in source examples)')
    return bytes(output), ecm_id


def read_mgz_research_image(session: HondaCB500FDashSession, progress=None) -> bytes:
    """Compatibility wrapper for the narrower CB500F DashBle path."""
    if type(session) is not HondaCB500FDashSession:
        raise PermissionError('MGZ read requires the CB500F DashBle session')
    return read_honda_research_image(session, progress)[0]
