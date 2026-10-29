"""Offline CBR1000RR 2012 US definition and image-specific checksum.

The checksum is adapted from Ryan Hope and HondaECU contributors' GPL-3.0
HondaECU.py at dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109. See
LICENSES/HondaECU-GPL-3.0.txt and docs/XDF_LIBRARY.md. This module does not
implement or enable communications with an ECU.
"""
from .checksums import ChecksumProvider, ChecksumUnavailable

XDF_NAME = 'CBR1000RR_2012_US.xdf'
XDF_SHA256 = 'c942ffc16e498985dba5592388e7cf6f2d23e2adde94fde825b52d1287141415'
# Hash only: the stock image is not redistributed by GuzziOnBoard.
SOURCE_SHA256 = 'c0fb37e60fbf38a8479166a5ef9ca0fdcc8b4f7c37de97f9dadaab1db0da0764'
ECU_ID = 'honda_cbr1000rr_2012_us'
CHECKSUM_OFFSET = 0x3fff8
IMAGE_SIZE = 0x40000


def _check_context(image: bytes, context: dict) -> None:
    if (len(image) != IMAGE_SIZE or context.get('address_base') != 0
            or context.get('xdf_sha256') != XDF_SHA256
            or context.get('source_sha256') != SOURCE_SHA256
            or context.get('declared_checksums') != ['Honda Checksum']):
        raise ChecksumUnavailable(
            'Honda checksum is limited to the pinned 2012 US XDF and '
            '38770-MGP-A01 source image, with a 256 KiB image and address base 0'
        )
    for change in context.get('changes', []):
        start = int(change['image_offset'], 0)
        length = len(bytes.fromhex(change['after_hex']))
        if start <= CHECKSUM_OFFSET < start + length:
            raise ChecksumUnavailable('calibration edits may not overlap the Honda checksum byte')


def update(image: bytes, context: dict) -> bytes:
    _check_context(image, context)
    result = bytearray(image)
    # HondaECU sums the whole image except the checksum byte and stores the
    # additive inverse at 0x3fff8. Consequently the whole-image sum is zero.
    result[CHECKSUM_OFFSET] = (-(sum(result) - result[CHECKSUM_OFFSET])) & 0xff
    return bytes(result)


def verify(image: bytes, context: dict) -> bool:
    _check_context(image, context)
    return sum(image) & 0xff == 0


def provider() -> ChecksumProvider:
    return ChecksumProvider(
        'honda-cbr1000rr-2012-us-a01-v1',
        'Honda CBR1000RR 2012 US / A01 checksum', '1.0.0',
        ('Honda Checksum',), update, verify, verified=False,
        note=('HondaECU 2012 US XDF and its repository 38770-MGP-A01 stock image '
              'only; requires exact XDF and original image SHA-256. Offline '
              'output tested; this integration has not been hardware-tested.'),
        source=('https://github.com/roccofz1/HondaECU/tree/'
                'dbb8d37bfb5dfd6d5d2b001ec44d8774063b9109'),
    )
