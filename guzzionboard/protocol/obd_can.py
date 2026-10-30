"""Explicit single-ECU, read-only generic SAE OBD over 11-bit ISO-TP CAN.

This is not a model-specific protocol claim. It requires the target to answer
standard OBD requests and has only synthetic tests in GuzziOnBoard. The OBD
PID definitions reuse the existing Daytona profile's standard SAE scaling.
"""
from __future__ import annotations

from .kwp2000 import NegativeResponse, ProtocolError


class ObdCanSession:
    # Deliberately restricted to the PID definitions in the generic profile.
    LENGTHS = {0x00: 4, 0x04: 1, 0x05: 1, 0x06: 1, 0x0B: 1,
               0x0C: 2, 0x0D: 1, 0x0E: 1, 0x0F: 1, 0x11: 1, 0x1F: 2,
               0x20: 4, 0x2F: 1, 0x33: 1, 0x40: 4, 0x42: 2, 0x5C: 1, 0x5E: 2}

    def __init__(self, connection, *, on_frame=None):
        self.connection = connection
        self.on_frame = on_frame or (lambda _direction, _raw: None)
        self.supported = None
        self.support_pages = set()
        self.vehicle_info_supported = None

    def request(self, payload):
        payload = bytes(payload)
        if not (payload == b'\x03' or len(payload) == 2 and ((payload[0] == 1 and payload[1] in self.LENGTHS) or (payload[0] == 9 and payload[1] in (0, 2, 4)))):
            raise PermissionError('Generic OBD CAN allows only listed mode 01 PIDs, mode 03 and mode 09 VIN/calibration ID')
        if len(payload) == 2 and payload[0] == 1 and payload[1] != 0 and (self.supported is None or payload[1] not in self.supported):
            raise ProtocolError(f'ECU support bitmap does not list PID 0x{payload[1]:02X}')
        if payload[0] == 9 and payload[1] in (2, 4) and (self.vehicle_info_supported is None or payload[1] not in self.vehicle_info_supported):
            raise ProtocolError(f'ECU mode 09 support bitmap does not list PID 0x{payload[1]:02X}')
        self.on_frame('tx', payload)
        self.connection.write(payload)
        reply = self.connection.read_frame(2.0)
        if not reply:
            raise ProtocolError('No OBD response from the selected ECU')
        self.on_frame('rx', reply)
        if reply[0] == 0x7f:
            if len(reply) != 3 or reply[1] != payload[0]:
                raise ProtocolError('Malformed or mismatched OBD negative response')
            raise NegativeResponse(reply[1], reply[2])
        if reply[0] != payload[0] + 0x40:
            raise ProtocolError('OBD response service mismatch')
        if payload[0] == 1:
            if len(reply) != 2 + self.LENGTHS[payload[1]] or reply[1] != payload[1]:
                raise ProtocolError('OBD PID response identifier or length mismatch')
        elif payload[0] == 9:
            if len(reply) < 2 or reply[1] != payload[1]:
                raise ProtocolError('OBD vehicle information identifier or length mismatch')
            if payload[1] == 0 and len(reply) != 6:
                raise ProtocolError('OBD vehicle information support bitmap length mismatch')
            if payload[1] == 2 and (len(reply) != 20 or reply[2] != 1):
                raise ProtocolError('OBD VIN count or length mismatch')
            if payload[1] == 4 and (len(reply) < 3 or not 1 <= reply[2] <= 4 or len(reply) != 3 + 16 * reply[2]):
                raise ProtocolError('OBD calibration ID count or length mismatch')
        elif len(reply) < 2 or len(reply) != 2 + 2 * reply[1]:
            raise ProtocolError('OBD CAN DTC count or length mismatch')
        return reply

    def initialise(self):
        data = self.request(b'\x01\x00')[2:]
        self.supported = {i + 1 for i in range(32) if data[i // 8] & (0x80 >> (i % 8))}
        self.support_pages = {0}

    def read_vehicle_information(self):
        # Query a fresh support bitmap; Mode 01 success does not imply Mode 09.
        self.vehicle_info_supported = None
        bitmap = self.request(b'\x09\x00')[2:]
        self.vehicle_info_supported = {i + 1 for i in range(32) if bitmap[i // 8] & (0x80 >> (i % 8))}
        fields, chunks = {}, []
        if 2 in self.vehicle_info_supported:
            raw = self.request(b'\x09\x02')[3:]
            if any(c not in b'ABCDEFGHJKLMNPRSTUVWXYZ0123456789' for c in raw):
                raise ProtocolError('OBD VIN response is not 17 permitted uppercase VIN characters')
            fields['Vehicle VIN (unverified OBD response)'] = raw.decode('ascii')
            chunks.append(raw)
        if 4 in self.vehicle_info_supported:
            raw = self.request(b'\x09\x04')[3:]
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
                bitmap = self.request(bytes([1, base]))[2:]
                self.supported.update(base + i + 1 for i in range(32)
                                      if bitmap[i // 8] & (0x80 >> (i % 8)))
                self.support_pages.add(base)
        return self.request(bytes([1, local_id]))[2:]

    def read_stored_codes(self):
        reply = self.request(b'\x03')
        codes = []
        for i in range(2, len(reply), 2):
            a, b = reply[i:i + 2]
            if not (a or b):
                raise ProtocolError('OBD CAN DTC list contains an empty counted entry')
            code = f"{'PCBU'[a >> 6]}{(a >> 4) & 3}{a & 15:X}{b:02X}"
            codes.append({'code': code, 'description': '', 'status_byte': None,
                          'kind': 'OBD stored', 'status': 'stored', 'warning_indicator': False})
        return codes

    def close(self):
        pass
