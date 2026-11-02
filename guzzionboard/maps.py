"""TunerPro XDF map definitions: parse, render and diff.

The GuzziDiag ecosystem standardised on TunerPro for map editing, and the
von-der-salierburg archive publishes XDF (XML) definition files for every
Guzzi family - P7/P8/16M/15M/15RC/5AM/MIU G3/7SM. Each XDF names every table
in a dump - fuel and ignition maps, lambda targets, corrections - with
addresses, scaling and units.

This module turns those definitions into data:

* :class:`XdfFile` parses an XDF (format as written by TunerPro v5,
  ``<XDFFORMAT version="1.60">``; the structure was read off a real file,
  see ``docs/PRIOR_ART.md`` 3);
* :meth:`XdfFile.render` maps a dump onto the definitions and returns every
  table with its axis labels and engineering values; an axis that TunerPro
  links to a *legend* table (``<embedinfo type="3" linkobjid="0x7FDD" />``)
  is labelled with that legend's own engineering values, so a row header
  reads "82" (its engine temperature) instead of "13" (its index);
* :meth:`XdfFile.diff` compares two dumps and reports *named* changes -
  "Spark High-Octane Table, row 1200 RPM, col 0.84 g/cyl: 28.1 -> 30.0"
  instead of "run at 0xF1BE, 2 bytes".

XDFs are third-party files. A growing set ships with this project under
``guzzionboard/xdfs/`` (see ``docs/XDF_LIBRARY.md`` for provenance and how to
add more) — :func:`available_xdfs` finds those automatically. Anything not
(yet) bundled can still be dropped into ``~/.guzzionboard/xdfs/`` the same way
key providers go into ``~/.guzzionboard/keys/``; a user-supplied file with the
same filename overrides a bundled one. The GuzziDiag definitions originate at
https://www.von-der-salierburg.de/download/GuzziDiag/; see docs/XDF_LIBRARY.md
for other sources and licensing.

One wrinkle worth understanding: XDF addresses are offsets into the *file
the XDF was authored against* - usually the full device image including the
bootloader. A GuzziOnBoard flash read is the 0x4C000-byte region starting at
device 0x4000, so rendering a region dump needs ``address_base=0x4000``.
That base is auto-detected from the image size and always reported back.
"""
from __future__ import annotations

import hashlib

from . import resources

import math
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

#: Where user-supplied XDFs are looked for, mirroring the key plugin dir.
XDF_DIR = resources.data_root() / "xdfs"

#: XDFs vendored into the project itself, see docs/XDF_LIBRARY.md.
BUNDLED_XDF_DIR = Path(__file__).resolve().parent / "xdfs"


class XdfError(Exception):
    """An XDF or image could not be interpreted."""


# Generous limits for user-supplied definitions. Checked before constructing
# axis labels, layout positions, or an XML tree, not just before rendering.
MAX_XDF_BYTES = 8 * 1024 * 1024
MAX_XDF_AXIS = 65_536
MAX_XDF_CELLS = 262_144
MAX_XDF_NODES = 100_000
MAX_XDF_DEPTH = 64


class _BoundedXmlTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.nodes = 0
        self.depth = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        if self.nodes > MAX_XDF_NODES or self.depth > MAX_XDF_DEPTH:
            raise XdfError("XDF XML structure exceeds supported limits")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)


def read_xdf_bytes(path: str | Path) -> bytes:
    """Read a bounded XDF once, preserving the bytes used for its digest."""
    try:
        with Path(path).open('rb') as file:
            raw = file.read(MAX_XDF_BYTES + 1)
    except OSError as exc:
        raise XdfError(f"cannot read {path}: {exc}") from exc
    if len(raw) > MAX_XDF_BYTES:
        raise XdfError("XDF exceeds the 8 MiB definition limit")
    return raw


# --------------------------------------------------------------------------
# The MATH equation: "X/4096", "X*0.05859372", ...
# --------------------------------------------------------------------------
#
# Only value-only equations are supported (a bare X plus arithmetic). The
# per-cell "<VAR type=\"address\">" form used by a few information tables
# references other locations and is reported as unsupported rather than
# guessed at.

_MATH_ALLOWED = re.compile(r"^[0-9A-Fa-fXx+\-*/().<> ]+$")
_HEX_LITERAL = re.compile(r"\b0[xX]([0-9A-Fa-f]+)\b")
_VAR_X = re.compile(r"\b[Xx]\b")
_THAT_CALL = re.compile(
    r"\bTHAT\s*\(\s*(0[xX][0-9A-Fa-f]+|[0-9]+)\s*[;,]\s*"
    r"ROW\s*\(\s*\)\s*[;,]\s*COL\s*\(\s*\)\s*[;,]\s*"
    r"(TRUE|FALSE|0|1)\s*\)",
    re.IGNORECASE,
)


def _math_equation(node: ET.Element) -> str:
    """The equation of a MATH element: <MATH equation="X/4096">."""
    math = node.find("MATH")
    if math is None:
        return "X"
    return (math.get("equation") or "X").strip()


def _prepare_scalar_math(equation: str) -> tuple[str, bool]:
    """Validate and normalise a scalar XDF equation (hex literals + shifts)."""
    if not isinstance(equation, str) or not equation.strip() or len(equation) > 256:
        raise XdfError(f"unsupported equation {equation!r}")
    if not _MATH_ALLOWED.fullmatch(equation):
        raise XdfError(f"unsupported equation {equation!r}")
    if "**" in equation or "//" in equation or "<>" in equation or "><" in equation:
        raise XdfError(f"unsupported equation {equation!r}")
    # Only paired bit-shifts (<< or >>) may use angle brackets; bare < or > is
    # comparison syntax and is rejected.
    stripped_shifts = equation.replace("<<", " ").replace(">>", " ")
    if "<" in stripped_shifts or ">" in stripped_shifts or "<<<" in equation or ">>>" in equation:
        raise XdfError(f"unsupported equation {equation!r}")

    def _hex_to_dec(match: re.Match[str]) -> str:
        return str(int(match.group(1), 16))

    normalised = _HEX_LITERAL.sub(_hex_to_dec, equation)
    # Any remaining hex letters other than standalone X/x are invalid tokens.
    without_x = _VAR_X.sub("0", normalised)
    if re.search(r"[A-Za-z]", without_x):
        raise XdfError(f"unsupported equation {equation!r}")
    has_shifts = "<<" in normalised or ">>" in normalised
    expr = _VAR_X.sub("(X)", normalised).replace(" ", "")
    return expr, has_shifts


def eval_math(equation: str, x: float) -> float:
    """Evaluate a TunerPro MATH equation for one raw value."""
    expr, has_shifts = _prepare_scalar_math(equation)
    try:
        if has_shifts:
            val_f = float(x)
            if not math.isfinite(val_f):
                raise ValueError("non-finite input")
            x_val: int | float = int(round(val_f))
        else:
            x_val = float(x)
        result = float(eval(expr, {"__builtins__": {}}, {"X": x_val}))  # noqa: S307
        if not math.isfinite(result):
            raise ValueError("non-finite result")
        return result
    except (ArithmeticError, ValueError, TypeError, SyntaxError, RecursionError) as exc:
        raise XdfError(f"equation {equation!r} failed on {x}: {exc}") from exc


def inverse_float_math(
    equation: str,
    value: float,
    *,
    size_bits: int = 32,
    little_endian: bool = True,
    decimalpl: int | None = None,
) -> tuple[float, float]:
    """Find the IEEE-754 32-bit or 64-bit float raw value for ``value``."""
    try:
        wanted = float(value)
    except (TypeError, ValueError):
        raise XdfError(f"value {value!r} is not a number") from None
    if not math.isfinite(wanted):
        raise XdfError("value must be finite")
    if size_bits not in (32, 64):
        raise XdfError(f"unsupported floating-point size {size_bits} bits")

    fmt = ("<" if little_endian else ">") + ("f" if size_bits == 32 else "d")

    def pack_roundtrip(raw_val: float) -> float | None:
        if not math.isfinite(raw_val):
            return None
        try:
            return struct.unpack(fmt, struct.pack(fmt, float(raw_val)))[0]
        except (struct.error, OverflowError, ValueError):
            return None

    def shown(v: float) -> float:
        return round(v, decimalpl) if decimalpl is not None else v

    candidates: list[float] = []

    def add_candidate(raw_val: float) -> None:
        q = pack_roundtrip(raw_val)
        if q is not None and math.isfinite(q):
            candidates.append(q)

    add_candidate(wanted)
    add_candidate(0.0)
    # Exact affine solution when f(X) = a*X + b.
    pts = []
    for probe in (0.0, 1.0, 2.0):
        try:
            pts.append((probe, eval_math(equation, probe)))
        except XdfError:
            pass
    if len(pts) == 3:
        s1 = pts[1][1] - pts[0][1]
        s2 = pts[2][1] - pts[1][1]
        if s1 and math.isclose(s1, s2, rel_tol=1e-11, abs_tol=1e-11):
            add_candidate((wanted - pts[0][1]) / s1)

    # Secant / bisection fallback for non-zero reciprocal or scaled forms.
    for lo_init, hi_init in ((-1e6, -1e-6), (1e-6, 1e6), (-1e6, 1e6)):
        try:
            flo = eval_math(equation, lo_init) - wanted
            fhi = eval_math(equation, hi_init) - wanted
        except XdfError:
            continue
        if flo == 0:
            add_candidate(lo_init)
            continue
        if fhi == 0:
            add_candidate(hi_init)
            continue
        if (flo < 0) == (fhi < 0):
            continue
        lo, hi = lo_init, hi_init
        for _ in range(64):
            mid = 0.5 * (lo + hi)
            try:
                fmid = eval_math(equation, mid) - wanted
            except XdfError:
                break
            if fmid == 0:
                lo = hi = mid
                break
            if (fmid < 0) == (flo < 0):
                lo, flo = mid, fmid
            else:
                hi, fhi = mid, fmid
        add_candidate(0.5 * (lo + hi))

    evaluated: list[tuple[float, float]] = []
    for raw_q in candidates:
        try:
            eng = eval_math(equation, raw_q)
        except XdfError:
            continue
        if math.isfinite(eng):
            evaluated.append((raw_q, eng))
    if not evaluated:
        raise XdfError(f"equation {equation!r} has no usable float values")

    raw_best, eng_best = min(evaluated, key=lambda pair: abs(shown(pair[1]) - wanted))
    actual = shown(eng_best)
    rel_eps = 1e-5 if size_bits == 32 else 1e-11
    display_quantum = 10 ** (-decimalpl) if decimalpl is not None else 0.0
    tolerance = max(display_quantum / 2, abs(wanted) * rel_eps, 1e-6 if size_bits == 32 else 1e-11)
    if abs(actual - wanted) > tolerance:
        raise XdfError(
            f"{value!r} cannot be represented by {size_bits}-bit IEEE-754 float "
            f"through {equation!r}; nearest is {actual:g}"
        )
    return raw_best, actual


def inverse_math(
    equation: str,
    value: float,
    *,
    size_bits: int,
    signed: bool,
    decimalpl: int | None = None,
    prior_raw: int | None = None,
) -> tuple[int, float]:
    """Find the integer XDF raw value nearest an engineering value.

    XDF equations in the bundled library are overwhelmingly affine
    (``X/10``, ``X-40``) with a handful of reciprocal and bit-shifted forms.
    Rather than rewriting user-supplied expressions or silently truncating,
    this function evaluates the already-sandboxed equation and searches each
    monotonic raw domain.  The result is accepted only when it is representable
    to within half of one raw step.  The returned engineering value is the
    value that will actually be displayed after quantisation.
    """
    try:
        wanted = float(value)
    except (TypeError, ValueError):
        raise XdfError(f"value {value!r} is not a number") from None
    if not math.isfinite(wanted):
        raise XdfError("value must be finite")
    if size_bits not in (8, 16, 32):
        raise XdfError(f"unsupported element size {size_bits} bits")

    if signed:
        low, high = -(1 << (size_bits - 1)), (1 << (size_bits - 1)) - 1
    else:
        low, high = 0, (1 << size_bits) - 1

    def engineering(raw: int) -> float | None:
        try:
            result = eval_math(equation, raw)
        except XdfError:
            return None
        return result if math.isfinite(result) else None

    candidates: set[int] = {low, high}
    if low <= 0 <= high:
        candidates.add(0)
    if prior_raw is not None and low <= prior_raw <= high:
        candidates.add(int(prior_raw))
    for raw in (-2, -1, 1, 2, 3):
        if low <= raw <= high:
            candidates.add(raw)

    # Bit-shift seed: for equations like ``X >> 4``, preserve the low bits of
    # ``prior_raw`` when available and also probe exact shift boundaries.
    shift_match = re.fullmatch(r"\s*[Xx]\s*>>\s*([0-9]+)\s*", equation)
    if shift_match:
        shift = int(shift_match.group(1))
        if 0 <= shift < size_bits and math.isfinite(wanted):
            base_shifted = int(round(wanted)) << shift
            if low <= base_shifted <= high:
                candidates.add(base_shifted)
            if prior_raw is not None:
                preserved = base_shifted | (int(prior_raw) & ((1 << shift) - 1))
                if low <= preserved <= high:
                    candidates.add(preserved)

    # Fast exact solution for affine equations.  Checking three consecutive
    # points proves the local slope and the final representability check keeps
    # a non-linear expression from being accepted on a coincidence.
    points = [(raw, engineering(raw)) for raw in (1, 2, 3) if low <= raw <= high]
    if len(points) == 3 and all(v is not None for _, v in points):
        slope_a = points[1][1] - points[0][1]
        slope_b = points[2][1] - points[1][1]
        if slope_a and math.isclose(slope_a, slope_b, rel_tol=1e-12, abs_tol=1e-12):
            intercept = points[0][1] - slope_a * points[0][0]
            estimate = (wanted - intercept) / slope_a
            if math.isfinite(estimate):
                rounded = round(estimate)
                for raw in range(rounded - 2, rounded + 3):
                    if low <= raw <= high:
                        candidates.add(raw)

    # Search negative and positive domains separately so reciprocal equations
    # never cross their undefined point at zero.  This also handles X*X,
    # which is monotonic on each side even though it is not globally so.
    domains: list[tuple[int, int]] = []
    if low <= -1:
        domains.append((low, min(high, -1)))
    if low <= 0 <= high and engineering(0) is not None:
        domains.append((0, 0))
    if high >= 1:
        domains.append((max(low, 1), high))

    for start, end in domains:
        if start == end:
            candidates.add(start)
            continue
        first, last = engineering(start), engineering(end)
        if first is None or last is None:
            continue
        ascending = last >= first
        lo, hi = start, end
        # Integer binary search.  Sixty-four iterations covers 32-bit domains
        # and costs the same regardless of table size.
        while lo <= hi:
            mid = (lo + hi) // 2
            current = engineering(mid)
            if current is None:
                break
            candidates.add(mid)
            if current == wanted:
                lo = hi = mid
                break
            if (current < wanted) == ascending:
                lo = mid + 1
            else:
                hi = mid - 1
        for raw in range(max(start, hi - 2), min(end, lo + 2) + 1):
            candidates.add(raw)

    evaluated = [(raw, engineering(raw)) for raw in candidates]
    evaluated = [(raw, val) for raw, val in evaluated if val is not None]
    if not evaluated:
        raise XdfError(f"equation {equation!r} has no usable raw values")

    def shown(v: float) -> float:
        return round(v, decimalpl) if decimalpl is not None else v

    raw, actual_unrounded = min(
        evaluated,
        key=lambda pair: (
            abs(shown(pair[1]) - wanted),
            abs(pair[0] - prior_raw) if prior_raw is not None else abs(pair[0]),
        ),
    )
    actual = shown(actual_unrounded)

    neighbours = []
    for adjacent in (raw - 1, raw + 1):
        if low <= adjacent <= high:
            adjacent_value = engineering(adjacent)
            if adjacent_value is not None:
                neighbours.append(abs(shown(adjacent_value) - actual))
    quantum = min((q for q in neighbours if q > 0), default=0.0)
    display_quantum = 10 ** (-decimalpl) if decimalpl is not None else 0.0
    tolerance = max(quantum / 2, display_quantum / 2, 1e-9)
    if abs(actual - wanted) > tolerance + abs(wanted) * 1e-12:
        raise XdfError(
            f"{value!r} cannot be represented by {size_bits}-bit raw data "
            f"through {equation!r}; nearest is {actual:g} (raw {raw})"
        )
    return raw, actual


def _int(text: str | None, default: int = 0) -> int:
    """XDF numbers are C-style: 0x1EEC0, 200702, -32."""
    if text is None:
        return default
    try:
        return int(str(text).strip(), 0)
    except (ValueError, TypeError, OverflowError) as exc:
        raise XdfError(f"invalid XDF integer {text!r}") from exc


def _normalise_id(value: str | None) -> str:
    """An object reference as a compare-able key: ``0x7FDD`` == ``0x07fdd``."""
    text = (value or "").strip().lower()
    digits = text[2:] if text.startswith("0x") else ""
    if digits and all(char in "0123456789abcdef" for char in digits):
        return "0x" + (digits.lstrip("0") or "0")
    return text


@dataclass
class Embedded:
    """An EMBEDDEDDATA block: where data lives and how it is packed."""

    address: int                  # XDF address, before BASEOFFSET
    size_bits: int = 8
    rows: int = 1
    cols: int = 1
    major_stride_bits: int = 0    # 0 = contiguous (cols * minor stride)
    minor_stride_bits: int = 0    # 0 = contiguous (element size)
    signed: bool = False
    little_endian: bool | None = None  # None inherits XDF header default
    column_major: bool = False
    is_float: bool = False

    @classmethod
    def parse(cls, node: ET.Element, *, signed_default: bool = False,
              float_default: bool = False) -> "Embedded":
        size_bits = _int(node.get("mmedelementsizebits"), 8)
        flag_text = node.get("mmedtypeflags")
        type_flags = _int(flag_text) if flag_text is not None else None
        if type_flags is not None and type_flags & ~0x10007:
            raise XdfError(f"unsupported embedded data flags 0x{type_flags:X} (float/unknown encoding)")
        is_float = bool(type_flags & 0x10000) if type_flags is not None else bool(float_default)
        if is_float:
            if size_bits not in (32, 64):
                raise XdfError(
                    f"floating-point embedded data is not supported for {size_bits}-bit elements"
                )
        elif size_bits not in (8, 16, 32):
            raise XdfError(f"unsupported element size {size_bits} bits")
        return cls(
            address=_int(node.get("mmedaddress")),
            size_bits=size_bits,
            rows=max(1, _int(node.get("mmedrowcount"), 1)),
            cols=max(1, _int(node.get("mmedcolcount"), 1)),
            major_stride_bits=_int(node.get("mmedmajorstridebits")),
            minor_stride_bits=_int(node.get("mmedminorstridebits")),
            signed=True if is_float else (bool(type_flags & 0x1) if type_flags is not None else signed_default),
            little_endian=bool(type_flags & 0x2) if type_flags is not None else None,
            column_major=bool(type_flags & 0x4) if type_flags is not None else False,
            is_float=is_float,
        )

    def validate_layout(self) -> None:
        if (not 1 <= self.rows <= MAX_XDF_AXIS or not 1 <= self.cols <= MAX_XDF_AXIS
                or self.rows * self.cols > MAX_XDF_CELLS):
            raise XdfError("embedded dimensions exceed supported XDF limits")
        # Reject layouts whose semantics are not supported rather than rounding
        # bit offsets or guessing the interaction of multi-column column-major
        # and explicit strides. A single-column (cols == 1) vector has only one
        # column, so major_stride_bits steps cleanly row-by-row.
        for stride, used in ((self.major_stride_bits, self.rows > 1),
                             (self.minor_stride_bits, self.cols > 1)):
            if used and (stride < 0 or stride % 8):
                raise XdfError("negative or non-byte-aligned embedded stride is not supported")
        if self.column_major and self.cols > 1 and (self.major_stride_bits or self.minor_stride_bits):
            raise XdfError("column-major embedded data with explicit strides is not supported")

    @property
    def count(self) -> int:
        return self.rows * self.cols

    @property
    def span_bits(self) -> int:
        self.validate_layout()
        if self.column_major and self.cols > 1:
            return self.count * self.size_bits
        minor = self.minor_stride_bits or self.size_bits
        major = self.major_stride_bits or (minor * self.cols)
        return (self.rows - 1) * major + (self.cols - 1) * minor + self.size_bits

    def positions(self, offset: int) -> list[tuple[int, int]]:
        """``(image offset, byte length)`` for each row-major element."""
        self.validate_layout()
        size = self.size_bits // 8
        if self.column_major and self.cols > 1:
            return [(offset + (c * self.rows + r) * size, size)
                    for r in range(self.rows) for c in range(self.cols)]
        minor = (self.minor_stride_bits or self.size_bits) // 8
        major = (
            self.major_stride_bits // 8
            if self.major_stride_bits else minor * self.cols
        )
        return [
            (offset + r * major + c * minor, size)
            for r in range(self.rows)
            for c in range(self.cols)
        ]

    def read(self, image: bytes, offset: int, *, little_endian: bool) -> list[int | float]:
        """Every raw element, row-major."""
        out: list[int | float] = []
        if self.little_endian is not None:
            little_endian = self.little_endian
        fmt = ("<" if little_endian else ">") + ("f" if self.size_bits == 32 else "d")
        for pos, size in self.positions(offset):
            chunk = image[pos : pos + size]
            if pos < 0 or len(chunk) != size:
                raise XdfError(
                    f"data at 0x{self.address:X} falls outside the image"
                )
            if self.is_float:
                val = struct.unpack(fmt, chunk)[0]
                if not math.isfinite(val):
                    raise XdfError(
                        f"non-finite IEEE-754 float at 0x{self.address:X}"
                    )
                out.append(float(val))
            else:
                out.append(int.from_bytes(chunk, "little" if little_endian
                                          else "big", signed=self.signed))
        return out

    def write_one(
        self, image: bytearray, offset: int, index: int, raw: int | float,
        *, little_endian: bool,
    ) -> tuple[int, bytes, bytes]:
        """Write one element without touching adjacent bytes.

        Returns its image offset plus the before/after byte strings.  Range,
        bounds and type checks are deliberately here at the byte boundary; no
        caller can accidentally get Python's truncation or wrapping.
        """
        positions = self.positions(offset)
        if not 0 <= index < len(positions):
            raise XdfError(
                f"cell index {index} is outside {self.rows}x{self.cols} data"
            )
        pos, size = positions[index]
        if pos < 0 or pos + size > len(image):
            raise XdfError(
                f"data at 0x{self.address:X} falls outside the image"
            )
        before = bytes(image[pos : pos + size])
        if self.little_endian is not None:
            little_endian = self.little_endian
        if self.is_float:
            if isinstance(raw, bool):
                raise XdfError(f"raw value {raw!r} is not a float")
            try:
                raw_f = float(raw)
                if not math.isfinite(raw_f):
                    raise ValueError("non-finite")
                fmt = ("<" if little_endian else ">") + ("f" if self.size_bits == 32 else "d")
                after = struct.pack(fmt, raw_f)
            except (TypeError, ValueError, OverflowError, struct.error) as exc:
                raise XdfError(f"float value {raw!r} cannot be encoded: {exc}") from exc
        else:
            if isinstance(raw, bool) or int(raw) != raw:
                raise XdfError(f"raw value {raw!r} is not an integer")
            raw_i = int(raw)
            if self.signed:
                low, high = -(1 << (self.size_bits - 1)), (1 << (self.size_bits - 1)) - 1
            else:
                low, high = 0, (1 << self.size_bits) - 1
            if not low <= raw_i <= high:
                raise XdfError(
                    f"raw value {raw_i} is outside the {self.size_bits}-bit "
                    f"{'signed' if self.signed else 'unsigned'} range {low}..{high}"
                )
            after = raw_i.to_bytes(
                size, "little" if little_endian else "big", signed=self.signed
            )
        image[pos : pos + size] = after
        return pos, before, after


@dataclass
class Axis:
    """One axis of a table: static LABELs or values embedded in the dump.

    An axis may instead *link* to another item - TunerPro writes
    ``<embedinfo type="3" linkobjid="0x7FDD" />`` - whose data is then the
    axis' labels.  In this library that target is always a legend table
    holding the breakpoints (engine temperature, RPM, TPS...).  The link is
    stored as written and resolved by :meth:`XdfFile.resolve_links`.
    """

    ident: str                    # "x" | "y"
    units: str = ""
    labels: list[str] = field(default_factory=list)
    count: int = 1
    embedded: Embedded | None = None
    math: str = "X"
    link_id: str = ""             # <embedinfo linkobjid>, "" when there is none
    target: "XdfTable | None" = field(default=None, repr=False, compare=False)

    @classmethod
    def parse(cls, node: ET.Element, *, signed_default: bool,
              float_default: bool = False) -> "Axis":
        units = (node.findtext("units") or "").strip()
        count = max(1, _int(node.findtext("indexcount"), 1))
        if count > MAX_XDF_AXIS:
            raise XdfError("axis exceeds supported XDF limit")
        labels: dict[int, str] = {}
        for label in node.findall("LABEL"):
            labels[_int(label.get("index"))] = (label.get("value") or "").strip()
        math = _math_equation(node)

        embedded = None
        data_node = node.find("EMBEDDEDDATA")
        if data_node is not None and data_node.get("mmedaddress") is not None:
            embedded = Embedded.parse(data_node, signed_default=signed_default,
                                      float_default=float_default)
            embedded.rows, embedded.cols = 1, count
            embedded.validate_layout()

        info = node.find("embedinfo")
        link_id = (info.get("linkobjid") or "").strip() if info is not None else ""

        return cls(
            ident=node.get("id") or "?",
            units=units,
            labels=[labels.get(i, "") for i in range(count)],
            count=count,
            embedded=embedded,
            math=math,
            link_id=link_id,
        )

    def header(self, image: bytes, offset: int, *, little_endian: bool) -> list[str]:
        """Axis labels, either the static ones or scaled embedded values."""
        if self.embedded is not None:
            raw = self.embedded.read(image, offset, little_endian=little_endian)
            return [_format_number(eval_math(self.math, v)) for v in raw]
        if any(self.labels):
            return self.labels
        return [str(i) for i in range(self.count)]

    def as_dict(self, image: bytes, offset: int, *, little_endian: bool) -> dict:
        values = self.header(image, offset, little_endian=little_endian)
        raw = (
            self.embedded.read(image, offset, little_endian=little_endian)
            if self.embedded is not None else []
        )
        result = {
            "id": self.ident,
            "units": self.units,
            "values": values,
            "raw_values": raw,
            "equation": self.math,
            "address": (
                f"0x{self.embedded.address:X}" if self.embedded is not None else ""
            ),
            "size_bits": self.embedded.size_bits if self.embedded is not None else 0,
            "signed": self.embedded.signed if self.embedded is not None else False,
            "editable": self.embedded is not None,
            "legend": None,
        }
        if self.embedded is not None and self.embedded.is_float:
            result["is_float"] = True
        return result


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


@dataclass
class XdfConstant:
    title: str
    description: str = ""
    category: str = ""
    units: str = ""
    embedded: Embedded | None = None
    math: str = "X"
    decimalpl: int | None = None
    uniqueid: str = ""

    def raw(self, image: bytes, offset: int, *, little_endian: bool) -> int | float:
        if self.embedded is None:
            raise XdfError(f"{self.title}: no embedded data")
        return self.embedded.read(image, offset, little_endian=little_endian)[0]

    def value(self, image: bytes, offset: int, *, little_endian: bool) -> float:
        val = eval_math(
            self.math, self.raw(image, offset, little_endian=little_endian)
        )
        return round(val, self.decimalpl) if self.decimalpl is not None else val

    @property
    def item_id(self) -> str:
        return self.uniqueid or (
            f"address:0x{self.embedded.address:X}" if self.embedded else self.title
        )

    def as_dict(self, image: bytes, offset: int,
                *, little_endian: bool) -> dict:
        raw = self.raw(image, offset, little_endian=little_endian)
        value = eval_math(self.math, raw)
        return {
            "id": self.item_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "units": self.units,
            "address": f"0x{self.embedded.address:X}" if self.embedded else "",
            "raw": raw,
            "value": round(value, self.decimalpl) if self.decimalpl is not None else value,
            "equation": self.math,
            "size_bits": self.embedded.size_bits if self.embedded else 0,
            "signed": self.embedded.signed if self.embedded else False,
            "is_float": self.embedded.is_float if self.embedded else False,
            "editable": self.embedded is not None,
        }


@dataclass
class XdfFlag:
    """A bitmask switch inside an integer byte/word (<XDFFLAG>)."""

    title: str
    description: str = ""
    category: str = ""
    embedded: Embedded | None = None
    mask: int = 1
    uniqueid: str = ""

    @property
    def item_id(self) -> str:
        if self.uniqueid:
            return self.uniqueid
        if self.embedded is not None:
            return f"flag:0x{self.embedded.address:X}:0x{self.mask:X}"
        return self.title

    def raw_word(self, image: bytes, offset: int, *, little_endian: bool) -> int:
        if self.embedded is None:
            raise XdfError(f"{self.title}: no embedded data")
        eff_le = little_endian if self.embedded.little_endian is None else self.embedded.little_endian
        pos, size = self.embedded.positions(offset)[0]
        chunk = image[pos : pos + size]
        if pos < 0 or len(chunk) != size:
            raise XdfError(f"data at 0x{self.embedded.address:X} falls outside the image")
        return int.from_bytes(chunk, "little" if eff_le else "big", signed=False)

    def is_set(self, image: bytes, offset: int, *, little_endian: bool) -> bool:
        return (self.raw_word(image, offset, little_endian=little_endian) & self.mask) == self.mask

    def as_dict(self, image: bytes, offset: int, *, little_endian: bool) -> dict:
        raw = self.raw_word(image, offset, little_endian=little_endian)
        return {
            "id": self.item_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "address": f"0x{self.embedded.address:X}" if self.embedded else "",
            "mask": f"0x{self.mask:X}",
            "mask_int": self.mask,
            "raw": raw,
            "value": (raw & self.mask) == self.mask,
            "size_bits": self.embedded.size_bits if self.embedded else 0,
            "editable": self.embedded is not None,
        }


@dataclass(frozen=True)
class XdfPatchEntry:
    """One contiguous byte replacement inside an <XDFPATCH>."""

    name: str
    address: int
    size: int
    patch_bytes: bytes
    base_bytes: bytes | None = None


@dataclass
class XdfPatch:
    """A multi-entry binary patch (<XDFPATCH>)."""

    title: str
    description: str = ""
    category: str = ""
    entries: tuple[XdfPatchEntry, ...] = ()
    uniqueid: str = ""

    @property
    def item_id(self) -> str:
        if self.uniqueid:
            return self.uniqueid
        if self.entries:
            return f"patch:0x{self.entries[0].address:X}"
        return self.title

    def inspect(self, image: bytes, *, file_offset_fn, address_base: int) -> dict:
        if not self.entries:
            raise XdfError(f"{self.title}: patch has no entries")
        entry_dicts = []
        all_patch = True
        has_base = all(e.base_bytes is not None for e in self.entries)
        any_diff_base = any(
            e.base_bytes is not None and e.base_bytes != e.patch_bytes
            for e in self.entries
        )
        all_base = has_base
        for entry in self.entries:
            pos = file_offset_fn(entry.address) - address_base
            chunk = image[pos : pos + entry.size]
            if pos < 0 or len(chunk) != entry.size:
                raise XdfError(
                    f"patch entry {entry.name!r} at 0x{entry.address:X} falls outside the image"
                )
            if chunk != entry.patch_bytes:
                all_patch = False
            if entry.base_bytes is None or chunk != entry.base_bytes:
                all_base = False
            entry_dicts.append({
                "name": entry.name,
                "address": f"0x{entry.address:X}",
                "image_offset": f"0x{pos:X}",
                "size": entry.size,
                "current_hex": chunk.hex().upper(),
                "patch_hex": entry.patch_bytes.hex().upper(),
                "base_hex": entry.base_bytes.hex().upper() if entry.base_bytes is not None else "",
            })
        if all_patch and (not has_base or any_diff_base):
            state = "applied"
            applied = True
        elif all_patch and all_base:
            state = "stock"
            applied = True
        elif all_base or not has_base:
            state = "unapplied"
            applied = False
        else:
            state = "mismatch"
            applied = False
        return {
            "id": self.item_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "address": f"0x{self.entries[0].address:X}",
            "state": state,
            "applied": applied,
            "has_basedata": has_base,
            "can_apply": (not all_patch) and (not has_base or all_base),
            "can_revert": bool(has_base and any_diff_base and all_patch),
            "entry_count": len(self.entries),
            "entries": entry_dicts,
            "editable": True,
        }


@dataclass
class XdfTable:
    title: str
    description: str = ""
    category: str = ""
    units: str = ""
    x: Axis = field(default_factory=Axis)
    y: Axis = field(default_factory=Axis)
    embedded: Embedded | None = None
    math: str = "X"
    decimalpl: int | None = None
    uniqueid: str = ""
    that_refs: list[tuple[str, bool]] = field(default_factory=list, repr=False, compare=False)

    def values(self, image: bytes, offset: int,
               *, little_endian: bool, cell_eq_fn=None) -> list[list[float]]:
        """Engineering values, one row per y (row) axis entry."""
        if self.embedded is None:
            raise XdfError(f"{self.title}: no embedded data")
        raw = self.embedded.read(image, offset, little_endian=little_endian)
        rows: list[list[float]] = []
        for r in range(self.embedded.rows):
            row = []
            for c in range(self.embedded.cols):
                eq = cell_eq_fn(r, c) if cell_eq_fn is not None else self.math
                value = eval_math(eq, raw[r * self.embedded.cols + c])
                row.append(round(value, self.decimalpl) if self.decimalpl else value)
            rows.append(row)
        return rows

    @property
    def item_id(self) -> str:
        return self.uniqueid or (
            f"address:0x{self.embedded.address:X}" if self.embedded else self.title
        )

    def as_dict(self, image: bytes, offsets: dict,
                *, little_endian: bool, cell_eq_fn=None) -> dict:
        """``offsets`` carries the image offsets of the data and both axes."""
        raw = self.embedded.read(
            image, offsets["data"], little_endian=little_endian
        ) if self.embedded else []
        raw_rows = [
            raw[r * self.embedded.cols : (r + 1) * self.embedded.cols]
            for r in range(self.embedded.rows)
        ] if self.embedded else []
        return {
            "id": self.item_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "units": self.units,
            "address": f"0x{self.embedded.address:X}" if self.embedded else "",
            "rows": self.y.count,
            "cols": self.x.count,
            "x": self.x.header(image, offsets["x"], little_endian=little_endian),
            "y": self.y.header(image, offsets["y"], little_endian=little_endian),
            "x_units": self.x.units,
            "y_units": self.y.units,
            "axes": {
                "x": self.x.as_dict(
                    image, offsets["x"], little_endian=little_endian
                ),
                "y": self.y.as_dict(
                    image, offsets["y"], little_endian=little_endian
                ),
            },
            "values": self.values(
                image, offsets["data"], little_endian=little_endian,
                cell_eq_fn=cell_eq_fn,
            ),
            "raw_values": raw_rows,
            "equation": self.math,
            "size_bits": self.embedded.size_bits if self.embedded else 0,
            "signed": self.embedded.signed if self.embedded else False,
            "is_float": self.embedded.is_float if self.embedded else False,
            "editable": self.embedded is not None,
        }


# --------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------


@dataclass
class XdfFile:
    """One parsed XDF and everything needed to map a dump onto it."""

    title: str = ""
    description: str = ""
    author: str = ""
    version: str = ""
    path: str = ""
    file_sha256: str = ""  # fingerprint of the bytes actually parsed
    region_size: int | None = None
    base_offset: int = 0
    base_subtract: bool = False
    little_endian: bool = False
    signed_default: bool = False
    float_default: bool = False
    categories: dict[int, str] = field(default_factory=dict)
    tables: list[XdfTable] = field(default_factory=list)
    constants: list[XdfConstant] = field(default_factory=list)
    flags: list[XdfFlag] = field(default_factory=list)
    patches: list[XdfPatch] = field(default_factory=list)
    checksums: list[str] = field(default_factory=list)
    unsupported: list[dict] = field(default_factory=list)

    # -- parsing ----------------------------------------------------------
    @classmethod
    def from_file(cls, path: str | Path) -> "XdfFile":
        path = Path(path)
        raw = read_xdf_bytes(path)
        xdf = cls.from_string(raw.decode("ISO-8859-1"))
        xdf.path = str(path)
        xdf.file_sha256 = hashlib.sha256(raw).hexdigest()
        return xdf

    @classmethod
    def from_string(cls, text: str) -> "XdfFile":
        if not isinstance(text, str) or len(text) > MAX_XDF_BYTES:
            raise XdfError("XDF exceeds the 8 MiB definition limit or is not text")
        # Entity expansion is not needed by XDF; standard predefined/numeric
        # XML entities still work. Reject all declarations before parsing.
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            raise XdfError("XDF DTD and entity declarations are not supported")
        try:
            root = ET.fromstring(text, parser=ET.XMLParser(target=_BoundedXmlTree()))
        except ET.ParseError as exc:
            raise XdfError(f"not valid XDF/XML: {exc}") from exc

        xdf = cls()
        header = root.find("XDFHEADER")
        if header is None:
            raise XdfError("no XDFHEADER - this is not a TunerPro XDF")

        xdf.title = (header.findtext("deftitle") or "").strip()
        xdf.description = (header.findtext("description") or "").strip()
        xdf.author = (header.findtext("author") or "").strip()
        xdf.version = (header.findtext("fileversion") or "").strip()
        for region in header.findall("REGION"):
            if region.get("size"):
                xdf.region_size = _int(region.get("size"))
        base = header.find("BASEOFFSET")
        if base is not None:
            xdf.base_offset = _int(base.get("offset"))
            xdf.base_subtract = bool(_int(base.get("subtract")))
        defaults = header.find("DEFAULTS")
        if defaults is not None:
            xdf.little_endian = bool(_int(defaults.get("lsbfirst")))
            xdf.signed_default = bool(_int(defaults.get("signed")))
            xdf.float_default = bool(_int(defaults.get("float")))
        for category in header.findall("CATEGORY"):
            xdf.categories[_int(category.get("index"))] = (
                category.get("name") or ""
            ).strip()

        def category_of(node: ET.Element) -> str:
            parts = []
            for mem in node.findall("CATEGORYMEM"):
                name = xdf.categories.get(_int(mem.get("category")), "")
                if name:
                    parts.append(name)
            return " / ".join(parts)

        for node in root.findall("XDFTABLE"):
            try:
                xdf.tables.append(cls._parse_table(node, category_of(node), xdf))
            except XdfError as exc:
                xdf.unsupported.append({
                    "title": (node.findtext("title") or "").strip(),
                    "kind": "table",
                    "reason": str(exc),
                })

        for node in root.findall("XDFCONSTANT"):
            try:
                xdf.constants.append(
                    cls._parse_constant(node, category_of(node), xdf)
                )
            except XdfError as exc:
                xdf.unsupported.append({
                    "title": (node.findtext("title") or "").strip(),
                    "kind": "constant",
                    "reason": str(exc),
                })

        for node in root.findall("XDFFLAG"):
            try:
                xdf.flags.append(cls._parse_flag(node, category_of(node), xdf))
            except XdfError as exc:
                xdf.unsupported.append({
                    "title": (node.findtext("title") or "").strip() or "(untitled flag)",
                    "kind": "flag",
                    "reason": str(exc),
                })

        for node in root.findall("XDFPATCH"):
            try:
                xdf.patches.append(cls._parse_patch(node, category_of(node)))
            except XdfError as exc:
                xdf.unsupported.append({
                    "title": (node.findtext("title") or "").strip() or "(untitled patch)",
                    "kind": "patch",
                    "reason": str(exc),
                })

        for index, node in enumerate(root.findall("XDFCHECKSUM"), 1):
            title = (node.findtext("title") or "").strip()
            # An unnamed declaration is still a declaration, not evidence
            # that the image needs no calibration checksum handling.
            xdf.checksums.append(title or f"(unnamed checksum #{index})")

        xdf.resolve_links()

        if not xdf.tables and not xdf.constants and not xdf.flags and not xdf.patches:
            raise XdfError(
                f"no readable tables or constants (root tag {root.tag!r})"
            )
        return xdf

    def resolve_links(self) -> None:
        """Point every ``<embedinfo linkobjid>`` axis and ``THAT(...)`` ref at its target."""
        by_id: dict[str, XdfTable] = {}
        for table in self.tables:
            if table.uniqueid:
                by_id.setdefault(_normalise_id(table.uniqueid), table)

        # Validate THAT(...) cross-table references and reject missing/cyclic
        # references before rendering or writing.
        valid_tables: list[XdfTable] = []
        removed = True
        while removed:
            removed = False
            current_ids = {
                _normalise_id(t.uniqueid): t for t in self.tables if t.uniqueid
            }
            valid_tables = []
            for table in self.tables:
                if not table.that_refs:
                    valid_tables.append(table)
                    continue
                reason = ""
                for target_id, _ in table.that_refs:
                    target = current_ids.get(target_id)
                    if target is None or target.embedded is None:
                        reason = f"{table.title}: THAT() target {target_id} is missing"
                        break
                    if (table.embedded is not None and (
                        target.embedded.rows < table.embedded.rows
                        or target.embedded.cols < table.embedded.cols
                    )):
                        reason = (
                            f"{table.title}: THAT() target {target.title!r} is smaller "
                            f"than {table.embedded.rows}x{table.embedded.cols}"
                        )
                        break
                if reason:
                    self.unsupported.append({
                        "title": table.title, "kind": "table", "reason": reason,
                    })
                    removed = True
                else:
                    valid_tables.append(table)
            self.tables = valid_tables

        by_id = {
            _normalise_id(t.uniqueid): t for t in self.tables if t.uniqueid
        }

        def _depth(tbl: XdfTable, stack: frozenset[int]) -> int:
            if not tbl.that_refs:
                return 0
            if id(tbl) in stack:
                raise XdfError(f"{tbl.title}: cyclic THAT() table reference")
            next_stack = stack | {id(tbl)}
            return 1 + max(
                _depth(by_id[target_id], next_stack)
                for target_id, _ in tbl.that_refs
            )

        non_cyclic: list[XdfTable] = []
        for table in self.tables:
            try:
                _depth(table, frozenset())
                non_cyclic.append(table)
            except XdfError as exc:
                self.unsupported.append({
                    "title": table.title, "kind": "table", "reason": str(exc),
                })
        self.tables = non_cyclic

        by_id = {}
        for table in self.tables:
            if table.uniqueid:
                by_id.setdefault(_normalise_id(table.uniqueid), table)
        for table in self.tables:
            for axis in (table.x, table.y):
                if axis.link_id:
                    axis.target = by_id.get(_normalise_id(axis.link_id))

    def _table_by_norm_id(self, norm_id: str) -> XdfTable:
        for table in self.tables:
            if table.uniqueid and _normalise_id(table.uniqueid) == norm_id:
                return table
        raise XdfError(f"THAT() target table {norm_id} is not available")

    def _table_depth(self, table: XdfTable, _seen: frozenset[int] = frozenset()) -> int:
        if not table.that_refs or id(table) in _seen:
            return 0
        nxt = _seen | {id(table)}
        return 1 + max(
            self._table_depth(self._table_by_norm_id(tid), nxt)
            for tid, _ in table.that_refs
        )

    def _cell_raw_and_unrounded(
        self, table: XdfTable, image: bytes, row: int, col: int, *, address_base: int
    ) -> tuple[int | float, float]:
        if table.embedded is None:
            raise XdfError(f"{table.title}: no embedded data")
        offset = self.file_offset(table.embedded.address) - address_base
        raw_list = table.embedded.read(image, offset, little_endian=self.little_endian)
        raw_val = raw_list[row * table.embedded.cols + col]
        eq = self._cell_equation(table, image, row, col, address_base=address_base)
        return raw_val, eval_math(eq, raw_val)

    def _cell_equation(
        self, table: XdfTable, image: bytes, row: int, col: int, *, address_base: int
    ) -> str:
        if not table.that_refs:
            return table.math

        def _replace(match: re.Match[str]) -> str:
            target_id = _normalise_id(hex(_int(match.group(1))))
            want_raw = match.group(2).strip().upper() in ("TRUE", "1")
            target = self._table_by_norm_id(target_id)
            raw_v, eng_v = self._cell_raw_and_unrounded(
                target, image, row, col, address_base=address_base
            )
            val = raw_v if want_raw else eng_v
            return f"({repr(float(val) if isinstance(val, float) else int(val))})"

        return _THAT_CALL.sub(_replace, table.math)

    @staticmethod
    def _extract_that_refs(equation: str) -> list[tuple[str, bool]]:
        refs: list[tuple[str, bool]] = []
        for match in _THAT_CALL.finditer(equation):
            target_int = _int(match.group(1))
            want_raw = match.group(2).strip().upper() in ("TRUE", "1")
            refs.append((_normalise_id(hex(target_int)), want_raw))
        return refs

    @classmethod
    def _check_math(cls, node: ET.Element, what: str, *, allow_that: bool = False) -> str:
        """Reject per-cell or cross-referencing equations we cannot honour."""
        maths = node.findall("MATH")
        equation = _math_equation(node)
        if len(maths) > 1 or any(
            var.get("type") for m in maths for var in m.findall("VAR")
        ):
            raise XdfError(
                f"{what}: per-cell or address-linked equations are not supported"
            )
        probe = _THAT_CALL.sub("(0)", equation) if allow_that else equation
        try:
            _prepare_scalar_math(probe)
        except XdfError as exc:
            raise XdfError(f"{what}: unsupported equation {equation!r}") from exc
        return equation

    @classmethod
    def _parse_table(cls, node: ET.Element, category: str,
                     xdf: "XdfFile") -> XdfTable:
        title = (node.findtext("title") or "").strip() or "(untitled table)"
        axes: dict[str, Axis] = {}
        for axis_node in node.findall("XDFAXIS"):
            axis = Axis.parse(axis_node, signed_default=xdf.signed_default,
                              float_default=xdf.float_default)
            axes[axis.ident] = axis

        z = axes.get("z")
        if z is None or z.embedded is None:
            raise XdfError(f"{title}: no z-axis data")
        z_node = next(
            (n for n in node.findall("XDFAXIS") if n.get("id") == "z"), None
        )
        y_axis = axes.get("y")
        x_axis = axes.get("x")
        if y_axis is not None and z.embedded.rows != y_axis.count:
            # TunerPro repeats the row count in both places; trust the axis.
            z.embedded.rows = y_axis.count
        if x_axis is not None and z.embedded.cols == 1 and x_axis.count > 1:
            # A 3D table may omit mmedcolcount; the x axis knows.
            z.embedded.cols = x_axis.count
        z.embedded.validate_layout()

        table = XdfTable(
            title=title,
            description=(node.findtext("description") or "").strip(),
            category=category,
            units=(z.units or node.findtext("units") or "").strip(),
            x=axes.get("x") or Axis(ident="x"),
            y=axes.get("y") or Axis(ident="y"),
            embedded=z.embedded,
            decimalpl=_int(z_node.findtext("decimalpl")) or None
            if z_node is not None and z_node.findtext("decimalpl") else None,
            uniqueid=node.get("uniqueid") or "",
        )
        # Scaling lives on the z axis.
        table.math = cls._check_math(z_node, title, allow_that=True)
        table.that_refs = cls._extract_that_refs(table.math)
        for axis, axis_node in (
            (table.x, next((n for n in node.findall("XDFAXIS")
                            if n.get("id") == "x"), None)),
            (table.y, next((n for n in node.findall("XDFAXIS")
                            if n.get("id") == "y"), None)),
        ):
            if axis_node is not None:
                axis.math = cls._check_math(axis_node, f"{title} ({axis.ident})")
        return table

    @classmethod
    def _parse_constant(cls, node: ET.Element, category: str,
                        xdf: "XdfFile") -> XdfConstant:
        title = (node.findtext("title") or "").strip() or "(untitled constant)"
        data_node = node.find("EMBEDDEDDATA")
        if data_node is None or data_node.get("mmedaddress") is None:
            raise XdfError(f"{title}: no embedded data")
        return XdfConstant(
            title=title,
            description=(node.findtext("description") or "").strip(),
            category=category,
            units=(node.findtext("units") or "").strip(),
            embedded=Embedded.parse(data_node, signed_default=xdf.signed_default,
                                    float_default=xdf.float_default),
            math=cls._check_math(node, title),
            decimalpl=_int(node.findtext("decimalpl")) or None
            if node.findtext("decimalpl") else None,
            uniqueid=node.get("uniqueid") or "",
        )

    @classmethod
    def _parse_flag(cls, node: ET.Element, category: str,
                    xdf: "XdfFile") -> XdfFlag:
        title = (node.findtext("title") or "").strip() or "(untitled flag)"
        data_node = node.find("EMBEDDEDDATA")
        if data_node is None or data_node.get("mmedaddress") is None:
            raise XdfError(f"{title}: no embedded data")
        embedded = Embedded.parse(
            data_node, signed_default=False, float_default=False
        )
        if embedded.is_float:
            raise XdfError(f"{title}: flag items cannot use floating-point data")
        embedded.signed = False
        embedded.rows = 1
        embedded.cols = 1
        embedded.validate_layout()
        mask = _int(node.findtext("mask"), 0)
        if mask <= 0 or mask >= (1 << embedded.size_bits):
            raise XdfError(
                f"{title}: invalid {embedded.size_bits}-bit flag mask 0x{mask:X}"
            )
        return XdfFlag(
            title=title,
            description=(node.findtext("description") or "").strip(),
            category=category,
            embedded=embedded,
            mask=mask,
            uniqueid=node.get("uniqueid") or "",
        )

    @staticmethod
    def _decode_patch_hex(text: str | None, expected_size: int | None, what: str) -> bytes:
        cleaned = re.sub(r"\s+", "", text or "")
        if not cleaned or not re.fullmatch(r"[0-9A-Fa-f]+", cleaned):
            raise XdfError(f"{what}: invalid hex bytes")
        if expected_size is not None and expected_size > 0 and len(cleaned) < expected_size * 2:
            cleaned = cleaned.zfill(expected_size * 2)
        if len(cleaned) % 2:
            cleaned = "0" + cleaned
        raw = bytes.fromhex(cleaned)
        if expected_size is not None and len(raw) != expected_size:
            raise XdfError(
                f"{what}: datasize {expected_size} does not match {len(raw)}-byte payload"
            )
        if not 1 <= len(raw) <= 4096:
            raise XdfError(f"{what}: patch entry size {len(raw)} outside 1..4096 bytes")
        return raw

    @classmethod
    def _parse_patch(cls, node: ET.Element, category: str) -> XdfPatch:
        title = (node.findtext("title") or "").strip() or "(untitled patch)"
        entry_nodes = node.findall("XDFPATCHENTRY")
        if not entry_nodes:
            raise XdfError(f"{title}: patch defines no XDFPATCHENTRY")
        if len(entry_nodes) > 512:
            raise XdfError(f"{title}: patch exceeds 512 entries")
        entries: list[XdfPatchEntry] = []
        seen_ranges: list[tuple[int, int]] = []
        for idx, entry_node in enumerate(entry_nodes, 1):
            if entry_node.get("address") is None:
                raise XdfError(f"{title}: patch entry #{idx} has no address")
            address = _int(entry_node.get("address"))
            size_attr = entry_node.get("datasize")
            expected_size = _int(size_attr) if size_attr is not None else None
            if expected_size is not None and expected_size <= 0:
                raise XdfError(f"{title}: patch entry #{idx} has non-positive datasize")
            name = (entry_node.get("name") or f"entry_{idx}").strip() or f"entry_{idx}"
            patch_bytes = cls._decode_patch_hex(
                entry_node.get("patchdata"), expected_size, f"{title} ({name})"
            )
            size = len(patch_bytes)
            base_raw = (entry_node.get("basedata") or "").strip()
            base_bytes = (
                cls._decode_patch_hex(base_raw, size, f"{title} ({name} basedata)")
                if base_raw else None
            )
            end = address + size
            for prev_start, prev_end in seen_ranges:
                if max(address, prev_start) < min(end, prev_end):
                    raise XdfError(f"{title}: overlapping entries inside patch")
            seen_ranges.append((address, end))
            entries.append(XdfPatchEntry(
                name=name, address=address, size=size,
                patch_bytes=patch_bytes, base_bytes=base_bytes,
            ))
        return XdfPatch(
            title=title,
            description=(node.findtext("description") or "").strip(),
            category=category,
            entries=tuple(entries),
            uniqueid=node.get("uniqueid") or "",
        )

    # -- addressing -------------------------------------------------------
    def file_offset(self, address: int) -> int:
        """XDF address -> offset in the bin the XDF was authored against."""
        if self.base_subtract:
            return address - self.base_offset
        return address + self.base_offset

    def _offsets(self, *, include_flags_patches: bool = True) -> list[tuple[str, int, int]]:
        """(what, image offset, span in bits) for every readable item."""
        out: list[tuple[str, int, int]] = []
        for table in self.tables:
            base = self.file_offset(table.embedded.address)
            out.append((table.title, base, table.embedded.span_bits))
            for axis in (table.x, table.y):
                if axis.embedded is not None:
                    out.append((
                        f"{table.title} [{axis.ident} axis]",
                        self.file_offset(axis.embedded.address),
                        axis.embedded.span_bits,
                    ))
        for const in self.constants:
            out.append((
                const.title,
                self.file_offset(const.embedded.address),
                const.embedded.span_bits,
            ))
        if include_flags_patches:
            for flag in self.flags:
                if flag.embedded is not None:
                    out.append((
                        flag.title,
                        self.file_offset(flag.embedded.address),
                        flag.embedded.span_bits,
                    ))
            for patch in self.patches:
                for entry in patch.entries:
                    out.append((
                        f"{patch.title} [{entry.name}]",
                        self.file_offset(entry.address),
                        entry.size * 8,
                    ))
        return out

    def data_end(self) -> int:
        """The highest bin offset any item touches."""
        end = 0
        for _, offset, span_bits in self._offsets():
            end = max(end, offset + (span_bits + 7) // 8)
        return end

    def suggest_address_base(self, image_len: int) -> int:
        """How far the image is shifted against the XDF's own bin.

        XDFs for the IAW families are authored against the full device dump
        (0x50000 for the 5AM). A flash *region* read is the device without
        its bootloader, so device address 0x4000 is image offset 0. Common
        bases are tried; if none fits, 0 is returned and rendering will
        report exactly which table fell outside.
        """
        end = self.data_end()
        if end <= image_len:
            return 0
        for guess in (0x4000, 0x8000, 0xC000):
            if end - guess <= image_len:
                return guess
        return 0

    # -- rendering --------------------------------------------------------
    def _bytes(self, image) -> bytes:
        if isinstance(image, (bytes, bytearray)):
            return bytes(image)
        data = getattr(image, "data", None)      # FirmwareImage
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        raise XdfError("image must be bytes or a FirmwareImage")

    def _legend_labels(self, axis: Axis, image: bytes,
                       *, address_base: int) -> tuple[list[str], dict]:
        """Engineering labels from the legend an axis links to, plus provenance.

        A linked axis names another item instead of holding its own data, and
        the referenced legend's values *are* the breakpoints - reading them
        through the legend's own MATH is what turns row 13 into "82 °C".  Only
        labels the legend actually defines are used: an axis longer than its
        legend keeps its own fallback for the tail, and the shortfall is
        reported rather than padded out with invented values.
        """
        info = {
            "id": axis.link_id,
            "title": "",
            "count": 0,
            "applied": 0,
            "reason": "",
        }
        target = axis.target
        if target is None:
            info["reason"] = f"no table in this definition has id {axis.link_id}"
            return [], info
        info["title"] = target.title
        if target.uniqueid:
            info["id"] = target.uniqueid
        if target.embedded is None:
            info["reason"] = (
                f"{target.title} carries no embedded data to label from"
            )
            return [], info
        offset = self.file_offset(target.embedded.address) - address_base
        try:
            raw = target.embedded.read(
                image, offset, little_endian=self.little_endian
            )
        except XdfError as exc:
            info["reason"] = f"{target.title} could not be read: {exc}"
            return [], info
        labels = []
        for value in raw:
            value = eval_math(target.math, value)
            if target.decimalpl:
                value = round(value, target.decimalpl)
            labels.append(_format_number(value))
        info["count"] = len(labels)
        return labels, info

    def axis_labels(self, axis: Axis, image: bytes, offset: int, *,
                    address_base: int) -> tuple[list[str], dict | None]:
        """One axis' labels: its own data or LABELs, with a linked legend on top.

        An axis that carries its own embedded values keeps them: those are the
        breakpoints the map stores (and edits), so they are the truer label
        even where the definition also names a legend.  The returned dict is
        the legend provenance, or ``None`` for an axis that links to nothing.
        """
        labels = axis.header(image, offset, little_endian=self.little_endian)
        if not axis.link_id or axis.embedded is not None:
            return labels, None
        legend, info = self._legend_labels(axis, image, address_base=address_base)
        for index, value in enumerate(legend[:len(labels)]):
            labels[index] = value
        info["applied"] = min(len(legend), len(labels))
        if not info["reason"] and info["applied"] < len(labels):
            info["reason"] = (
                f"{info['title'] or info['id']} defines {info['count']} labels "
                f"for a {len(labels)}-entry axis"
            )
        return labels, info

    def render(self, image, *, address_base: int | None = None) -> dict:
        """Every table, constant, flag and patch with its engineering values."""
        data = self._bytes(image)
        if address_base is None:
            address_base = self.suggest_address_base(len(data))

        def hint() -> str:
            return (
                f"outside this {len(data)}-byte image (base 0x{address_base:X}). "
                "If this is a region read of a full-device XDF, pass "
                "address_base=0x4000."
            )

        def axis_offset(axis: Axis, data_offset: int) -> int:
            if axis.embedded is None:
                return data_offset
            return self.file_offset(axis.embedded.address) - address_base

        tables: list[dict] = []
        errors: list[dict] = []
        for table in self.tables:
            data_offset = self.file_offset(table.embedded.address) - address_base
            offsets = {
                "data": data_offset,
                "x": axis_offset(table.x, data_offset),
                "y": axis_offset(table.y, data_offset),
            }
            try:
                cell_eq = (
                    (lambda r, c, tbl=table: self._cell_equation(
                        tbl, data, r, c, address_base=address_base
                    ))
                    if table.that_refs else None
                )
                entry = table.as_dict(
                    data, offsets, little_endian=self.little_endian,
                    cell_eq_fn=cell_eq,
                )
                for name, axis in (("x", table.x), ("y", table.y)):
                    labels, legend = self.axis_labels(
                        axis, data, offsets[name], address_base=address_base
                    )
                    entry[name] = labels
                    entry["axes"][name].update(values=labels, legend=legend)
            except XdfError as exc:
                errors.append({
                    "title": table.title, "kind": "table",
                    "reason": f"{table.title}: {exc} {hint()}",
                })
                continue
            tables.append(entry)

        constants: list[dict] = []
        for const in self.constants:
            offset = self.file_offset(const.embedded.address) - address_base
            try:
                constants.append(
                    const.as_dict(data, offset, little_endian=self.little_endian)
                )
            except XdfError as exc:
                errors.append({
                    "title": const.title, "kind": "constant",
                    "reason": f"{const.title}: {exc} {hint()}",
                })

        flags: list[dict] = []
        for flag in self.flags:
            offset = self.file_offset(flag.embedded.address) - address_base
            try:
                flags.append(
                    flag.as_dict(data, offset, little_endian=self.little_endian)
                )
            except XdfError as exc:
                errors.append({
                    "title": flag.title, "kind": "flag",
                    "reason": f"{flag.title}: {exc} {hint()}",
                })

        patches: list[dict] = []
        for patch in self.patches:
            try:
                patches.append(
                    patch.inspect(
                        data, file_offset_fn=self.file_offset,
                        address_base=address_base,
                    )
                )
            except XdfError as exc:
                errors.append({
                    "title": patch.title, "kind": "patch",
                    "reason": f"{patch.title}: {exc} {hint()}",
                })

        return {
            "xdf": {
                "title": self.title, "description": self.description,
                "author": self.author, "version": self.version,
                "path": self.path,
                "categories": sorted(self.categories.values()),
            },
            "image_size": len(data),
            "address_base": address_base,
            "tables": tables,
            "constants": constants,
            "flags": flags,
            "patches": patches,
            "unsupported": self.unsupported,
            "errors": errors,
            "checksums": self.checksums,
        }

    def _item(self, kind: str, ref: str):
        """Resolve a stable item id, with an unambiguous title fallback."""
        collections = {
            "table": self.tables,
            "constant": self.constants,
            "flag": self.flags,
            "patch": self.patches,
        }
        if kind not in collections:
            raise XdfError(f"unknown change kind {kind!r}")
        items = collections[kind]
        if not items:
            raise XdfError(f"this XDF has no {kind}s")
        direct = [item for item in items if item.item_id == ref or item.uniqueid == ref]
        if len(direct) == 1:
            return direct[0]
        titled = [item for item in items if item.title == ref]
        if len(titled) == 1:
            return titled[0]
        if len(titled) > 1:
            raise XdfError(
                f"{ref!r} names {len(titled)} {kind}s; use the item's id"
            )
        raise XdfError(f"no {kind} with id or title {ref!r}")

    @staticmethod
    def _parse_bool_value(value, what: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in ("true", "1", "on", "yes", "enabled", "applied"):
                return True
            if norm in ("false", "0", "off", "no", "disabled", "unapplied"):
                return False
        raise XdfError(f"{what}: value {value!r} must be true/false")

    def apply_changes(
        self, image, changes: list[dict], *, address_base: int | None = None
    ) -> tuple[bytes, list[dict]]:
        """Apply explicit engineering-value, flag and patch edits to a copy of an image.

        Every request names an XDF item and carries the raw value/bytes the
        operator saw.  That optimistic-lock value prevents a recommendation
        prepared against one map being silently applied to another.  The source
        bytes are never mutated and the result records the exact byte offset
        and quantised value for a reviewable build manifest.
        """
        source = self._bytes(image)
        if address_base is None:
            address_base = self.suggest_address_base(len(source))
        if not isinstance(changes, list) or not changes:
            raise XdfError("at least one map change is required")
        if len(changes) > 4096:
            raise XdfError("a tuning build is limited to 4096 explicit changes")

        # Order THAT()-dependent table edits after base edits while preserving
        # the caller's original change order in the returned manifest.
        indexed_changes: list[tuple[int, int, dict]] = []
        for idx, change in enumerate(changes):
            if not isinstance(change, dict):
                raise XdfError(f"change {idx + 1} is not an object")
            kind_probe = str(change.get("kind") or "").strip().lower()
            ref_probe = str(change.get("id") or change.get("item_id") or change.get("title") or "")
            depth = 0
            if kind_probe == "table" and ref_probe:
                try:
                    tbl_probe = self._item("table", ref_probe)
                    depth = self._table_depth(tbl_probe)
                except XdfError:
                    depth = 0
            indexed_changes.append((depth, idx, change))
        indexed_changes.sort(key=lambda entry: (entry[0], entry[1]))

        output = bytearray(source)
        applied_by_idx: dict[int, dict] = {}
        touched: set[tuple[str, str, int]] = set()
        touched_bytes: set[int] = set()
        touched_flag_bits: dict[int, int] = {}

        for _, orig_idx, change in indexed_changes:
            number = orig_idx + 1
            kind = str(change.get("kind") or "").strip().lower()
            ref = str(change.get("id") or change.get("item_id") or change.get("title") or "")
            if not ref:
                raise XdfError(f"change {number} has no item id")

            if kind == "flag":
                flag: XdfFlag = self._item("flag", ref)
                if flag.embedded is None:
                    raise XdfError(f"{flag.title}: no embedded data")
                target_key = ("flag", flag.item_id, 0)
                if target_key in touched:
                    raise XdfError(f"{flag.title}: flag is changed more than once")
                touched.add(target_key)

                offset = self.file_offset(flag.embedded.address) - address_base
                before_raw = flag.raw_word(source, offset, little_endian=self.little_endian)
                if "expected_raw" not in change:
                    raise XdfError(
                        f"{flag.title}: expected_raw is required so the source map can be verified"
                    )
                try:
                    exp_v = change["expected_raw"]
                    expected_raw = int(exp_v)
                    if isinstance(exp_v, bool) or expected_raw != float(exp_v):
                        raise ValueError
                except (TypeError, ValueError):
                    raise XdfError(
                        f"{flag.title}: expected_raw {change.get('expected_raw')!r} is not an integer"
                    ) from None
                if expected_raw != before_raw:
                    raise XdfError(
                        f"{flag.title}: source changed; expected raw {expected_raw}, "
                        f"found {before_raw}. Render the source again."
                    )

                wanted_bool = self._parse_bool_value(change.get("value"), flag.title)
                before_bool = (before_raw & flag.mask) == flag.mask
                if wanted_bool == before_bool:
                    raise XdfError(f"{flag.title}: requested value leaves flag unchanged")

                eff_le = (
                    self.little_endian
                    if flag.embedded.little_endian is None
                    else flag.embedded.little_endian
                )
                pos, size = flag.embedded.positions(offset)[0]
                mask_bytes = flag.mask.to_bytes(size, "little" if eff_le else "big", signed=False)
                for byte_idx, bmask in enumerate(mask_bytes):
                    if not bmask:
                        continue
                    bpos = pos + byte_idx
                    if bpos in touched_bytes or (touched_flag_bits.get(bpos, 0) & bmask):
                        raise XdfError(f"{flag.title}: overlapping byte/bit writes in this change set")
                for byte_idx, bmask in enumerate(mask_bytes):
                    if bmask:
                        bpos = pos + byte_idx
                        touched_flag_bits[bpos] = touched_flag_bits.get(bpos, 0) | bmask

                before_bytes = bytes(source[pos : pos + size])
                working_word = int.from_bytes(
                    output[pos : pos + size],
                    "little" if eff_le else "big",
                    signed=False,
                )
                after_word = (working_word | flag.mask) if wanted_bool else (working_word & ~flag.mask)
                after_bytes = after_word.to_bytes(size, "little" if eff_le else "big", signed=False)
                output[pos : pos + size] = after_bytes
                applied_by_idx[orig_idx] = {
                    "kind": "flag",
                    "id": flag.item_id,
                    "axis": "",
                    "index": None,
                    "title": flag.title,
                    "row": None,
                    "col": None,
                    "x": "",
                    "y": "",
                    "units": "",
                    "mask": f"0x{flag.mask:X}",
                    "address": f"0x{flag.embedded.address:X}",
                    "image_offset": f"0x{pos:X}",
                    "before_raw": before_raw,
                    "after_raw": (before_raw | flag.mask) if wanted_bool else (before_raw & ~flag.mask),
                    "before": before_bool,
                    "requested": wanted_bool,
                    "after": wanted_bool,
                    "quantized": False,
                    "before_hex": before_bytes.hex(),
                    "after_hex": after_bytes.hex(),
                }
                continue

            if kind == "patch":
                patch: XdfPatch = self._item("patch", ref)
                target_key = ("patch", patch.item_id, 0)
                if target_key in touched:
                    raise XdfError(f"{patch.title}: patch is changed more than once")
                touched.add(target_key)

                info = patch.inspect(
                    source, file_offset_fn=self.file_offset, address_base=address_base
                )
                expected_hex = change.get("expected_hex")
                current_hex_list = [e["current_hex"].lower() for e in info["entries"]]
                if not isinstance(expected_hex, list) or len(expected_hex) != len(current_hex_list):
                    raise XdfError(
                        f"{patch.title}: expected_hex list is required so the source map can be verified"
                    )
                norm_expected = [str(h or "").strip().lower() for h in expected_hex]
                if norm_expected != current_hex_list:
                    raise XdfError(
                        f"{patch.title}: source bytes changed since render; render the source again"
                    )

                wanted_apply = self._parse_bool_value(change.get("value"), patch.title)
                allow_mismatch = bool(change.get("allow_base_mismatch"))
                if wanted_apply:
                    if info["state"] in ("applied", "stock"):
                        raise XdfError(f"{patch.title}: patch is already applied")
                    if info["has_basedata"] and info["state"] == "mismatch" and not allow_mismatch:
                        raise XdfError(
                            f"{patch.title}: source bytes do not match patch basedata"
                        )
                else:
                    if not info["has_basedata"]:
                        raise XdfError(
                            f"{patch.title}: patch defines no basedata and cannot be reverted"
                        )
                    if not info["can_revert"] and not allow_mismatch:
                        raise XdfError(
                            f"{patch.title}: patch is not currently applied and cannot be reverted"
                        )

                patch_byte_set: set[int] = set()
                writes: list[tuple[int, bytes, bytes]] = []
                for entry in patch.entries:
                    pos = self.file_offset(entry.address) - address_base
                    target_bytes = entry.patch_bytes if wanted_apply else entry.base_bytes
                    assert target_bytes is not None
                    before_b = bytes(source[pos : pos + entry.size])
                    erange = set(range(pos, pos + entry.size))
                    if (touched_bytes & erange) or any(b in touched_flag_bits for b in erange):
                        raise XdfError(f"{patch.title}: overlapping byte writes in this change set")
                    patch_byte_set.update(erange)
                    writes.append((pos, before_b, target_bytes))
                if all(before_b == target_b for _, before_b, target_b in writes):
                    raise XdfError(f"{patch.title}: requested patch state leaves image unchanged")
                touched_bytes.update(patch_byte_set)
                for pos, _, target_b in writes:
                    output[pos : pos + len(target_b)] = target_b
                first_pos = writes[0][0]
                applied_by_idx[orig_idx] = {
                    "kind": "patch",
                    "id": patch.item_id,
                    "axis": "",
                    "index": None,
                    "title": patch.title,
                    "row": None,
                    "col": None,
                    "x": "",
                    "y": "",
                    "units": "",
                    "address": f"0x{patch.entries[0].address:X}",
                    "image_offset": f"0x{first_pos:X}",
                    "before_raw": current_hex_list,
                    "after_raw": [tb.hex() for _, _, tb in writes],
                    "before": bool(info["applied"]),
                    "requested": wanted_apply,
                    "after": wanted_apply,
                    "quantized": False,
                    "before_hex": "".join(bb.hex() for _, bb, _ in writes),
                    "after_hex": "".join(tb.hex() for _, _, tb in writes),
                    "entries": [
                        {
                            "name": entry.name,
                            "image_offset": f"0x{pos:X}",
                            "before_hex": bb.hex(),
                            "after_hex": tb.hex(),
                        }
                        for entry, (pos, bb, tb) in zip(patch.entries, writes)
                    ],
                }
                continue

            axis_name = ""
            table_for_that: XdfTable | None = None
            if kind == "axis":
                table = self._item("table", ref)
                axis_name = str(change.get("axis") or "").lower()
                if axis_name not in ("x", "y"):
                    raise XdfError(f"{table.title}: axis changes need axis 'x' or 'y'")
                value_item = table.x if axis_name == "x" else table.y
                embedded = value_item.embedded
                item_id = table.item_id
                title = f"{table.title} ({axis_name} axis)"
                units = value_item.units
                equation = value_item.math
                decimalpl = None
                try:
                    index = int(change.get("index"))
                except (TypeError, ValueError):
                    raise XdfError(f"{title}: axis changes need a numeric index") from None
                if embedded is None:
                    raise XdfError(
                        f"{title}: static-label axes are definitions, not image "
                        "data, and cannot be edited"
                    )
                if not 0 <= index < embedded.count:
                    raise XdfError(
                        f"{title}: index {index} is outside 0..{embedded.count - 1}"
                    )
                row, col = index, 0
            else:
                item = self._item(kind, ref)
                embedded = item.embedded
                if embedded is None:
                    raise XdfError(f"{item.title}: no embedded data")
                item_id = item.item_id
                title = item.title
                units = item.units
                equation = item.math
                decimalpl = item.decimalpl
                if kind == "table":
                    table_for_that = item
                    try:
                        row, col = int(change.get("row")), int(change.get("col"))
                    except (TypeError, ValueError):
                        raise XdfError(
                            f"{title}: table changes need numeric row and col"
                        ) from None
                    if not (0 <= row < embedded.rows and 0 <= col < embedded.cols):
                        raise XdfError(
                            f"{title}: cell ({row}, {col}) is outside "
                            f"{embedded.rows}x{embedded.cols}"
                        )
                    index = row * embedded.cols + col
                else:
                    row = col = 0
                    index = 0

            target_key = (kind, f"{item_id}:{axis_name}", index)
            if target_key in touched:
                raise XdfError(
                    f"{title}: cell ({row}, {col}) is changed more than once"
                )
            touched.add(target_key)

            offset = self.file_offset(embedded.address) - address_base
            before_raws = embedded.read(
                source, offset, little_endian=self.little_endian
            )
            before_raw = before_raws[index]
            if "expected_raw" not in change:
                raise XdfError(
                    f"{title}: expected_raw is required so the source map "
                    "can be verified"
                )
            eff_le = (
                self.little_endian
                if embedded.little_endian is None
                else embedded.little_endian
            )
            if embedded.is_float:
                try:
                    exp_f = float(change["expected_raw"])
                    if isinstance(change["expected_raw"], bool) or not math.isfinite(exp_f):
                        raise ValueError
                    fmt = ("<" if eff_le else ">") + ("f" if embedded.size_bits == 32 else "d")
                    exp_packed = struct.pack(fmt, exp_f)
                    before_packed = struct.pack(fmt, float(before_raw))
                except (TypeError, ValueError, OverflowError, struct.error):
                    raise XdfError(
                        f"{title}: expected_raw {change.get('expected_raw')!r} "
                        "is not a finite float"
                    ) from None
                if exp_packed != before_packed and not math.isclose(
                    exp_f, float(before_raw),
                    rel_tol=1e-6 if embedded.size_bits == 32 else 1e-12,
                    abs_tol=1e-7 if embedded.size_bits == 32 else 1e-12,
                ):
                    raise XdfError(
                        f"{title}: source changed at ({row}, {col}); expected "
                        f"raw {exp_f}, found {before_raw}. Render the source again."
                    )
            else:
                try:
                    expected_value = change["expected_raw"]
                    expected_raw = int(expected_value)
                    if isinstance(expected_value, bool) or expected_raw != float(expected_value):
                        raise ValueError
                except (TypeError, ValueError):
                    raise XdfError(
                        f"{title}: expected_raw {change.get('expected_raw')!r} "
                        "is not an integer"
                    ) from None
                if expected_raw != before_raw:
                    raise XdfError(
                        f"{title}: source changed at ({row}, {col}); expected "
                        f"raw {expected_raw}, found {before_raw}. Render the source again."
                    )

            eq_before = (
                self._cell_equation(
                    table_for_that, source, row, col, address_base=address_base
                )
                if table_for_that is not None and table_for_that.that_refs
                else equation
            )
            eq_working = (
                self._cell_equation(
                    table_for_that, bytes(output), row, col, address_base=address_base
                )
                if table_for_that is not None and table_for_that.that_refs
                else equation
            )
            if embedded.is_float:
                new_raw, actual = inverse_float_math(
                    eq_working,
                    change.get("value"),
                    size_bits=embedded.size_bits,
                    little_endian=eff_le,
                    decimalpl=decimalpl,
                )
            else:
                new_raw, actual = inverse_math(
                    eq_working,
                    change.get("value"),
                    size_bits=embedded.size_bits,
                    signed=embedded.signed,
                    decimalpl=decimalpl,
                    prior_raw=int(before_raw),
                )
            before_value = eval_math(eq_before, before_raw)
            if decimalpl is not None:
                before_value = round(before_value, decimalpl)
            if embedded.is_float:
                fmt = ("<" if eff_le else ">") + ("f" if embedded.size_bits == 32 else "d")
                if struct.pack(fmt, float(new_raw)) == struct.pack(fmt, float(before_raw)):
                    raise XdfError(
                        f"{title}: requested value leaves ({row}, {col}) unchanged"
                    )
            elif new_raw == before_raw:
                raise XdfError(
                    f"{title}: requested value leaves ({row}, {col}) unchanged"
                )
            pos, size = embedded.positions(offset)[index]
            byte_range = set(range(pos, pos + size))
            if (touched_bytes & byte_range) or any(b in touched_flag_bits for b in byte_range):
                raise XdfError(f"{title}: overlapping byte writes in this change set")
            touched_bytes.update(byte_range)
            pos, before_bytes, after_bytes = embedded.write_one(
                output, offset, index, new_raw,
                little_endian=self.little_endian,
            )
            requested = float(change["value"])
            applied_by_idx[orig_idx] = {
                "kind": kind,
                "id": item_id,
                "axis": axis_name,
                "index": index if kind == "axis" else None,
                "title": title,
                "row": row if kind == "table" else None,
                "col": col if kind == "table" else None,
                "x": str(change.get("x") or "") if kind == "table" else "",
                "y": str(change.get("y") or "") if kind == "table" else "",
                "units": units,
                "address": f"0x{embedded.address:X}",
                "image_offset": f"0x{pos:X}",
                "before_raw": before_raw,
                "after_raw": new_raw,
                "before": before_value,
                "requested": requested,
                "after": actual,
                "quantized": not math.isclose(
                    actual, requested, rel_tol=1e-12, abs_tol=1e-12
                ),
                "before_hex": before_bytes.hex(),
                "after_hex": after_bytes.hex(),
            }

        applied = [applied_by_idx[i] for i in range(len(changes))]
        return bytes(output), applied

    def diff(self, before, after, *, address_base: int | None = None) -> dict:
        """Named differences between two dumps across tables, constants, flags and patches."""
        a = self._bytes(before)
        b = self._bytes(after)
        if len(a) != len(b):
            raise XdfError(
                f"images differ in size ({len(a)} vs {len(b)}); "
                "compare like with like"
            )
        if address_base is None:
            address_base = self.suggest_address_base(len(a))

        tables: list[dict] = []
        for table in self.tables:
            offset = self.file_offset(table.embedded.address) - address_base
            try:
                eq_a = (
                    (lambda r, c, tbl=table: self._cell_equation(
                        tbl, a, r, c, address_base=address_base
                    ))
                    if table.that_refs else None
                )
                eq_b = (
                    (lambda r, c, tbl=table: self._cell_equation(
                        tbl, b, r, c, address_base=address_base
                    ))
                    if table.that_refs else None
                )
                before_rows = table.values(
                    a, offset, little_endian=self.little_endian, cell_eq_fn=eq_a
                )
                after_rows = table.values(
                    b, offset, little_endian=self.little_endian, cell_eq_fn=eq_b
                )
                x_offset = (
                    self.file_offset(table.x.embedded.address) - address_base
                    if table.x.embedded is not None else offset
                )
                y_offset = (
                    self.file_offset(table.y.embedded.address) - address_base
                    if table.y.embedded is not None else offset
                )
                x, _ = self.axis_labels(
                    table.x, a, x_offset, address_base=address_base
                )
                y, _ = self.axis_labels(
                    table.y, a, y_offset, address_base=address_base
                )
                x_after, _ = self.axis_labels(
                    table.x, b, x_offset, address_base=address_base
                )
                y_after, _ = self.axis_labels(
                    table.y, b, y_offset, address_base=address_base
                )
            except XdfError as exc:
                tables.append({"title": table.title, "error": str(exc)})
                continue

            cells = []
            for r, (row_a, row_b) in enumerate(zip(before_rows, after_rows)):
                for c, (va, vb) in enumerate(zip(row_a, row_b)):
                    if va != vb:
                        cells.append({
                            "row": r, "col": c,
                            "x": x[c] if c < len(x) else str(c),
                            "y": y[r] if r < len(y) else str(r),
                            "before": va, "after": vb,
                        })
            axis_changes = []
            for axis_name, before_axis, after_axis, axis in (
                ("x", x, x_after, table.x),
                ("y", y, y_after, table.y),
            ):
                for index, (before_value, after_value) in enumerate(
                    zip(before_axis, after_axis)
                ):
                    if before_value != after_value:
                        axis_changes.append({
                            "axis": axis_name,
                            "index": index,
                            "units": axis.units,
                            "before": before_value,
                            "after": after_value,
                        })
            if cells or axis_changes:
                tables.append({
                    "title": table.title,
                    "category": table.category,
                    "units": table.units,
                    "changed_cells": len(cells),
                    "cells": cells[:512],
                    "cells_truncated": len(cells) > 512,
                    "axis_changes": axis_changes,
                })

        constants = []
        for const in self.constants:
            offset = self.file_offset(const.embedded.address) - address_base
            try:
                va = const.value(a, offset, little_endian=self.little_endian)
                vb = const.value(b, offset, little_endian=self.little_endian)
            except XdfError:
                continue
            if va != vb:
                constants.append({
                    "title": const.title, "units": const.units,
                    "before": va, "after": vb,
                })

        flags = []
        for flag in self.flags:
            offset = self.file_offset(flag.embedded.address) - address_base
            try:
                fa = flag.is_set(a, offset, little_endian=self.little_endian)
                fb = flag.is_set(b, offset, little_endian=self.little_endian)
            except XdfError:
                continue
            if fa != fb:
                flags.append({
                    "title": flag.title,
                    "category": flag.category,
                    "address": f"0x{flag.embedded.address:X}",
                    "mask": f"0x{flag.mask:X}",
                    "before": fa,
                    "after": fb,
                })

        patches = []
        for patch in self.patches:
            try:
                pa = patch.inspect(
                    a, file_offset_fn=self.file_offset, address_base=address_base
                )
                pb = patch.inspect(
                    b, file_offset_fn=self.file_offset, address_base=address_base
                )
            except XdfError:
                continue
            changed_entries = sum(
                ea["current_hex"] != eb["current_hex"]
                for ea, eb in zip(pa["entries"], pb["entries"])
            )
            if changed_entries:
                patches.append({
                    "title": patch.title,
                    "category": patch.category,
                    "address": pa["address"],
                    "before": pa["state"],
                    "after": pb["state"],
                    "changed_entries": changed_entries,
                })

        return {
            "xdf": {"title": self.title, "path": self.path},
            "image_size": len(a),
            "address_base": address_base,
            "identical": not tables and not constants and not flags and not patches,
            "tables": tables,
            "constants": constants,
            "flags": flags,
            "patches": patches,
        }

    def validate_definition(self, image=None, *, address_base: int | None = None) -> dict:
        """Audit whether an XDF is safe and complete enough for editing.

        This does not certify that community-authored labels are physically
        correct. It catches machine-verifiable defects: duplicate ids,
        impossible geometry, out-of-region/overlapping ranges, non-invertible
        equations, render failures and non-monotonic embedded axes.
        """
        findings: list[dict] = []

        def add(level: str, check: str, detail: str, item: str = "") -> None:
            findings.append({
                "level": level, "check": check, "detail": detail, "item": item,
            })

        if not self.title:
            add("warn", "metadata", "definition has no title")
        if self.checksums:
            add(
                "warn", "calibration-checksum",
                "definition declares checksum(s) that require an explicitly "
                f"selected compatible provider: {', '.join(self.checksums)}",
            )
        else:
            add(
                "warn", "calibration-checksum",
                "definition declares no calibration checksum; this does not establish that the image needs none",
            )
        fitted = fitment(self.path)
        if not fitted.get("family"):
            add("fatal", "fitment", "filename/catalog provides no ECU family")
        else:
            add("ok", "fitment", f"cataloged for {fitted['family']}")

        ids: dict[tuple[str, str], list[str]] = {}
        for kind, items in (
            ("table", self.tables),
            ("constant", self.constants),
            ("flag", self.flags),
            ("patch", self.patches),
        ):
            for item in items:
                ids.setdefault((kind, item.item_id), []).append(item.title)
        for (kind, ident), titles in ids.items():
            if len(titles) > 1:
                add(
                    "fatal", "unique-id",
                    f"{kind} id {ident!r} is shared by {len(titles)} items",
                    " / ".join(titles),
                )

        ranges = []
        for name, offset, span_bits in self._offsets(include_flags_patches=False):
            byte_len = (span_bits + 7) // 8
            if offset < 0:
                add("fatal", "address", f"negative file offset {offset}", name)
                continue
            end = offset + byte_len
            ranges.append((offset, end, name))
            if self.region_size is not None and end > self.region_size:
                add(
                    "fatal", "region-bounds",
                    f"0x{offset:X}..0x{end - 1:X} exceeds region "
                    f"size 0x{self.region_size:X}", name,
                )
        for flag in self.flags:
            if flag.embedded is None:
                continue
            offset = self.file_offset(flag.embedded.address)
            byte_len = (flag.embedded.span_bits + 7) // 8
            if offset < 0:
                add("fatal", "address", f"negative file offset {offset}", flag.title)
            elif self.region_size is not None and offset + byte_len > self.region_size:
                add(
                    "fatal", "region-bounds",
                    f"0x{offset:X}..0x{offset + byte_len - 1:X} exceeds region "
                    f"size 0x{self.region_size:X}", flag.title,
                )
        for patch in self.patches:
            for entry in patch.entries:
                offset = self.file_offset(entry.address)
                end = offset + entry.size
                label = f"{patch.title} [{entry.name}]"
                if offset < 0:
                    add("fatal", "address", f"negative file offset {offset}", label)
                elif self.region_size is not None and end > self.region_size:
                    add(
                        "fatal", "region-bounds",
                        f"0x{offset:X}..0x{end - 1:X} exceeds region "
                        f"size 0x{self.region_size:X}", label,
                    )
        for index, (start, end, name) in enumerate(sorted(ranges)):
            for other_start, other_end, other_name in sorted(ranges)[index + 1:]:
                if other_start >= end:
                    break
                if name != other_name:
                    add(
                        "warn", "overlap",
                        f"0x{max(start, other_start):X}.."
                        f"0x{min(end, other_end) - 1:X} also belongs to {other_name}",
                        name,
                    )

        writable = [
            ("table", item.title, item.math, item.embedded, item.decimalpl)
            for item in self.tables
        ] + [
            ("constant", item.title, item.math, item.embedded, item.decimalpl)
            for item in self.constants
        ] + [
            ("axis", f"{table.title} ({axis_name} axis)", axis.math, axis.embedded, None)
            for table in self.tables
            for axis_name, axis in (("x", table.x), ("y", table.y))
            if axis.embedded is not None
        ]
        for kind, title, equation, embedded, decimals in writable:
            if embedded is None:
                continue
            probe_eq = _THAT_CALL.sub("(0)", equation)
            if embedded.is_float:
                eff_le = (
                    self.little_endian
                    if embedded.little_endian is None
                    else embedded.little_endian
                )
                float_samples = (-10.5, 0.0, 42.25)
                usable = 0
                for raw_f in float_samples:
                    try:
                        engineering = eval_math(probe_eq, raw_f)
                        inv_f, _ = inverse_float_math(
                            probe_eq, engineering, size_bits=embedded.size_bits,
                            little_endian=eff_le, decimalpl=decimals,
                        )
                        if math.isclose(inv_f, raw_f, rel_tol=1e-5, abs_tol=1e-6):
                            usable += 1
                    except XdfError:
                        pass
                sample_count = len(float_samples)
            else:
                if embedded.signed:
                    low, high = -(1 << (embedded.size_bits - 1)), (1 << (embedded.size_bits - 1)) - 1
                else:
                    low, high = 0, (1 << embedded.size_bits) - 1
                samples = {low, high, low + (high - low) // 2}
                usable = 0
                for raw in samples:
                    try:
                        engineering = eval_math(probe_eq, raw)
                        inverse, _ = inverse_math(
                            probe_eq, engineering, size_bits=embedded.size_bits,
                            signed=embedded.signed, decimalpl=decimals,
                            prior_raw=raw,
                        )
                        if inverse == raw:
                            usable += 1
                    except XdfError:
                        pass
                sample_count = len(samples)
            if not usable:
                add(
                    "fatal", "write-equation",
                    f"{kind} equation {equation!r} cannot round-trip a raw value",
                    title,
                )
            elif usable < sample_count:
                add(
                    "warn", "write-equation",
                    f"equation {equation!r} round-tripped {usable}/{sample_count} samples",
                    title,
                )
            else:
                add(
                    "ok", "write-equation",
                    f"equation {equation!r} round-tripped all sampled raw values",
                    title,
                )

        render = None
        if image is not None:
            try:
                render = self.render(image, address_base=address_base)
            except XdfError as exc:
                add("fatal", "render", str(exc))
            else:
                for error in render.get("errors", []):
                    add("fatal", "render", error["reason"], error.get("title", ""))
                for table in render.get("tables", []):
                    for axis_name in ("x", "y"):
                        axis = table.get("axes", {}).get(axis_name, {})
                        if not axis.get("editable"):
                            continue
                        try:
                            values = [float(value) for value in axis.get("values", [])]
                        except ValueError:
                            continue
                        if any(b <= a for a, b in zip(values, values[1:])):
                            add(
                                "warn", "axis-order",
                                f"embedded {axis_name} axis is not strictly increasing",
                                table["title"],
                            )
                        else:
                            add(
                                "ok", "axis-order",
                                f"embedded {axis_name} axis is strictly increasing",
                                table["title"],
                            )

        fatal = sum(f["level"] == "fatal" for f in findings)
        warnings = sum(f["level"] == "warn" for f in findings)
        return {
            "ok": fatal == 0,
            "fatal": fatal,
            "warnings": warnings,
            "findings": findings,
            "definition": self.describe(),
            "render": render,
            "note": (
                "Structural validation cannot prove that community labels, "
                "addresses or recommended values are physically correct."
            ),
        }

    def describe(self) -> dict:
        return {
            "title": self.title,
            "path": self.path,
            "version": self.version,
            "tables": len(self.tables),
            "constants": len(self.constants),
            "flags": len(self.flags),
            "patches": len(self.patches),
            "unsupported": len(self.unsupported),
            "region_size": self.region_size,
            "categories": sorted(self.categories.values()),
            **fitment(self.path),
        }


# --------------------------------------------------------------------------
# Fitment: which motorcycles a definition actually belongs to
# --------------------------------------------------------------------------
#
# An XDF title is whatever its author typed ("15M Marelli", sometimes
# nothing at all), so it is useless for picking the right definition and
# dangerous as the only label in a drop-down: two unrelated bikes can share
# it. ``guzzionboard/xdfs/catalog.json`` carries the real provenance for
# every bundled file - brand, ECU family and the list of motorcycles the
# GuzziDiag archive publishes it for - and that is what the UI groups by.

#: Catalog of the bundled library, see docs/XDF_LIBRARY.md.
XDF_CATALOG_PATH = BUNDLED_XDF_DIR / "catalog.json"

#: Display names for the brand folders/keys used in catalog.json.
BRAND_LABELS = {
    "aprilia": "Aprilia",
    "bmw": "BMW",
    "ducati": "Ducati",
    "gasgas": "GasGas",
    "gilera": "Gilera",
    "honda": "Honda",
    "husqvarna": "Husqvarna",
    "malaguti": "Malaguti",
    "morini": "Moto Morini",
    "moto_guzzi": "Moto Guzzi",
    "piaggio": "Piaggio",
    "scomadi": "Scomadi",
}

#: ECU families that name themselves in an XDF filename prefix.
_FAMILY_PREFIXES = (
    "MIUG3", "MIU1", "MBC1", "15RC", "15M", "15P", "16M", "59M",
    "5AM", "5SM", "5DM", "7SM", "11MP", "P7", "P8",
)

_catalog_cache: tuple[float, dict[str, dict]] | None = None


def brand_label(brand: str) -> str:
    key = (brand or "").strip().lower()
    return BRAND_LABELS.get(key, key.replace("_", " ").title() or "Unknown")


def load_xdf_catalog() -> dict[str, dict]:
    """``catalog.json`` keyed by XDF filename (cached on file mtime).

    A missing or broken catalog is not fatal: fitment then falls back to
    what can be read off the filename.
    """
    global _catalog_cache
    try:
        stamp = XDF_CATALOG_PATH.stat().st_mtime
    except OSError:
        return {}
    if _catalog_cache and _catalog_cache[0] == stamp:
        return _catalog_cache[1]
    import json

    try:
        entries = json.loads(XDF_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    by_name: dict[str, dict] = {}
    for entry in entries if isinstance(entries, list) else []:
        name = str(entry.get("xdf_filename") or "")
        if name:
            by_name[name.lower()] = entry
    _catalog_cache = (stamp, by_name)
    return by_name


def family_from_filename(name: str) -> str:
    stem = Path(name).name.upper()
    for family in _FAMILY_PREFIXES:
        if stem.startswith(family + "_") or stem == family + ".XDF":
            return family
    return ""


def fitment(path: str | Path | None) -> dict:
    """What motorcycles a definition file applies to.

    Returns the catalog facts a chooser needs: ``filename`` (the stable
    identifier to select by - titles collide), ``family`` (the ECU family,
    the thing that must match the bike on the bench), ``label``, and
    ``fits``: every brand/model the archive publishes this definition for.
    """
    name = Path(path).name if path else ""
    entry = load_xdf_catalog().get(name.lower(), {})
    brand = str(entry.get("brand") or "")
    if not brand and path:
        parent = Path(path).parent.name.lower()
        if parent in BRAND_LABELS:
            brand = parent
    family = str(entry.get("family") or "") or family_from_filename(name)
    label = str(entry.get("label") or "") or Path(name).stem.replace("_", " ")
    used_by = entry.get("used_by") or ([{"brand": brand, "label": label}] if brand else [])
    fits = [
        {
            "brand": str(u.get("brand") or ""),
            "brand_label": brand_label(str(u.get("brand") or "")),
            "label": str(u.get("label") or ""),
        }
        for u in used_by
        if isinstance(u, dict)
    ]
    return {
        "filename": name,
        "brand": brand,
        "brand_label": brand_label(brand) if brand else "Uncatalogued",
        "family": family,
        "label": label,
        "fits": fits,
        "fits_brands": sorted({f["brand_label"] for f in fits if f["brand_label"]}),
        "catalogued": bool(entry),
        "research_only": bool(entry.get("research_only")),
        "source_url": str(entry.get("source_url") or ""),
    }


def group_xdfs(described: list[dict]) -> list[dict]:
    """Group described XDFs by the motorcycles they apply to.

    One group per brand, each holding one sub-group per ECU family, so a
    drop-down can be rendered as "Moto Guzzi / 5AM" -> the actual models
    rather than as 94 interchangeable-looking titles. A definition that
    the archive lists for several brands appears under each of them -
    that is a fact about the file, not a duplicate.
    """
    groups: dict[str, dict] = {}
    for entry in described:
        brands = {
            (f.get("brand") or "", f.get("brand_label") or "")
            for f in entry.get("fits") or []
        } or {(entry.get("brand", ""), entry.get("brand_label", "Uncatalogued"))}
        for brand, label in sorted(brands):
            group = groups.setdefault(
                label, {"brand": brand, "brand_label": label, "families": {}}
            )
            family = entry.get("family") or "unknown"
            group["families"].setdefault(family, []).append(entry["filename"])
    out = []
    for label in sorted(groups, key=str.lower):
        group = groups[label]
        out.append(
            {
                "brand": group["brand"],
                "brand_label": label,
                "families": [
                    {"family": fam, "files": sorted(files)}
                    for fam, files in sorted(group["families"].items())
                ],
            }
        )
    return out


def load_xdfs(directory: str | Path = XDF_DIR, *, recursive: bool = False) -> list[XdfFile]:
    """Every parseable XDF in a directory, like the key loader.

    ``recursive`` walks subdirectories too, which is how the bundled library
    (organised one folder per brand) is read; the flat, non-recursive default
    is unchanged for the user override directory.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    globber = directory.rglob if recursive else directory.glob
    paths = sorted(globber("*.xdf")) + sorted(globber("*.XDF"))
    out: list[XdfFile] = []
    for path in paths:
        try:
            out.append(XdfFile.from_file(path))
        except XdfError:
            continue          # a broken third-party file must not kill the app
    return out


def load_bundled_xdfs() -> list[XdfFile]:
    """Every XDF vendored into the project under ``guzzionboard/xdfs/``."""
    return load_xdfs(BUNDLED_XDF_DIR, recursive=True)


def available_xdfs(user_directory: str | Path = XDF_DIR) -> list[XdfFile]:
    """The bundled library plus any user-supplied override directory.

    A user file whose *filename* matches a bundled one replaces it (so an
    updated or corrected XDF can be dropped in without editing the repo);
    everything else from both sources is included. Filenames, not titles,
    are the identity here: XDF titles collide ("15M Marelli" is on several
    unrelated files) and are sometimes empty.

    The result is ordered the way a chooser wants to show it: by brand,
    then ECU family, then model label.
    """
    bundled = load_bundled_xdfs()
    user = load_xdfs(user_directory)
    user_names = {Path(x.path).name.lower() for x in user if x.path}
    merged = [
        x for x in bundled if Path(x.path).name.lower() not in user_names
    ] + user

    def order(x: XdfFile) -> tuple:
        fit = fitment(x.path)
        return (
            not fit["catalogued"],          # catalogued first
            fit["brand_label"].lower(),
            fit["family"],
            fit["label"].lower(),
            x.path,
        )

    merged.sort(key=order)
    return merged
