"""Ducati Panigale V2 dash annual-service-reset builders (experimental).

Source: slava-fm/moto-service-tool @ ac39e456, MIT (LICENSES/MotoServiceTool-MIT.txt
to be added), reset-scripts/annual-service-reset.txt — "Confirmed working
2026-06-05" for the author's stated Ducati Panigale V2 fitment: dashboard ECU
CAN 0x7E3 (response 0x7EB), KWP2000-over-CAN with manual ISO-TP framing
(ATCAF0). Author-confirmed success on the stated fitment -> adopted as
[experimental] per the write-class rule.

Every function requires CONFIRM_TOKEN and returns frame BYTES only — nothing
opens a transport or sends to a vehicle. This is a dashboard service-reminder
reset, NOT an ECU flash, and touches nothing immobilizer/odometer related.
"""
from __future__ import annotations

from .experimental_writers import CONFIRM_TOKEN, _gate

PROFILE = 'ducati_panigale_v2_service_reset_experimental'

DASH_TX_ID = 0x7E3
DASH_RX_ID = 0x7EB

# Payload sequence transcribed verbatim from the confirmed script
# (AT modem setup commands omitted; ISO-TP single-frame payloads only).
RESET_PAYLOADS = [
    bytes.fromhex('021001'),   # StartDiagnosticSession 0x01
    bytes.fromhex('021A91'),   # ReadDataByIdentifier 0x1A91
    bytes.fromhex('021A93'),   # ReadDataByIdentifier 0x1A93
    bytes.fromhex('04310900'), # RoutineControl 0x0900 (service reset)
    bytes.fromhex('023309'),   # vendor reset service 0x33 0x09
    bytes.fromhex('04320900'), # vendor write service 0x32 0x0900
    bytes.fromhex('023E00'),   # TesterPresent
    bytes.fromhex('021A91'),
    bytes.fromhex('021A93'),
]

# ELM327 setup preamble (reference only; never sent by this module)
AT_PREAMBLE = ['ATZ', 'ATE0', 'ATL0', 'ATS1', 'ATSP6', 'ATCAF0', 'ATAT1',
               'ATSH7E3', 'ATCRA7EB']


def kwp_can_single_frame(tx_id: int, payload: bytes, *, confirm_token: str) -> bytes:
    """ISO-TP single frame: [0x0N, payload...] for payloads up to 7 bytes."""
    _gate(confirm_token)
    payload = bytes(payload)
    if not (1 <= len(payload) <= 7):
        raise ValueError('single-frame payload must be 1..7 bytes')
    return bytes([len(payload)]) + payload


def build_reset_frames(*, confirm_token: str) -> list[tuple[int, bytes]]:
    """Ordered (can_id, iso_tp_bytes) list for the confirmed dash reset."""
    _gate(confirm_token)
    return [(DASH_TX_ID, kwp_can_single_frame(DASH_TX_ID, p, confirm_token=confirm_token))
            for p in RESET_PAYLOADS]
