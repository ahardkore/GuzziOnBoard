"""ECU image checksum verification + opt-in, author-confirmed repair (offline research).

Source: NetworkDir/moto-ecu-checksum @ 0849357fbdee09779a8b1a910ee3cc29e03325e3
(MIT, LICENSES/Moto-ECU-checksum-MIT.txt; Round 16 in
docs/CAPTURE_SEARCH_2026-11-03.md plus Continental M3C PR #8).

POLICY: verify_* functions are read-only. The repair_* functions are
write-class and included ONLY because the upstream author confirms byte-identical
output vs. commercial flash tools / bench-tested images on the listed models.
They operate on local file images only; this module never communicates with an ECU.

Algorithms (9 families):
  - yamaha_mt:       whole-image 16-bit BE word sum must equal 0x5AA5 (1 MB)
                     or 0xE81F (896 KB); checksum word at end-8 after the
                     8-char software ID (byte end-12 == 'Y'), followed by 64 02.
  - honda_keihin:    one byte at end-8 makes the byte sum 0 mod 256 over the
                     whole image (X-ADV 750, 512 KB, "MKH") or 0x10000..end
                     (ADV350, 768 KB, "KN6" ID at end-0x80); tail 16 bytes FF
                     except the checksum byte.
  - bosch_mse6:      16-byte BE records [start][end][cs][~cs] found by
                     structure (cs ^ ~cs == 0xFFFFFFFF); cs = sum of 16-bit BE
                     words start..end inclusive mod 2^32. Self-invariant:
                     [cs][~cs] always contributes 0x1FFFE.
  - bosch_mse8:      256 KB cal block found by footer signature at block+0x3FFE0;
                     CRC-32 (zlib) of block[0..0x3FFF8) XOR 0xA18AFC77 stored
                     BE at block+0x3FFF8.
  - bosch_mg1:       blocks on 256 KB boundaries starting DEADBEEF, ending with
                     a 0x15C-byte 0x12345678 fill then BE CRC-32 (reflected,
                     poly 0xEDB88320, init 0xACC08E37, xorout 0xFFFFFFFF)
                     == zlib.crc32(block, 0x533F71C8) over block..fill end.
  - dellorto:        cal block at 0x80000 ("DellOrto 32bit Engine Management
                     System" signature); BE 16-bit one's complement of the byte
                     sum of 0x80000..0x921FD at 0x921FE.
  - qh250:           32 KB block at 0x0000 (starts AA AA, ends 55 54 AA 45);
                     BE 16-bit words 0x0000..0x7FEF sum to 0; checksum at 0x7FEE.
  - italjet_suzuki:  512 KB image; after the AA 55 CC 33 marker preceding the
                     12-char ASCII part number in 0x20000..end: LE 16-bit
                     checksum + complement; byte sum of 0x20000..end (value +
                     complement always adds 0x1FE).
  - continental_m3c: Continental (Siemens VDO) M3C on MC9S12X internal flash
                     (KTM / Husqvarna TPI two-strokes, e.g. TE300i 256 KB);
                     FF FF FF FF + BE16 CRC-16/MODBUS + BE16 count + count
                     banked [00 PP AAAA] start/end pairs on 16 KB PPAGE windows.
"""
from __future__ import annotations

import hashlib
import zlib

PROFILE = 'ecu_image_checksum_verify_only'


def _be16(b: bytes | bytearray, o: int) -> int:
    return (b[o] << 8) | b[o + 1]


def _le16(b: bytes | bytearray, o: int) -> int:
    return b[o] | (b[o + 1] << 8)


def _be32(b: bytes | bytearray, o: int) -> int:
    return int.from_bytes(b[o:o + 4], 'big')


_CRC16_MODBUS_TABLE: tuple[int, ...] | None = None


def _crc16_modbus(img: bytes | bytearray, ranges: list[tuple[int, int]]) -> int:
    global _CRC16_MODBUS_TABLE
    if _CRC16_MODBUS_TABLE is None:
        tbl = []
        for n in range(256):
            c = n
            for _ in range(8):
                c = ((c >> 1) ^ 0xA001) if (c & 1) else (c >> 1)
            tbl.append(c)
        _CRC16_MODBUS_TABLE = tuple(tbl)
    table = _CRC16_MODBUS_TABLE
    crc = 0xFFFF
    for start, end in ranges:
        for b in img[start:end + 1]:
            crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
    return crc


def verify_yamaha_mt(img: bytes):
    """Whole-image BE16 word-sum target 0x5AA5 (1 MB) / 0xE81F (896 KB)."""
    img = bytes(img)
    targets = {0x100000: 0x5AA5, 0xE0000: 0xE81F}
    n = len(img)
    if n not in targets or n % 2:
        return None
    if not all(0x30 <= img[n - 16 + i] <= 0x39 or 0x41 <= img[n - 16 + i] <= 0x5A for i in range(8)):
        return None
    if img[n - 12] != 0x59 or img[n - 6] != 0x64 or img[n - 5] != 0x02:
        return None
    loc = n - 8
    total = sum(_be16(img, i) for i in range(0, n, 2)) & 0xFFFF
    return {'algorithm': 'yamaha_mt', 'target': targets[n], 'word_sum': total,
            'stored': _be16(img, loc), 'checksum_offset': loc, 'ok': total == targets[n]}


def verify_honda_keihin(img: bytes):
    """Byte at end-8 makes byte sum 0 mod 256 (X-ADV whole image / ADV350 0x10000..end)."""
    img = bytes(img)
    n = len(img)
    models = [(0x80000, 0x0, img.find(b'MKH') >= 0, 'X-ADV 750'),
              (0xC0000, 0x10000, img[n - 0x80:n - 0x7D] == b'KN6', 'ADV350')]
    for size, start, matched, name in models:
        if n != size or not matched:
            continue
        if any(img[i] != 0xFF for i in range(n - 16, n) if i != n - 8):
            return None
        s = sum(img[start:n]) & 0xFF
        return {'algorithm': 'honda_keihin', 'model': name, 'byte_sum_mod256': s,
                'stored': img[n - 8], 'checksum_offset': n - 8, 'ok': s == 0}
    return None


def verify_bosch_mse6(img: bytes, scan_start=0x140000, scan_end=0x140400):
    """Structurally-found [start][end][cs][~cs] records; cs = BE16 word sum of region."""
    img = bytes(img)
    records = []
    limit = min(scan_end, len(img) - 16)
    for off in range(scan_start, limit + 1, 2):
        cs, ncs = _be32(img, off + 8), _be32(img, off + 12)
        if cs ^ ncs != 0xFFFFFFFF:
            continue
        start, end = _be32(img, off), _be32(img, off + 4)
        if not (0 <= start < end < len(img) and end - start >= 0x1000):
            continue
        stop = end if (end - start) % 2 == 1 else min(end + 1, len(img) - 1)
        computed = sum(_be16(img, i) for i in range(start, stop, 2)) & 0xFFFFFFFF
        records.append({'algorithm': 'bosch_mse6', 'record_offset': off,
                        'start': start, 'end': end, 'stored': cs,
                        'computed': computed, 'ok': cs == computed})
    return records


def verify_bosch_mse8(img: bytes):
    """256 KB cal block via footer signature at block+0x3FFE0; CRC32 ^ 0xA18AFC77 at +0x3FFF8."""
    img = bytes(img)
    for base in range(0, len(img) - 0x40000 + 1, 0x40000):
        footer = img[base + 0x3FFE0:base + 0x40000]
        stored = _be32(img, base + 0x3FFF8)
        if stored == 0 and not any(footer):   # no signature and no CRC: not a cal block
            continue
        computed = (zlib.crc32(img[base:base + 0x3FFF8]) ^ 0xA18AFC77) & 0xFFFFFFFF
        return {'algorithm': 'bosch_mse8', 'block': base,
                'checksum_offset': base + 0x3FFF8, 'stored': stored,
                'computed': computed, 'ok': stored == computed}
    return None


def verify_bosch_mg1(img: bytes):
    """DEADBEEF blocks on 256 KB boundaries; custom-init CRC-32 == zlib.crc32(block, 0x533F71C8)."""
    img = bytes(img)
    records = []
    fill = b'\x12\x34\x56\x78' * 0x57
    for base in range(0, len(img) - 0x400, 0x40000):
        if img[base:base + 4] != b'\xDE\xAD\xBE\xEF':
            continue
        end = min(base + 0x40000 - 4, len(img) - 4)
        while end > base + 0x15C and img[end - 0x15C:end] != fill:
            end -= 2
        if end <= base + 0x15C or img[end - 0x15C:end] != fill:
            continue
        stored = _be32(img, end)
        computed = zlib.crc32(img[base:end], 0x533F71C8) & 0xFFFFFFFF
        records.append({'algorithm': 'bosch_mg1', 'block': base, 'crc_offset': end,
                        'stored': stored, 'computed': computed, 'ok': stored == computed})
    return records


def verify_dellorto(img: bytes):
    """BE16 one's complement of byte sum 0x80000..0x921FD at 0x921FE."""
    img = bytes(img)
    if len(img) < 0x92200 or b'DellOrto 32bit Engine Management System' not in img[0x80000:0x921FE]:
        return None
    s = sum(img[0x80000:0x921FE]) & 0xFFFF
    stored = _be16(img, 0x921FE)
    computed = (~s) & 0xFFFF
    return {'algorithm': 'dellorto', 'checksum_offset': 0x921FE,
            'stored': stored, 'computed': computed, 'ok': stored == computed}


def verify_qh250(img: bytes):
    """BE16 words 0x0000..0x7FEF sum to 0; checksum at 0x7FEE; block ends 55 54 AA 45."""
    img = bytes(img)
    if len(img) < 0x8000 or img[0:2] != b'\xAA\xAA' or img[0x7FFC:0x8000] != b'\x55\x54\xAA\x45':
        return None
    total = sum(_be16(img, i) for i in range(0, 0x7FF0, 2)) & 0xFFFF
    return {'algorithm': 'qh250', 'checksum_offset': 0x7FEE,
            'stored': _be16(img, 0x7FEE), 'word_sum': total, 'ok': total == 0}


def _find_italjet_suzuki_loc(img: bytes | bytearray) -> int:
    if len(img) != 0x80000:
        return -1
    mark = b'\xAA\x55\xCC\x33'
    pos = img.find(mark, 0x20000)
    while pos != -1:
        loc = pos + 16
        if (loc + 4 <= len(img)
                and all(0x20 <= img[i] <= 0x7E for i in range(pos + 4, loc))
                and (_le16(img, loc) ^ _le16(img, loc + 2)) == 0xFFFF):
            return loc
        pos = img.find(mark, pos + 1)
    return -1


def _compute_italjet_suzuki(img: bytes | bytearray, loc: int) -> int:
    # Value and its 16-bit complement always contribute 0x1FE to the byte sum.
    body = sum(img[0x20000:loc]) + sum(img[loc + 4:])
    return (0x1FE + body) & 0xFFFF


def verify_italjet_suzuki(img: bytes):
    """LE16 checksum + complement after the AA55CC33 marker + 12-char part number."""
    img = bytes(img)
    loc = _find_italjet_suzuki_loc(img)
    if loc < 0:
        return None
    stored = _le16(img, loc)
    computed = _compute_italjet_suzuki(img, loc)
    return {'algorithm': 'italjet_suzuki', 'checksum_offset': loc,
            'stored': stored, 'computed': computed,
            'byte_sum_tail': sum(img[0x20000:]) & 0xFFFF, 'ok': stored == computed}


def _m3c_to_offset(addr: int, size: int) -> int:
    page = (addr >> 16) & 0xFF
    win = addr & 0xFFFF
    if (addr >> 24) or page < 0xE0 or not (0x8000 <= win <= 0xBFFF):
        return -1
    pages = size // 0x4000
    return (page % pages) * 0x4000 + (win - 0x8000)


def _find_continental_m3c(img: bytes | bytearray) -> list[dict]:
    n = len(img)
    if n < 0x10000 or n > 0x100000 or (n % 0x4000) != 0 or (n & (n - 1)) != 0:
        return []
    descriptors: list[dict] = []
    for off in range(4, n - 11, 0x100):
        if img[off - 4:off] != b'\xFF\xFF\xFF\xFF':
            continue
        count = _be16(img, off + 2)
        if not (1 <= count <= 32) or off + 4 + count * 8 > n:
            continue
        ranges: list[tuple[int, int]] = []
        addrs: list[tuple[int, int]] = []
        valid = True
        for k in range(count):
            p = off + 4 + k * 8
            sa, ea = _be32(img, p), _be32(img, p + 4)
            s, e = _m3c_to_offset(sa, n), _m3c_to_offset(ea, n)
            if s < 0 or e < s or (sa >> 16) != (ea >> 16) or (s <= off + 1 and e >= off):
                valid = False
                break
            ranges.append((s, e))
            addrs.append((sa, ea))
        if valid:
            descriptors.append({'offset': off, 'ranges': ranges, 'addrs': addrs})
    # Real M3C reads hold multiple segment descriptors (boot/code/calibration).
    return descriptors if len(descriptors) >= 2 else []


def verify_continental_m3c(img: bytes):
    """Continental M3C (MC9S12X) FFFFFFFF-prefixed banked CRC-16/MODBUS descriptors."""
    img = bytes(img)
    descriptors = _find_continental_m3c(img)
    if not descriptors:
        return []
    records = []
    for d in descriptors:
        stored = _be16(img, d['offset'])
        computed = _crc16_modbus(img, d['ranges'])
        sa0, _ = d['addrs'][0]
        _, ea_last = d['addrs'][-1]
        label = (
            f"CRC-16 ({len(d['addrs'])} range(s) "
            f"{(sa0 >> 16) & 0xFF:02X}:{sa0 & 0xFFFF:04X}.."
            f"{(ea_last >> 16) & 0xFF:02X}:{ea_last & 0xFFFF:04X})"
        )
        records.append({
            'algorithm': 'continental_m3c',
            'label': label,
            'checksum_offset': d['offset'],
            'start': min(s for s, _ in d['ranges']),
            'end': max(e for _, e in d['ranges']),
            'stored': stored,
            'computed': computed,
            'ok': stored == computed,
        })
    return records


# ---- Opt-in repair (author-confirmed; local file images only) -------------

def repair_yamaha_mt(img: bytes) -> bytes:
    img = bytearray(img)
    n = len(img)
    loc = n - 8
    base = sum(_be16(img, i) for i in range(0, n, 2) if i != loc) & 0xFFFF
    targets = {0x100000: 0x5AA5, 0xE0000: 0xE81F}
    v = (targets[n] - base) & 0xFFFF
    img[loc], img[loc + 1] = v >> 8, v & 0xFF
    return bytes(img)


def repair_honda_keihin(img: bytes) -> bytes:
    img = bytearray(img)
    n = len(img)
    start = 0 if n == 0x80000 else 0x10000
    img[n - 8] = 0
    img[n - 8] = (-sum(img[start:n])) & 0xFF
    return bytes(img)


def repair_bosch_mse6(img: bytes, scan_start=0x140000, scan_end=0x140400) -> bytes:
    img = bytearray(img)
    for rec in verify_bosch_mse6(bytes(img), scan_start, scan_end):
        if not rec['ok']:
            off = rec['record_offset']
            img[off + 8:off + 12] = rec['computed'].to_bytes(4, 'big')
            img[off + 12:off + 16] = (~rec['computed'] & 0xFFFFFFFF).to_bytes(4, 'big')
    return bytes(img)


def repair_bosch_mse8(img: bytes) -> bytes:
    img = bytearray(img)
    r = verify_bosch_mse8(bytes(img))
    if r and not r['ok']:
        base = r['block']
        img[base + 0x3FFF8:base + 0x3FFFC] = (r['computed'] & 0xFFFFFFFF).to_bytes(4, 'big')
    return bytes(img)


def repair_bosch_mg1(img: bytes) -> bytes:
    img = bytearray(img)
    for rec in verify_bosch_mg1(bytes(img)):
        if not rec['ok']:
            img[rec['crc_offset']:rec['crc_offset'] + 4] = rec['computed'].to_bytes(4, 'big')
    return bytes(img)


def repair_dellorto(img: bytes) -> bytes:
    img = bytearray(img)
    s = sum(img[0x80000:0x921FE]) & 0xFFFF
    img[0x921FE:0x92200] = ((~s) & 0xFFFF).to_bytes(2, 'big')
    return bytes(img)


def repair_qh250(img: bytes) -> bytes:
    img = bytearray(img)
    others = sum(_be16(img, i) for i in range(0, 0x7FF0, 2) if i != 0x7FEE) & 0xFFFF
    img[0x7FEE:0x7FF0] = ((-others) & 0xFFFF).to_bytes(2, 'big')
    return bytes(img)


def repair_italjet_suzuki(img: bytes) -> bytes:
    img = bytearray(img)
    loc = _find_italjet_suzuki_loc(img)
    if loc < 0:
        return bytes(img)
    v = _compute_italjet_suzuki(img, loc)
    img[loc:loc + 2] = v.to_bytes(2, 'little')
    img[loc + 2:loc + 4] = (~v & 0xFFFF).to_bytes(2, 'little')
    return bytes(img)


def repair_continental_m3c(img: bytes) -> bytes:
    img = bytearray(img)
    descriptors = _find_continental_m3c(img)
    if not descriptors:
        return bytes(img)
    # Two passes in case one segment's range covers another segment's CRC word.
    for _ in range(2):
        for d in descriptors:
            v = _crc16_modbus(img, d['ranges'])
            img[d['offset']:d['offset'] + 2] = v.to_bytes(2, 'big')
    return bytes(img)


REPAIRERS = {
    'yamaha_mt': repair_yamaha_mt,
    'honda_keihin': repair_honda_keihin,
    'bosch_mse6': repair_bosch_mse6,
    'bosch_mse8': repair_bosch_mse8,
    'bosch_mg1': repair_bosch_mg1,
    'dellorto': repair_dellorto,
    'qh250': repair_qh250,
    'italjet_suzuki': repair_italjet_suzuki,
    'continental_m3c': repair_continental_m3c,
}


VERIFIERS = {
    'yamaha_mt': verify_yamaha_mt,
    'honda_keihin': verify_honda_keihin,
    'bosch_mse6': verify_bosch_mse6,
    'bosch_mse8': verify_bosch_mse8,
    'bosch_mg1': verify_bosch_mg1,
    'dellorto': verify_dellorto,
    'qh250': verify_qh250,
    'italjet_suzuki': verify_italjet_suzuki,
    'continental_m3c': verify_continental_m3c,
}


ALGORITHM_METADATA = {
    'yamaha_mt': {
        'label': 'Yamaha MT series (1 MiB 0x5AA5 / 896 KiB 0xE81F word sum)',
        'tested': 'MT-25 2019, MT-07 2014-2021, MT-09 SP 2019',
        'caveat': 'Only the whole-image 16-bit word sum at end-8 is updated; cryptographic signatures and fitment are not verified.',
    },
    'honda_keihin': {
        'label': 'Honda Keihin modern (X-ADV 750 / ADV350 end-8 byte sum)',
        'tested': 'Honda X-ADV 750 2019 (MKH), ADV350 2024 (KN6)',
        'caveat': 'Only the single modulo-256 checksum byte at end-8 is updated; ECU fitment is not verified.',
    },
    'bosch_mse6': {
        'label': 'Bosch MSE6.0 ([start][end][cs][~cs] 16-bit word sum)',
        'tested': 'CFMoto NK250 2024, CFMoto 450SR 2023',
        'caveat': 'Repairs structural [start][end][cs][~cs] records only. Untouched 450SR factory reads can report mismatched records on 0x140000-0x14FFFF.',
    },
    'bosch_mse8': {
        'label': 'Bosch MSE8.0 / E186 (256 KiB calibration CRC-32 XOR 0xA18AFC77)',
        'tested': 'RKS RZ125S 2024 (F01RB0D2G0_XD105A1A25)',
        'caveat': 'Updates the 256 KiB calibration block CRC-32 at +0x3FFF8 only; signatures are not verified.',
    },
    'bosch_mg1': {
        'label': 'Bosch MG1 / MG1CA094 (DEADBEEF block CRC-32)',
        'tested': 'KTM Duke 390 2017, Bajaj Pulsar NS200 2018-2022, NS125, RS200',
        'caveat': 'Updates DEADBEEF block CRC-32 values only. MG1 ECUs also carry an FA FA signature block that must be handled by the flash tool.',
    },
    'dellorto': {
        'label': "Dell'Orto 32-bit EMS (0x80000..0x921FD byte sum complement)",
        'tested': 'Bajaj Pulsar RS200 2024 (JL351458010651)',
        'caveat': 'Updates only the 16-bit complement at 0x921FE; other regions and signatures are not verified.',
    },
    'qh250': {
        'label': 'QH250 (32 KiB 0x0000..0x7FEF BE16 zero-sum at 0x7FEE)',
        'tested': 'QH250 (E2400-05)',
        'caveat': 'Updates only the 16-bit word at 0x7FEE; fitment is not verified.',
    },
    'italjet_suzuki': {
        'label': 'Italjet / Suzuki-type (AA55CC33 LE16 tail byte sum + complement)',
        'tested': 'Italjet Dragster 200 2023 (5710BL01 / 33950-03K00)',
        'caveat': 'Updates only the 4-byte checksum + complement after the part-number marker.',
    },
    'continental_m3c': {
        'label': 'Continental M3C MC9S12X (FFFFFFFF banked CRC-16/MODBUS)',
        'tested': 'Husqvarna TE300i 2020 (KM557EU2025002)',
        'caveat': 'Updates FFFFFFFF-prefixed banked segment CRC-16 words only; boot/security signatures are not verified.',
    },
}


def verify_image(img: bytes):
    """Run every verifier; return {name: result-or-records} for recognised images."""
    out = {}
    for name, fn in VERIFIERS.items():
        r = fn(img)
        if r:
            out[name] = r
    return out


def _records_list(result) -> list[dict]:
    if not result:
        return []
    return list(result) if isinstance(result, list) else [result]


def _checksum_spans(algorithm: str, records: list[dict]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rec in records:
        if algorithm == 'bosch_mse6':
            spans.append((rec['record_offset'] + 8, 8))
        elif algorithm == 'bosch_mg1':
            spans.append((rec['crc_offset'], 4))
        elif algorithm == 'bosch_mse8':
            spans.append((rec['checksum_offset'], 4))
        elif algorithm == 'italjet_suzuki':
            spans.append((rec['checksum_offset'], 4))
        elif algorithm in ('yamaha_mt', 'dellorto', 'qh250', 'continental_m3c'):
            spans.append((rec['checksum_offset'], 2))
        elif algorithm == 'honda_keihin':
            spans.append((rec['checksum_offset'], 1))
    return spans


def proposals(original: bytes, candidate: bytes) -> list[dict]:
    """Return verified checksum-repair proposals for an edited research image.

    A family is proposed only when:
      1. ``original`` and ``candidate`` have equal length and differ in at least one byte;
      2. ``original`` matches the family's structural layout and already passes ``ok``
         (eliminating accidental heuristic collisions on unrelated ROMs);
      3. user edits do not directly overwrite the family's checksum bytes; and
      4. ``repair_*(candidate)`` re-verifies ``ok`` across all records and changes only
         bytes inside the declared checksum spans.
    """
    orig_b = bytes(original)
    cand_b = bytes(candidate)
    if len(orig_b) != len(cand_b) or orig_b == cand_b:
        return []
    diff_offsets = {i for i, (a, b) in enumerate(zip(orig_b, cand_b)) if a != b}
    results: list[dict] = []
    for family, verify_fn in VERIFIERS.items():
        orig_recs = _records_list(verify_fn(orig_b))
        if not orig_recs or not all(r.get('ok') for r in orig_recs):
            continue
        spans = _checksum_spans(family, orig_recs)
        if not spans:
            continue
        protected = {pos for start, length in spans for pos in range(start, start + length)}
        if diff_offsets & protected:
            continue
        repaired = REPAIRERS[family](cand_b)
        rep_recs = _records_list(verify_fn(repaired))
        if not rep_recs or not all(r.get('ok') for r in rep_recs):
            continue
        cs_diffs = {i for i, (a, b) in enumerate(zip(cand_b, repaired)) if a != b}
        if not cs_diffs <= protected:
            continue
        byte_changes = []
        for start, length in spans:
            before = cand_b[start:start + length]
            after = repaired[start:start + length]
            if before != after:
                byte_changes.append({
                    'offset': f'0x{start:X}',
                    'offset_int': start,
                    'length': length,
                    'before_hex': before.hex(),
                    'after_hex': after.hex(),
                })
        meta = ALGORITHM_METADATA[family]
        min_off = min(start for start, _ in spans)
        max_end = max(start + length for start, length in spans)
        results.append({
            'family': family,
            'label': meta['label'],
            'tested': meta['tested'],
            'caveat': meta['caveat'],
            'records_total': len(rep_recs),
            'checksum_start': min_off,
            'checksum_end_exclusive': max_end,
            'byte_changes': byte_changes,
            'already_valid': len(byte_changes) == 0,
            'output_sha256': hashlib.sha256(repaired).hexdigest(),
            'source': 'https://github.com/NetworkDir/moto-ecu-checksum/tree/0849357fbdee09779a8b1a910ee3cc29e03325e3',
        })
    return results


def inspect_and_propose(img: bytes, algorithm: str = 'auto') -> list[dict]:
    """Inspect a standalone binary image against one or all 9 checksum families."""
    data = bytes(img)
    names = list(VERIFIERS) if algorithm in ('', 'auto') else [algorithm]
    out: list[dict] = []
    for name in names:
        if name not in VERIFIERS:
            raise ValueError(f'unknown ECU checksum family {name!r}')
        recs = _records_list(VERIFIERS[name](data))
        if not recs:
            continue
        spans = _checksum_spans(name, recs)
        repaired = REPAIRERS[name](data)
        rep_recs = _records_list(VERIFIERS[name](repaired))
        repaired_ok = bool(rep_recs) and all(r.get('ok') for r in rep_recs)
        byte_changes = []
        for start, length in spans:
            before = data[start:start + length]
            after = repaired[start:start + length]
            if before != after:
                byte_changes.append({
                    'offset': f'0x{start:X}',
                    'offset_int': start,
                    'length': length,
                    'before_hex': before.hex(),
                    'after_hex': after.hex(),
                })
        meta = ALGORITHM_METADATA[name]
        out.append({
            'family': name,
            'label': meta['label'],
            'tested': meta['tested'],
            'caveat': meta['caveat'],
            'ok': all(r.get('ok') for r in recs),
            'records': recs,
            'repaired_ok': repaired_ok,
            'byte_changes': byte_changes,
            'output_sha256': hashlib.sha256(repaired).hexdigest() if repaired_ok else None,
            'source': 'https://github.com/NetworkDir/moto-ecu-checksum/tree/0849357fbdee09779a8b1a910ee3cc29e03325e3',
        })
    return out
