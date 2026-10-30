"""Narrow Harley Delphi CAN identity-query attempt.

Wire identifiers and DIDs are factual observations from rob9206/lawflo,
HarleyECUDump, revision 6255518dc9118d960efa42d6d9dc975926bbd579.
No code, firmware, capture payloads or credentials from that source are
included; its license and use disclaimers are not unambiguous. This session
never performs authentication, a session change, a download or memory read.
The new implementation has synthetic tests only.
"""
from __future__ import annotations

from .kwp2000 import NegativeResponse, ProtocolError


class HarleyCanTimeout(ProtocolError):
    pass


class HarleyDelphiCanSession:
    DIDS = {
        0xF1EA: 'Part-number DID F1EA (raw candidate)',
        0xF1ED: 'Serial-number DID F1ED (raw candidate)',
        0xF1F5: 'Calibration-ID DID F1F5 (raw candidate)',
        0xF1F2: 'Checksum DID F1F2 (raw candidate)',
        0xF1EF: 'ECU-info DID F1EF (raw candidate)',
    }

    # These DIDs were requested and received in the source capture; their
    # meanings are not described. Expose only the captured lengths and raw bytes.
    RAW_DIDS = {0x0100: 2, 0x0101: 1, 0x0102: 3, 0x0103: 1}

    def __init__(self, connection, *, on_frame=None):
        self.connection = connection
        self.on_frame = on_frame or (lambda _direction, _raw: None)

    def request(self, payload):
        payload = bytes(payload)
        if payload != b'\x3e\x00' and not (len(payload) == 3 and payload[0] == 0x22 and int.from_bytes(payload[1:], 'big') in (self.DIDS.keys() | self.RAW_DIDS.keys())):
            raise PermissionError('Harley Delphi identity research allows only tester-present and five fixed DIDs')
        self.on_frame('tx', payload)
        self.connection.write(payload)
        reply = self.connection.read_frame(2.0)
        if not reply:
            raise HarleyCanTimeout('Harley CAN request timed out')
        self.on_frame('rx', reply)
        if reply[0] == 0x7f:
            if len(reply) != 3 or reply[1] != payload[0]:
                raise ProtocolError('Harley CAN malformed or mismatched negative response')
            raise NegativeResponse(reply[1], reply[2])
        if payload == b'\x3e\x00':
            if reply != b'\x7e\x00':
                raise ProtocolError('Harley CAN tester-present response mismatch')
        elif len(reply) < 4 or len(reply) > 259 or reply[:3] != b'\x62' + payload[1:]:
            raise ProtocolError('Harley CAN DID response identifier or length mismatch')
        if payload[0] == 0x22:
            did = int.from_bytes(payload[1:], 'big')
            if did in self.RAW_DIDS and len(reply) != 3 + self.RAW_DIDS[did]:
                raise ProtocolError('Harley CAN raw DID length differs from the source capture')
        return reply

    def read_data_by_local_id(self, local_id):
        if local_id not in self.RAW_DIDS:
            raise PermissionError('Harley CAN live research allows only four fixed raw DIDs')
        return self.request(b'\x22' + local_id.to_bytes(2, 'big'))[3:]

    def read_identity_candidates(self):
        fields, raw = {}, []
        for did, label in self.DIDS.items():
            try:
                reply = self.request(bytes([0x22]) + did.to_bytes(2, 'big'))
            except (HarleyCanTimeout, NegativeResponse):
                continue
            value = reply[3:]
            fields[label] = value.hex(' ').upper()
            raw.append(reply)
        if not fields:
            raise ProtocolError('No Harley Delphi identity DIDs answered; the target may require authentication or a different protocol')
        return fields, b''.join(raw)

    def close(self):
        pass
