"""Generic read-only KWP2000 (ISO 14230) session over K-Line.

Unlike :class:`~guzzionboard.protocol.kwp2000.KWP2000Session`, whose write guard
only blocks the mutating services, this session enforces the generic profile's
read-only allowlist in code: only session control, ECU identification,
local-identifier reads, DTC reads and tester-present may be transmitted.
ReadMemoryByAddress (0x23) and every other service - including all mutating
ones - are refused with ``PermissionError`` before a byte is sent, so the
profile's "identification and stored DTCs only" claim holds even if the
caller bypasses the catalog capability check. Synthetic tests only; no
model-specific fitment is claimed.
"""
from __future__ import annotations

from typing import Sequence

from .kwp2000 import KWP2000Session, Service

#: The complete read-only vocabulary of the generic profile.
READ_ONLY_SERVICES = frozenset({
    Service.START_DIAGNOSTIC_SESSION,
    Service.READ_ECU_IDENTIFICATION,
    Service.READ_DATA_BY_LOCAL_ID,
    0x17,  # readStatusOfDiagnosticTroubleCodes (not in the Service enum)
    Service.READ_DTC_BY_STATUS,
    Service.TESTER_PRESENT,
})


class GenericKwp2000Session(KWP2000Session):
    """KWP2000 session restricted to the standard read-only services."""

    def request(self, payload: Sequence[int], *, timeout: float | None = None,
                force_long: bool = False, pending_timeout: float | None = None):
        payload = bytes(payload)
        if not payload or payload[0] not in READ_ONLY_SERVICES:
            sid = payload[0] if payload else -1
            raise PermissionError(
                f"generic KWP2000 allows only read-only services "
                f"(10/1A/21/17/18/3E); 0x{sid:02X} was refused before transmission"
            )
        return super().request(payload, timeout=timeout, force_long=force_long,
                               pending_timeout=pending_timeout)
