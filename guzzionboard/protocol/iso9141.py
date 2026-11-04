"""Generic read-only SAE OBD-II over ISO 9141-2 K-Line (ISO 14230-3 framing).

ISO 9141-2 shares the K-Line and the 5-baud electrical initialisation with
KWP2000, but the keyword pairs ``08 08`` / ``94 94`` select a different message
layer: a three-byte header (format, target, source), the payload, and a
checksum, with no length byte - so replies are read as a burst until the line
goes quiet (``KLineConnection.read_iso9141_burst``).

This module is deliberately generic, not a model-specific claim: it speaks
only the legislated OBD services (mode 01 listed PIDs, mode 03 stored DTCs,
optional mode 09 VIN / calibration IDs) against the standard OBD header
``68 6A F1`` / reply header ``48 6B D1`` at 10400 baud after a validated
5-baud handshake. It has synthetic tests only; nothing here is verified against
a particular motorcycle. The request allowlist mirrors
:class:`guzzionboard.protocol.obd_can.ObdCanSession` - anything outside it is
refused with ``PermissionError`` before a byte is sent.
"""
from __future__ import annotations

import time

from .kwp2000 import NegativeResponse, ProtocolError, checksum

#: Standard OBD-II K-Line addressing: format byte, target ECU 0x6A, tester 0xF1.
DEFAULT_REQUEST_HEADER = bytes([0x68, 0x6A, 0xF1])
#: ECU replies come from 0x6B back to the tester 0xD1.
DEFAULT_RESPONSE_HEADER = bytes([0x48, 0x6B, 0xD1])

#: A burst larger than this is not a frame sequence any OBD ECU sends.
MAX_BURST_BYTES = 512

#: Minimum quiet time between the request and the first response byte, and
#: between response bytes, before the line is considered idle (ISO 9141-2 P4).
DEFAULT_INTER_BYTE_GAP = 0.060


def build_frame(payload, header: bytes = DEFAULT_REQUEST_HEADER) -> bytes:
    """Header + payload + checksum, the complete on-wire request."""
    payload = bytes(payload)
    if not 1 <= len(payload) <= 255:
        raise ProtocolError("ISO 9141-2 payload must be 1..255 bytes")
    if len(header) != 3:
        raise ProtocolError("ISO 9141-2 header is exactly three bytes")
    body = bytes(header) + payload
    return body + bytes([checksum(body)])


def parse_iso9141_burst(raw: bytes, resp_header: bytes = DEFAULT_RESPONSE_HEADER) -> list[bytes]:
    """Split a checksum-delimited burst into payload frames.

    Every frame must start with the expected reply header and carry a valid
    checksum; anything else is a protocol error, never a partial answer.
    """
    raw = bytes(raw)
    resp_header = bytes(resp_header)
    if not raw or len(raw) > MAX_BURST_BYTES:
        raise ProtocolError("Invalid ISO 9141-2 response burst")
    frames, start = [], 0
    while start < len(raw):
        if raw[start:start + 3] != resp_header:
            raise ProtocolError("Unexpected ISO 9141-2 reply header")
        end = None
        for candidate in range(start + 5, len(raw) + 1):
            if candidate < len(raw) and raw[candidate:candidate + 3] != resp_header:
                continue
            if checksum(raw[start:candidate - 1]) == raw[candidate - 1]:
                end = candidate
                break
        if end is None:
            raise ProtocolError("ISO 9141-2 checksum mismatch or truncated burst")
        frames.append(raw[start + 3:end - 1])
        start = end
    return frames


class Iso9141ObdSession:
    """Read-only generic OBD session on an ISO 9141-2 K-Line link.

    The 5-baud handshake has already completed when this object is created
    (the transport owns it); this class only frames requests. Only the PID
    definitions of the generic catalog profile are reachable.
    """

    # Mode 01 PIDs the generic profile declares, with their response lengths.
    LENGTHS = {0x00: 4, 0x04: 1, 0x05: 1, 0x06: 1, 0x0B: 1,
               0x0C: 2, 0x0D: 1, 0x0E: 1, 0x0F: 1, 0x11: 1, 0x1F: 2,
               0x20: 4, 0x2F: 1, 0x33: 1, 0x40: 4, 0x42: 2, 0x5C: 1, 0x5E: 2}

    def __init__(self, connection, *, on_frame=None,
                 req_header: bytes = DEFAULT_REQUEST_HEADER,
                 resp_header: bytes = DEFAULT_RESPONSE_HEADER,
                 inter_frame_delay: float = 0.060):
        self.connection = connection
        self.on_frame = on_frame or (lambda _direction, _raw: None)
        self.req_header = bytes(req_header)
        self.resp_header = bytes(resp_header)
        self.inter_frame_delay = inter_frame_delay
        self.supported = None
        self.support_pages = set()
        self.vehicle_info_supported = None

    # -- framing ----------------------------------------------------------
    def _read_burst(self, timeout: float) -> bytes:
        reader = getattr(self.connection, "read_iso9141_burst", None)
        if reader is not None:
            return reader(timeout, gap=DEFAULT_INTER_BYTE_GAP, limit=MAX_BURST_BYTES)
        return self.connection.read_frame(timeout)

    def request(self, payload, *, timeout: float | None = None):
        """Send one allowlisted request; return the validated reply frames.

        Anything but mode 01 listed PIDs, mode 03 and mode 09 VIN/calibration
        queries is refused before transmission - this session has no write,
        clear, actuator or routine vocabulary at all.
        """
        payload = bytes(payload)
        if not (payload == b'\x03' or len(payload) == 2 and ((payload[0] == 1 and payload[1] in self.LENGTHS) or (payload[0] == 9 and payload[1] in (0, 2, 4)))):
            raise PermissionError('Generic OBD over ISO 9141-2 allows only listed mode 01 PIDs, mode 03 and mode 09 VIN/calibration ID')
        if len(payload) == 2 and payload[0] == 1 and payload[1] != 0 and (self.supported is None or payload[1] not in self.supported):
            raise ProtocolError(f'ECU support bitmap does not list PID 0x{payload[1]:02X}')
        if payload[0] == 9 and payload[1] in (2, 4) and (self.vehicle_info_supported is None or payload[1] not in self.vehicle_info_supported):
            raise ProtocolError(f'ECU mode 09 support bitmap does not list PID 0x{payload[1]:02X}')
        raw = build_frame(payload, self.req_header)
        if self.inter_frame_delay > 0:
            time.sleep(self.inter_frame_delay)
        self.on_frame('tx', raw)
        self.connection.write(raw)
        burst = self._read_burst(2.0 if timeout is None else timeout)
        if not burst:
            raise ProtocolError('No OBD response from the selected ECU')
        self.on_frame('rx', burst)
        frames = parse_iso9141_burst(burst, self.resp_header)
        for frame in frames:
            if len(frame) >= 3 and frame[0] == 0x7f:
                raise NegativeResponse(frame[1], frame[2])
            if not frame or frame[0] != (payload[0] | 0x40):
                raise ProtocolError('ISO 9141-2 OBD response service mismatch')
            if payload[0] == 1 and (len(frame) != 2 + self.LENGTHS[payload[1]] or frame[1] != payload[1]):
                raise ProtocolError('ISO 9141-2 PID response identifier or length mismatch')
            if payload[0] == 9 and (len(frame) < 2 or frame[1] != payload[1]):
                raise ProtocolError('ISO 9141-2 vehicle information identifier mismatch')
            if payload[0] == 9 and payload[1] == 0 and len(frame) != 6:
                raise ProtocolError('ISO 9141-2 mode 09 support bitmap length mismatch')
            if payload[0] == 9 and payload[1] == 2 and (len(frame) != 20 or frame[2] != 1):
                raise ProtocolError('ISO 9141-2 VIN count or length mismatch')
            if payload[0] == 9 and payload[1] == 4 and (len(frame) < 3 or not 1 <= frame[2] <= 4 or len(frame) != 3 + 16 * frame[2]):
                raise ProtocolError('ISO 9141-2 calibration ID count or length mismatch')
            if payload[0] == 3 and ((len(frame) - 1) % 2 or len(frame) < 1):
                raise ProtocolError('ISO 9141-2 DTC response has a partial code')
        return frames

    # -- OBD services -----------------------------------------------------
    def initialise(self):
        frames = self.request([1, 0])
        if len(frames) != 1:
            raise ProtocolError('ISO 9141-2 support bitmap must have one response')
        bitmap = frames[0][2:]
        self.supported = {i + 1 for i in range(32) if bitmap[i // 8] & (0x80 >> (i % 8))}
        self.support_pages = {0}

    def read_vehicle_information(self):
        # Query a fresh support bitmap; Mode 01 success does not imply Mode 09.
        self.vehicle_info_supported = None
        frames = self.request([9, 0])
        if len(frames) != 1:
            raise ProtocolError('ISO 9141-2 mode 09 support bitmap must have one response')
        bitmap = frames[0][2:]
        self.vehicle_info_supported = {i + 1 for i in range(32) if bitmap[i // 8] & (0x80 >> (i % 8))}
        fields, chunks = {}, []
        if 2 in self.vehicle_info_supported:
            raw = self.request([9, 2])[0][3:]
            if any(c not in b'ABCDEFGHJKLMNPRSTUVWXYZ0123456789' for c in raw):
                raise ProtocolError('OBD VIN response is not 17 permitted uppercase VIN characters')
            fields['Vehicle VIN (unverified OBD response)'] = raw.decode('ascii')
            chunks.append(raw)
        if 4 in self.vehicle_info_supported:
            raw = self.request([9, 4])[0][3:]
            values = []
            for offset in range(0, len(raw), 16):
                part = raw[offset:offset + 16]
                if any(c != 0 and not 0x20 <= c <= 0x7e for c in part):
                    raise ProtocolError('OBD calibration ID has non-printable characters')
                value = part.decode('ascii').strip(' \x00')
                if not value or '\x00' in value:
                    raise ProtocolError('OBD calibration ID is empty or has embedded nulls')
                values.append(value)
            fields['Calibration IDs (unverified OBD response)'] = ', '.join(values)
            chunks.append(raw)
        if not fields:
            raise ProtocolError('ECU mode 09 support bitmap lists neither VIN nor calibration ID')
        return fields, b''.join(chunks)

    def read_data_by_local_id(self, local_id):
        if local_id in self.LENGTHS and local_id > 0x20:
            # Additional bitmap pages are requested lazily, only if the
            # preceding bitmap advertises the corresponding continuation PID.
            for base in (0x20, 0x40):
                if local_id <= base:
                    break
                if base in self.support_pages:
                    continue
                if self.supported is None or base not in self.supported:
                    break
                frames = self.request(bytes([1, base]))
                if len(frames) != 1:
                    raise ProtocolError('ISO 9141-2 support bitmap page must have one response')
                bitmap = frames[0][2:]
                self.supported.update(base + i + 1 for i in range(32)
                                      if bitmap[i // 8] & (0x80 >> (i % 8)))
                self.support_pages.add(base)
        frames = self.request(bytes([1, local_id]))
        if len(frames) != 1:
            raise ProtocolError('ISO 9141-2 PID yielded multiple responses')
        return frames[0][2:]

    def read_stored_codes(self):
        codes = []
        for frame in self.request([3]):
            if len(frame) < 1:
                continue
            for index in range(1, len(frame), 2):
                a, b = frame[index:index + 2]
                if not (a or b):
                    continue
                code = f"{'PCBU'[a >> 6]}{(a >> 4) & 3}{a & 15:X}{b:02X}"
                codes.append({'code': code, 'description': '', 'status_byte': None,
                              'kind': 'OBD stored', 'status': 'stored', 'warning_indicator': False})
        return codes

    def tester_present(self):
        return self.request([1, 0])

    def close(self):
        pass
