"""Offline MGZ-A03 checksum, adapted from HondaECU GPL-3.0.

See LICENSES/HondaECU-GPL-3.0.txt and docs/XDF_LIBRARY.md. No ECU I/O.
"""
from .checksums import ChecksumProvider, ChecksumUnavailable

XDF_NAME = 'CB500_MGZ_A03_gob.xdf'
XDF_SHA256 = '8a40a493f0766bab53dfa74d4a34d4a473e126011eb770553ece598d88f61426'
SOURCE_SHA256 = '4b402f033a03fa3898d3bd016ae73209884e32706a98ca646f78b29b526d3259'
ECU_ID = 'honda_cb500_mgz_a03'
IMAGE_SIZE = 0x40000
CHECKSUM_OFFSET = 0x3fff8
CHECKSUM_NAME = 'Honda MGZ-A03 checksum'


def _check(image, context):
    if (len(image) != IMAGE_SIZE or context.get('address_base') != 0
            or context.get('xdf_sha256') != XDF_SHA256
            or context.get('source_sha256') != SOURCE_SHA256
            or context.get('declared_checksums') != [CHECKSUM_NAME]):
        raise ChecksumUnavailable('MGZ checksum requires the pinned MGZ-A03 XDF and original image, 256 KiB, base 0')
    for change in context.get('changes', []):
        start = int(change['image_offset'], 0)
        if start <= CHECKSUM_OFFSET < start + len(bytes.fromhex(change['after_hex'])):
            raise ChecksumUnavailable('calibration edits may not overlap the MGZ checksum byte')


def update(image, context):
    _check(image, context)
    output = bytearray(image)
    output[CHECKSUM_OFFSET] = (-(sum(output) - output[CHECKSUM_OFFSET])) & 0xff
    return bytes(output)


def verify(image, context):
    _check(image, context)
    return sum(image) & 0xff == 0


def provider():
    return ChecksumProvider('honda-cb500-mgz-a03-v1', 'Honda CB500 / CBR500 MGZ-A03 checksum',
        '1.0.0', (CHECKSUM_NAME,), update, verify, verified=False,
        note='Only the pinned modified XDF and the exact HondaECU MGZ-A03 original image; offline only, no hardware validation.',
        source='https://github.com/aeaphichart/HondaECU-1/tree/b59ae98baf092def23d7c34d5ef5f43bd6aba952')
