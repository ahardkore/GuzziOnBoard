"""EcmSpy Buell EEPROM read import: binary ``.epr`` and ``Reihe:`` hex dumps.

EcmSpy saves a Buell DDFI EEPROM read in one of two shapes:

* a binary ``.epr`` file holding the normal pages in ascending order; page
  zero, where the source layout has one, is *not* included, or
* a text dump whose first line names the ECM ID/version and a date, followed
  by ``Reihe: <page>`` sections of two-digit hex bytes, sixteen per line.

Both forms describe the same flat image the rest of this project reads and
writes as XPR.  This module turns either form into that flat image, checks it
against the bundled source page geometry, and saves an explicit research copy.

It never opens a serial port, never writes an ECU and never invents page-zero
bytes.  A read without page zero is flagged: the experimental write review
needs the complete layout, so an import that omits page zero can be inspected
in Maps but cannot be used to prepare a write.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from . import buell_ddfi, resources

#: Hard ceiling for a user-supplied read; the largest Buell layout is < 4 KiB.
MAX_READ_BYTES = 64 * 1024

PROFILE = 'buell_eeprom_import'

_HEADER = re.compile(r'^(?P<id>[A-Z0-9]{5})(?P<rest>[^\r\n]{0,120})$', re.IGNORECASE)
_SERIES = re.compile(r'^Reihe\s*:\s*(?P<page>[0-9]{1,2})$', re.IGNORECASE)
_DATE = re.compile(r'\b([0-9]{1,2}[-./][0-9]{1,2}[-./][0-9]{2,4})\b')
_HEX2 = re.compile(r'^[0-9A-Fa-f]{2}$')
#: Control bytes that never belong in a text dump.
_CONTROL = {chr(c) for c in range(32)} - {'\r', '\n', '\t'}


class BuellImportError(ValueError):
    """A read file could not be identified or failed its layout check."""


@dataclass(frozen=True)
class ImportedRead:
    """One imported EEPROM read and what is known about its geometry."""

    data: bytes
    ecm_id: str
    kind: str                      # 'epr-binary' | 'hex-dump'
    header: str = ''               # raw first line of a text dump
    date: str = ''                 # date as written in that header
    identification: str = 'explicit'   # 'explicit' | 'header' | 'filename' | 'size-only'
    pages: tuple[tuple[int, int], ...] = ()   # (page, size) actually present

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def page_zero_present(self) -> bool:
        return any(page == 0 for page, _ in self.pages)


def _normal_pages(ecm_id: str) -> list[tuple[int, int]]:
    return [(page, size) for page, size in buell_ddfi.IMAGE_LAYOUTS[ecm_id] if page]


def _page_zero_size(ecm_id: str) -> int:
    return next((size for page, size in buell_ddfi.IMAGE_LAYOUTS[ecm_id] if page == 0), 0)


def _normal_total(ecm_id: str) -> int:
    return sum(size for _, size in _normal_pages(ecm_id))


def _full_total(ecm_id: str) -> int:
    return sum(size for _, size in buell_ddfi.IMAGE_LAYOUTS[ecm_id])


def _assemble(pages: dict[int, bytes], ecm_id: str) -> bytes:
    """Normal pages ascending, then page zero, matching the XPR file layout."""
    out = bytearray()
    for page, _ in _normal_pages(ecm_id):
        out.extend(pages[page])
    if 0 in pages:
        out.extend(pages[0])
    return bytes(out)


def parse_hex_dump(text: str) -> ImportedRead:
    """Parse an EcmSpy ``Reihe:`` text dump into one flat image."""
    if not isinstance(text, str):
        raise BuellImportError('A hex dump must be text.')
    text = text.lstrip('\ufeff')
    if len(text) > MAX_READ_BYTES * 8:
        raise BuellImportError('Hex dump exceeds the import size limit.')
    if any(char in _CONTROL for char in text):
        raise BuellImportError('Hex dump contains control bytes; import the binary .epr instead.')
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise BuellImportError('The hex dump is empty.')
    header = lines[0].strip()
    match = _HEADER.match(header)
    ecm_id = match['id'].upper() if match else ''
    if ecm_id not in buell_ddfi.IMAGE_LAYOUTS:
        raise BuellImportError(
            'The first line does not start with a supported Buell ECM ID; '
            'a text dump cannot be assigned to a layout without it.'
        )
    date = _DATE.search(header)
    expected = dict(buell_ddfi.IMAGE_LAYOUTS[ecm_id])

    pages: dict[int, bytearray] = {}
    current: bytearray | None = None
    current_page = -1
    for number, raw in enumerate(lines[1:], start=2):
        line = raw.strip()
        if not line:
            continue
        series = _SERIES.match(line)
        if series:
            page = int(series['page'])
            if page not in expected:
                raise BuellImportError(f'Line {number}: page {page} is not part of the {ecm_id} layout.')
            if page in pages:
                raise BuellImportError(f'Line {number}: page {page} appears more than once.')
            current = pages[page] = bytearray()
            current_page = page
            continue
        if current is None:
            raise BuellImportError(f'Line {number}: data before the first "Reihe:" marker.')
        tokens = line.split()
        bad = next((token for token in tokens if not _HEX2.match(token)), None)
        if bad is not None:
            raise BuellImportError(f'Line {number}: {bad!r} is not a two-digit hex byte.')
        current.extend(int(token, 16) for token in tokens)
        if len(current) > expected[current_page]:
            raise BuellImportError(f'Line {number}: page data exceeds its {ecm_id} page size.')

    missing = [page for page in expected if page not in pages and page != 0]
    if missing:
        raise BuellImportError(f'Hex dump is incomplete; page(s) {missing} are missing.')
    for page, data in pages.items():
        if len(data) != expected[page]:
            raise BuellImportError(
                f'Page {page} has {len(data)} bytes; the {ecm_id} layout needs {expected[page]}.'
            )
    ordered = tuple(
        (page, len(pages[page])) for page, _ in _normal_pages(ecm_id) if page in pages
    ) + (((0, len(pages[0])),) if 0 in pages else ())
    return ImportedRead(
        data=_assemble({page: bytes(data) for page, data in pages.items()}, ecm_id),
        ecm_id=ecm_id,
        kind='hex-dump',
        header=header,
        date=date.group(1) if date else '',
        identification='header',
        pages=ordered,
    )


def _candidate_layouts(size: int) -> tuple[list[str], list[str]]:
    normal = [ecm for ecm in buell_ddfi.IMAGE_LAYOUTS if _normal_total(ecm) == size]
    full = [ecm for ecm in buell_ddfi.IMAGE_LAYOUTS if _full_total(ecm) == size]
    return normal, full


def _filename_hint(path: Path) -> str | None:
    name = path.name.upper()
    for ecm_id in sorted(buell_ddfi.IMAGE_LAYOUTS, key=len, reverse=True):
        if name.startswith(ecm_id):
            return ecm_id
    return None


def parse_binary(data: bytes, *, ecm_id: str | None = None, name: str = '') -> ImportedRead:
    """Check a binary read against a page layout and return it unchanged."""
    size = len(data)
    if not size:
        raise BuellImportError('The EEPROM read is empty.')
    if size > MAX_READ_BYTES:
        raise BuellImportError('The EEPROM read exceeds the import size limit.')
    normal, full = _candidate_layouts(size)
    identification = 'explicit'
    if ecm_id is not None:
        if ecm_id not in buell_ddfi.IMAGE_LAYOUTS:
            raise BuellImportError('That ECM ID has no bundled source page layout.')
        if size not in (_normal_total(ecm_id), _full_total(ecm_id)):
            raise BuellImportError(
                f'{size} bytes do not match the {ecm_id} layout '
                f'({_normal_total(ecm_id)} without page zero, {_full_total(ecm_id)} with it).'
            )
    else:
        hint = _filename_hint(Path(name)) if name else None
        if hint and hint in normal + full:
            ecm_id, identification = hint, 'filename'
        else:
            every = sorted(set(normal) | set(full))
            if len(every) != 1:
                raise BuellImportError(
                    f'{size} bytes matches several layouts or none '
                    f'({", ".join(every) if every else "no bundled layout"}); '
                    'enter the ECM ID explicitly.'
                )
            ecm_id, identification = every[0], 'size-only'
    assert ecm_id is not None
    page_zero = _page_zero_size(ecm_id)
    has_page_zero = bool(page_zero) and size == _full_total(ecm_id)
    if has_page_zero:
        pages = tuple((page, page_size) for page, page_size in _normal_pages(ecm_id)) + ((0, page_zero),)
    else:
        pages = tuple(_normal_pages(ecm_id))
    return ImportedRead(data=bytes(data), ecm_id=ecm_id, kind='epr-binary',
                        identification=identification, pages=pages)


def _read_text(data: bytes) -> str | None:
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return None
    if 'Reihe' in text[:4096]:
        return text
    return None


def load_read(path: str | Path, ecm_id: str | None = None) -> ImportedRead:
    """Read an ``.epr``/hex-dump file from disk and identify its layout."""
    if not isinstance(path, (str, Path)) or (isinstance(path, str) and not path.strip()):
        raise BuellImportError('Choose a local EcmSpy .epr or hex-dump file.')
    if ecm_id is not None and not isinstance(ecm_id, str):
        raise BuellImportError('An ECM ID must be text, for example BUEIB.')
    path = Path(path)
    if not path.is_absolute():
        raise BuellImportError('The read path must be absolute.')
    try:
        with path.open('rb') as handle:
            data = handle.read(MAX_READ_BYTES + 1)
    except OSError as exc:
        raise BuellImportError(f'Cannot read the EEPROM read: {exc}') from exc
    if len(data) > MAX_READ_BYTES:
        raise BuellImportError('The EEPROM read exceeds the import size limit.')
    text = _read_text(data)
    if text is not None:
        return parse_hex_dump(text)
    if ecm_id:
        ecm_id = ecm_id.strip().upper()
        if len(ecm_id) != 5:
            raise BuellImportError('An ECM ID is five characters, for example BUEIB.')
    return parse_binary(data, ecm_id=ecm_id or None, name=path.name)


def describe(read: ImportedRead, *, saved_path: str | None = None) -> dict:
    """Return the operator-facing report for one imported read."""
    from .buell_burn import MAP_DEFINITIONS

    page_zero = _page_zero_size(read.ecm_id)
    warnings = [
        'Imported files are unverified third-party data. The geometry check only '
        'proves the byte count, not the ECM identity, fitment, checksum or values.',
    ]
    if page_zero and not read.page_zero_present:
        warnings.append(
            f'Page zero ({page_zero} bytes) is absent, as in this EcmSpy form. '
            'The image can be inspected in Maps but cannot be used for the '
            'experimental write review, which requires the complete XPR layout.'
        )
    if read.kind == 'epr-binary':
        warnings.append(
            'A binary .epr carries no ECM ID. The layout was chosen from '
            + ('the filename, not the contents; '
               if read.identification == 'filename'
               else 'the byte count alone; ')
            + 'confirm the actual ECM before trusting the tables.'
        )
    return {
        'profile': PROFILE,
        'ecm_id': read.ecm_id,
        'kind': read.kind,
        'identification': read.identification,
        'header': read.header,
        'date': read.date,
        'size': len(read.data),
        'sha256': read.sha256,
        'pages': [{'page': page, 'size': size} for page, size in read.pages],
        'missing_page_zero': bool(page_zero and not read.page_zero_present),
        'page_zero_size': page_zero,
        'map_xdf': MAP_DEFINITIONS[read.ecm_id] + '_source_research.xdf',
        'saved_path': saved_path,
        'address_base': 0,
        'synthetic_tested': True,
        'warnings': warnings,
    }


def save_import(read: ImportedRead, folder: str | Path | None = None) -> str:
    """Write an imported read to a new research copy and return its path."""
    if not isinstance(read, ImportedRead):
        raise BuellImportError('Only a parsed Buell import can be saved.')
    target = Path(folder) if folder is not None else resources.data_root() / 'buell-imports'
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = 'xpr' if read.page_zero_present else 'bin'
    path = target / (
        f'{read.ecm_id}-epr-import-{int(time.time())}-{secrets.token_hex(8)}.{suffix}'
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(read.data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)
