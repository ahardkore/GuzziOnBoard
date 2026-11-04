"""Generic read-only UDS (ISO 14229) session over 11-bit ISO-TP CAN.

This is deliberately generic, not a model-specific claim: it speaks only the
standard read-only UDS services against whatever ECU answers at the selected
physical diagnostic CAN ID pair (0x7E0-0x7E7 request, +8 response, 500 kbit/s).
The request allowlist is enforced before any byte is transmitted:

* ``10 <session>``      DiagnosticSessionControl, default (0x01) or extended
                        diagnostic session (0x03) only - no programming session
* ``22 <DID hi lo>``    ReadDataByIdentifier
* ``19 <sub> [...]``    ReadDTCInformation (the whole service is read-only)
* ``3E [sub]``          TesterPresent

Everything else - ECUReset (0x11), ClearDiagnosticInformation (0x14),
ReadMemoryByAddress (0x23), SecurityAccess (0x27), WriteDataByIdentifier
(0x2E), RoutineControl (0x31), RequestDownload/TransferData/... (0x34-0x38),
and any unknown service - is refused with ``PermissionError``. There is no
write, clear, actuator, routine or programming vocabulary in this session at
all. Synthetic tests only; nothing here is verified against a particular
motorcycle.

Written sources: ISO 14229 service tables (see docs/PROTOCOL_NOTES.md), the
py-uds / python-udsoncan reference implementations.
"""
from __future__ import annotations

from .kwp2000 import NegativeResponse, ProtocolError

#: DiagnosticSessionControl sub-functions that are read-only safe.
READ_ONLY_SESSIONS = (0x01, 0x03)
#: DIDs the generic profile exposes: only the standardized VIN identifier.
VIN_DID = 0xF190


def _valid_request(payload: bytes) -> bool:
    if len(payload) == 2 and payload[0] == 0x10:
        return payload[1] in READ_ONLY_SESSIONS
    if len(payload) == 3 and payload[0] == 0x22:
        return True
    if payload[0] == 0x19 and 2 <= len(payload) <= 4:
        return True
    if payload[0] == 0x3E and len(payload) in (1, 2):
        return True
    return False


class UdsSession:
    """Read-only generic UDS session on an ISO-TP CAN link.

    The ISO-TP transport (single/multi-frame segmentation, flow control) is
    owned by the CAN connection; this class only exchanges UDS payloads, the
    same split :class:`~guzzionboard.protocol.obd_can.ObdCanSession` uses.
    """

    def __init__(self, connection, *, on_frame=None, timeout: float = 2.0):
        self.connection = connection
        self.on_frame = on_frame or (lambda _direction, _raw: None)
        self.timeout = timeout

    def request(self, payload, *, timeout: float | None = None) -> bytes:
        """Send one allowlisted request; return the validated positive reply.

        Anything outside the read-only allowlist is refused before
        transmission. Negative responses raise :class:`NegativeResponse`.
        """
        payload = bytes(payload)
        if not payload or not _valid_request(payload):
            raise PermissionError(
                'Generic UDS allows only read-only services: '
                'DiagnosticSessionControl (default/extended), ReadDataByIdentifier, '
                'ReadDTCInformation and TesterPresent'
            )
        self.on_frame('tx', payload)
        self.connection.write(payload)
        reply = self.connection.read_frame(timeout if timeout is not None else self.timeout)
        if not reply:
            raise ProtocolError('No UDS response from the selected ECU')
        self.on_frame('rx', reply)
        if reply[0] == 0x7F:
            if len(reply) != 3 or reply[1] != payload[0]:
                raise ProtocolError('Malformed or mismatched UDS negative response')
            raise NegativeResponse(reply[1], reply[2])
        if reply[0] != payload[0] + 0x40:
            raise ProtocolError('UDS response service mismatch')
        if payload[0] in (0x10, 0x19, 0x3E) and len(reply) >= 2 and reply[1] != payload[1]:
            raise ProtocolError('UDS response sub-function echo mismatch')
        if payload[0] == 0x22 and (len(reply) < 4 or reply[1:3] != payload[1:3]):
            raise ProtocolError('UDS ReadDataByIdentifier DID echo mismatch')
        return reply

    # -- read-only vocabulary ---------------------------------------------
    def initialise(self) -> None:
        """Enter the default diagnostic session (read-only safe)."""
        self.request(b'\x10\x01')

    def enter_extended_session(self) -> None:
        """Enter the extended diagnostic session (still read-only safe)."""
        self.request(b'\x10\x03')

    def tester_present(self) -> None:
        self.request(b'\x3e')

    def read_did(self, did: int) -> bytes:
        reply = self.request(bytes([0x22]) + did.to_bytes(2, 'big'))
        return reply[3:]

    def read_data_by_local_id(self, local_id: int) -> bytes:
        """Catalog-parameter path; the "local id" of UDS is the DID."""
        return self.read_did(local_id)

    def read_vehicle_information(self):
        """Read the standardized VIN DID; reported as unverified, like OBD mode 09."""
        raw = self.read_did(VIN_DID)
        if len(raw) != 17 or any(c not in b'ABCDEFGHJKLMNPRSTUVWXYZ0123456789' for c in raw):
            raise ProtocolError('UDS VIN response is not 17 permitted uppercase VIN characters')
        fields = {'Vehicle VIN (unverified UDS DID F190 response)': raw.decode('ascii')}
        return fields, raw

    def read_stored_codes(self):
        """ReadDTCInformation sub 0x02 (DTCs by status mask 0xFF), SAE J2012 decoded."""
        reply = self.request(b'\x19\x02\xff')
        # Positive reply: 59 02 <statusAvailabilityMask> <DTCAndStatusRecord...>
        data = reply[2:]
        if not data:
            raise ProtocolError('UDS ReadDTCInformation response is empty')
        records = data[1:]  # skip the DTC status availability mask
        if len(records) % 4 != 0:
            raise ProtocolError('UDS DTC record list is not a multiple of 4 bytes')
        codes = []
        for i in range(0, len(records), 4):
            a, b, c, status = records[i:i + 4]
            if not (a or b or c):
                raise ProtocolError('UDS DTC list contains an empty record')
            # First two DTC bytes carry the SAE J2012 letter/digit layout;
            # the third byte and the status byte stay raw.
            code = f"{'PCBU'[a >> 6]}{(a >> 4) & 3}{a & 15:X}{b:02X}"
            codes.append({'code': code, 'description': '', 'status_byte': status,
                          'kind': 'UDS stored', 'status': 'stored', 'warning_indicator': False})
        return codes

    def close(self):
        pass
