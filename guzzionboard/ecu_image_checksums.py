"""ECU image checksum verification + opt-in, author-confirmed repair (offline research).

Source: NetworkDir/moto-ecu-checksum @ pinned commit (Round 16 in
docs/CAPTURE_SEARCH_2026-11-03.md); no license stated — treated as open per
the project license policy (modifiable/removable later if the author advises
otherwise). Algorithms reimplemented from the verify() side only, cited.

POLICY: verify_* functions are read-only. The repair_* functions are
write-class and included ONLY because the upstream author indicates success
(byte-identical MD5 vs. commercial flash tools / flashed-and-running on the
listed models — see Round 16). They operate on local file images only; this
app never writes to an ECU.

Algorithms (all verify-only):
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
  - italjet_suzuki:  after the AA 55 CC 33 marker preceding the 12-char part
                     number: LE 16-bit checksum + complement; byte sum of
                     0x20000..end is invariant (value+complement = 0x1FE).
"""
from __future__ import annotations

import zlib

PROFILE = 'ecu_image_checksum_verify_only'


def _be16(b, o): return (b[o] << 8) | b[o + 1]
def _le16(b, o): return b[o] | (b[o + 1] << 8)
def _be32(b, o): return int.from_bytes(b[o:o + 4], 'big')


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
            'checksum_offset': loc, 'ok': total == targets[n]}


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
                'checksum_offset': n - 8, 'ok': s == 0}
    return None


def verify_bosch_mse6(img: bytes, scan_start=0x140000, scan_end=0x140400):
    """Structurally-found [start][end][cs][~cs] records; cs = BE16 word sum of region."""
    img = bytes(img)
    records = []
    for off in range(scan_start, min(scan_end, len(img) - 16), 2):
        cs, ncs = _be32(img, off + 8), _be32(img, off + 12)
        if cs ^ ncs != 0xFFFFFFFF:
            continue
        start, end = _be32(img, off), _be32(img, off + 4)
        if not (0 <= start < end < len(img) and end - start >= 0x1000):
            continue
        computed = sum(_be16(img, i) for i in range(start, end + 1, 2)) & 0xFFFFFFFF
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
        computed = zlib.crc32(img[base:base + 0x3FFF8]) ^ 0xA18AFC77
        return {'algorithm': 'bosch_mse8', 'block': base, 'stored': stored,
                'computed': computed & 0xFFFFFFFF, 'ok': stored == (computed & 0xFFFFFFFF)}
    return None


def verify_bosch_mg1(img: bytes):
    """DEADBEEF blocks on 256 KB boundaries; custom-init CRC-32 == zlib.crc32(block, 0x533F71C8)."""
    img = bytes(img)
    records = []
    for base in range(0, len(img) - 0x400, 0x40000):
        if img[base:base + 4] != b'\xDE\xAD\xBE\xEF':
            continue
        end = base + 0x40000 - 4
        while end > base and img[end - 0x15C:end] != b'\x12\x34\x56\x78' * 0x57:
            end -= 2
        if end <= base:
            continue
        stored = _be32(img, end)
        computed = zlib.crc32(img[base:end], 0x533F71C8) & 0xFFFFFFFF
        records.append({'algorithm': 'bosch_mg1', 'block': base, 'crc_offset': end,
                        'stored': stored, 'computed': computed, 'ok': stored == computed})
    return records


def verify_dellorto(img: bytes):
    """BE16 one's complement of byte sum 0x80000..0x921FD at 0x921FE."""
    img = bytes(img)
    if len(img) < 0x92200 or b'DellOrto 32bit Engine Management System' not in img[0x80000:0x80040]:
        return None
    s = sum(img[0x80000:0x921FE]) & 0xFFFF
    stored = _be16(img, 0x921FE)
    computed = (~s) & 0xFFFF
    return {'algorithm': 'dellorto', 'stored': stored, 'computed': computed, 'ok': stored == computed}


def verify_qh250(img: bytes):
    """BE16 words 0x0000..0x7FEF sum to 0; checksum at 0x7FEE; block ends 55 54 AA 45."""
    img = bytes(img)
    if len(img) < 0x8000 or img[0:2] != b'\xAA\xAA' or img[0x7FFC:0x8000] != b'\x55\x54\xAA\x45':
        return None
    total = sum(_be16(img, i) for i in range(0, 0x7FF0, 2)) & 0xFFFF
    return {'algorithm': 'qh250', 'word_sum': total, 'ok': total == 0}


def verify_italjet_suzuki(img: bytes):
    """LE16 checksum + complement after the AA55CC33 marker before the part number."""
    img = bytes(img)
    mark = b'\xAA\x55\xCC\x33'
    pos = img.find(mark, 0, max(0, len(img) - 0x20000))
    while pos != -1:
        loc = pos + 4 + 12
        if loc + 4 <= len(img):
            stored, compl = _le16(img, loc), _le16(img, loc + 2)
            if stored ^ compl == 0xFFFF:
                total = sum(img[0x20000:]) & 0xFFFF
                return {'algorithm': 'italjet_suzuki', 'checksum_offset': loc,
                        'stored': stored, 'byte_sum_tail': total, 'ok': True}
        pos = img.find(mark, pos + 1, max(0, len(img) - 0x20000))
    return None


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
    mark = b'\xAA\x55\xCC\x33'
    pos = img.find(mark, 0, max(0, len(img) - 0x20000))
    while pos != -1:
        loc = pos + 4 + 12
        if loc + 4 <= len(img) and _le16(img, loc) ^ _le16(img, loc + 2) == 0xFFFF:
            v = sum(img[0x20000:loc]) & 0xFFFF   # value+complement always adds 0x1FE
            img[loc:loc + 2] = v.to_bytes(2, 'little')
            img[loc + 2:loc + 4] = (~v & 0xFFFF).to_bytes(2, 'little')
            return bytes(img)
        pos = img.find(mark, pos + 1, max(0, len(img) - 0x20000))
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
}


def verify_image(img: bytes):
    """Run every verifier; return {name: result-or-records} for recognised images."""
    out = {}
    for name, fn in VERIFIERS.items():
        r = fn(img)
        if r:
            out[name] = r
    return out
