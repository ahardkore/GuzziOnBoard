"""Offline, source-scoped Honda byte-sum preview; never accesses an ECU.

Checksum locations follow the pinned HondaECU tables, GPL-3.0. The source
algorithm sets the specified byte to the two's complement of the other bytes.
The result is research only, not proof of fitment or flash readiness.
"""
from __future__ import annotations

import hashlib
from .protocol.honda_cbr600rr import (
    HONDA_RESEARCH_CHECKSUM_OFFSETS, HONDA_RESEARCH_LAYOUTS, HONDA_RESEARCH_IMAGE_SIZES,
    HONDA_RESEARCH_STARTS, HONDA_EXAMPLE_INFERRED_IDS, HONDA_TABLE_ONLY_IDS,
    HONDA_FAMILY_INFERRED_IDS, HONDA_SOURCE_CONFLICTS, HONDA_RESEARCH_COMMENTED_IDS,
    HONDA_RESEARCH_EXAMPLE_PARTS, HONDA_VFR_RESEARCH_IDS,
)


def proposals(original: bytes | bytearray, edited: bytes | bytearray) -> list[dict]:
    if len(original) != len(edited) or not original or len(original) > 0x100000 or sum(original) & 255:
        return []
    edited_sum = sum(edited) & 255
    result = []
    for ecm, offset in HONDA_RESEARCH_CHECKSUM_OFFSETS.items():
        part, id_offset = HONDA_RESEARCH_LAYOUTS[ecm]
        if (len(original) != HONDA_RESEARCH_IMAGE_SIZES[ecm]
                or original[id_offset:id_offset+5] != ecm or edited[id_offset:id_offset+5] != ecm):
            continue
        # Do not advertise checksum-only changes as an edited calibration.
        if all(a == b for i, (a, b) in enumerate(zip(original, edited)) if i != offset):
            continue
        updated = (edited[offset] - edited_sum) & 255
        corrected = bytearray(edited)
        corrected[offset] = updated
        assert not sum(corrected) & 255
        basis = ('source ID table; no example independently checked' if ecm in HONDA_TABLE_ONLY_IDS else
                 'family-inferred; named example conflicts' if ecm in HONDA_FAMILY_INFERRED_IDS else
                 'source-named example inference' if ecm in HONDA_EXAMPLE_INFERRED_IDS else 'source table and example')
        conflict = HONDA_SOURCE_CONFLICTS.get(ecm, '')
        if ecm in HONDA_RESEARCH_EXAMPLE_PARTS:
            conflict = f"Source table part {part} differs from example filename {HONDA_RESEARCH_EXAMPLE_PARTS[ecm]}."
        if part == '38770-MGE-701':
            conflict = 'The 701 XDF filename conflicts with its embedded 773 title.'
        source = ('AlexKovalevich/HondaECU db0a6cb8' if ecm in HONDA_VFR_RESEARCH_IDS or ecm in HONDA_RESEARCH_COMMENTED_IDS else
                  'aeaphichart/HondaECU-1 b59ae98b; Alex checksum table for K26' if part.startswith('38770-K26-') else
                  'aeaphichart/HondaECU-1 b59ae98b')
        result.append({'ecm_id': ecm.hex().upper(), 'part': part, 'id_offset': id_offset,
                       'source': source,
                       'id_basis': basis, 'read_start': HONDA_RESEARCH_STARTS[ecm],
                       'checksum_offset': offset, 'before': edited[offset], 'after': updated,
                       'input_sum': edited_sum, 'output_sha256': hashlib.sha256(corrected).hexdigest(),
                       'conflict': conflict,
                       'commented': ecm in HONDA_RESEARCH_COMMENTED_IDS})
    return result
