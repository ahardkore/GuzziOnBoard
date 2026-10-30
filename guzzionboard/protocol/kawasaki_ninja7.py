"""Source-scoped Ninja 7 Hybrid KWP-on-CAN read-only session.

Adapted from Matt Githens' MIT-licensed kawasaki-can-hack, revision
26820ddf88d682c7071b0825252c7fa0b82c709a; see
LICENSES/Kawasaki-CAN-Hack-MIT.txt. GuzziOnBoard hardware has not been tested.
"""
from __future__ import annotations

from .kwp2000 import Frame, KWP2000Session, NegativeResponse, ProtocolError, decode_dtc_number


class KawasakiNinja7Session(KWP2000Session):
    # Source-tested or source-described values only, no arbitrary PID probing.
    LENGTHS = {0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x09: 2, 0x0B: 1,
               0x0C: 1, 0x0D: 2, 0x76: 1}

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        if not (payload in (b'\x10\x80', b'\x1a\x80', b'\x18\x01', b'\x3e')
                or (len(payload) == 2 and payload[0] == 0x21 and payload[1] in self.LENGTHS)):
            raise PermissionError('Ninja 7 read-only session refuses this request')
        self._log('tx', payload)
        self.connection.write(payload)
        reply = self.connection.read_frame(2.0 if timeout is None else timeout)
        if not reply:
            if payload == b'\x3e':
                return None  # source sends keepalive without requiring a reply
            raise ProtocolError('Ninja 7 response timed out')
        self._log('rx', reply)
        if reply[0] == 0x7f:
            if len(reply) != 3 or reply[1] != payload[0]:
                raise ProtocolError('Ninja 7 malformed or mismatched negative response')
            raise NegativeResponse(reply[1], reply[2])
        if reply[0] != payload[0] + 0x40:
            raise ProtocolError('Ninja 7 response service mismatch')
        if payload == b'\x10\x80' and (len(reply) < 2 or reply[1] != 0x80):
            raise ProtocolError('Ninja 7 session start response mismatch')
        if payload[0] == 0x21:
            if len(reply) != 2 + self.LENGTHS[payload[1]] or reply[1] != payload[1]:
                raise ProtocolError('Ninja 7 data response identifier or length mismatch')
            if payload[1] in (0x06, 0x07, 0x0C) and reply[2] == 0xff:
                raise ProtocolError('Ninja 7 sensor reports unavailable (0xFF)')
        if payload == b'\x1a\x80' and len(reply) < 2:
            raise ProtocolError('Ninja 7 empty ECU identification response')
        return Frame(format_byte=0, target=None, source=None, payload=reply, raw=reply)

    def tester_present(self):
        return self.request(b'\x3e', timeout=0.5)

    def read_identity_raw(self):
        return self.request(b'\x1a\x80').payload[1:]

    def read_stored_codes(self):
        reply = self.request(b'\x18\x01').payload
        if reply == b'\x58\x00':
            return []
        # Only zero DTCs were confirmed in the source. Its nonzero parser is
        # a candidate; reject incomplete or inconsistent record counts.
        if len(reply) < 3:
            raise ProtocolError('Ninja 7 truncated DTC response')
        count = int.from_bytes(reply[1:3], 'big')
        if len(reply) != 3 + 3 * count:
            raise ProtocolError('Ninja 7 DTC record count or length mismatch')
        return [{'code': decode_dtc_number(reply[i], reply[i + 1]),
                 'status_byte': reply[i + 2], 'status': 'uninterpreted',
                 'description': 'Source-described DTC layout; nonzero records not confirmed',
                 'kind': 'uninterpreted', 'warning_indicator': None} for i in range(3, len(reply), 3)]
