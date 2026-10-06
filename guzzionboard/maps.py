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
  table with its axis labels and engineering values;
* :meth:`XdfFile.diff` compares two dumps and reports *named* changes -
  "Spark High-Octane Table, row 1200 RPM, col 0.84 g/cyl: 28.1 -> 30.0"
  instead of "run at 0xF1BE, 2 bytes".

XDFs are third-party files. A growing set ships with this project under
``guzzionboard/xdfs/`` (see ``docs/XDF_LIBRARY.md`` for provenance and how to
add more) — :func:`available_xdfs` finds those automatically. Anything not
(yet) bundled can still be dropped into ``~/.guzzionboard/xdfs/`` the same way
key providers go into ``~/.guzzionboard/keys/``; a user-supplied file with the
same title overrides a bundled one. The origin for all of these is
https://www.von-der-salierburg.de/download/GuzziDiag/ (TunerPro XDF section).

One wrinkle worth understanding: XDF addresses are offsets into the *file
the XDF was authored against* - usually the full device image including the
bootloader. A GuzziOnBoard flash read is the 0x4C000-byte region starting at
device 0x4000, so rendering a region dump needs ``address_base=0x4000``.
That base is auto-detected from the image size and always reported back.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

#: Where user-supplied XDFs are looked for, mirroring the key plugin dir.
XDF_DIR = Path.home() / ".guzzionboard" / "xdfs"

#: XDFs vendored into the project itself, see docs/XDF_LIBRARY.md.
BUNDLED_XDF_DIR = Path(__file__).resolve().parent / "xdfs"


class XdfError(Exception):
    """An XDF or image could not be interpreted."""


# --------------------------------------------------------------------------
# The MATH equation: "X/4096", "X*0.05859372", ...
# --------------------------------------------------------------------------
#
# Only value-only equations are supported (a bare X plus arithmetic). The
# per-cell "<VAR type=\"address\">" form used by a few information tables
# references other locations and is reported as unsupported rather than
# guessed at.

_MATH_ALLOWED = re.compile(r"^[Xx0-9+\-*/()., ]+$")


def _math_equation(node: ET.Element) -> str:
    """The equation of a MATH element: <MATH equation="X/4096">."""
    math = node.find("MATH")
    if math is None:
        return "X"
    return (math.get("equation") or "X").strip()


def eval_math(equation: str, x: float) -> float:
    """Evaluate a TunerPro MATH equation for one raw value."""
    if not _MATH_ALLOWED.match(equation or ""):
        raise XdfError(f"unsupported equation {equation!r}")
    text = equation.replace(" ", "").replace("X", "(X)").replace("x", "(X)")
    if "**" in text:
        raise XdfError(f"unsupported equation {equation!r}")
    try:
        return float(eval(text, {"__builtins__": {}}, {"X": float(x)}))  # noqa: S307
    except (ArithmeticError, ValueError, SyntaxError) as exc:
        raise XdfError(f"equation {equation!r} failed on {x}: {exc}") from exc


def inverse_math(
    equation: str,
    value: float,
    *,
    size_bits: int,
    signed: bool,
    decimalpl: int | None = None,
) -> tuple[int, float]:
    """Find the integer XDF raw value nearest an engineering value.

    XDF equations in the bundled library are overwhelmingly affine
    (``X/10``, ``X-40``) with a handful of reciprocal forms.  Rather than
    rewriting user-supplied expressions or silently truncating, this function
    evaluates the already-sandboxed equation and searches each monotonic raw
    domain.  The result is accepted only when it is representable to within
    half of one raw step.  The returned engineering value is the value that
    will actually be displayed after quantisation.
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
    for raw in (-2, -1, 1, 2, 3):
        if low <= raw <= high:
            candidates.add(raw)

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
        evaluated, key=lambda pair: abs(shown(pair[1]) - wanted)
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
    return int(str(text).strip(), 0)


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

    @classmethod
    def parse(cls, node: ET.Element, *, signed_default: bool = False) -> "Embedded":
        size_bits = _int(node.get("mmedelementsizebits"), 8)
        if size_bits not in (8, 16, 32):
            raise XdfError(f"unsupported element size {size_bits} bits")
        type_flags = _int(node.get("mmedtypeflags"))
        return cls(
            address=_int(node.get("mmedaddress")),
            size_bits=size_bits,
            rows=max(1, _int(node.get("mmedrowcount"), 1)),
            cols=max(1, _int(node.get("mmedcolcount"), 1)),
            major_stride_bits=_int(node.get("mmedmajorstridebits")),
            minor_stride_bits=_int(node.get("mmedminorstridebits")),
            signed=bool(type_flags & 0x1) or signed_default,
        )

    @property
    def count(self) -> int:
        return self.rows * self.cols

    @property
    def span_bits(self) -> int:
        minor = self.minor_stride_bits or self.size_bits
        major = self.major_stride_bits or (minor * self.cols)
        return (self.rows - 1) * major + (self.cols - 1) * minor + self.size_bits

    def positions(self, offset: int) -> list[tuple[int, int]]:
        """``(image offset, byte length)`` for each row-major element."""
        size = self.size_bits // 8
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

    def read(self, image: bytes, offset: int, *, little_endian: bool) -> list[int]:
        """Every raw element, row-major."""
        out: list[int] = []
        for pos, size in self.positions(offset):
            chunk = image[pos : pos + size]
            if pos < 0 or len(chunk) != size:
                raise XdfError(
                    f"data at 0x{self.address:X} falls outside the image"
                )
            out.append(int.from_bytes(chunk, "little" if little_endian
                                      else "big", signed=self.signed))
        return out

    def write_one(
        self, image: bytearray, offset: int, index: int, raw: int,
        *, little_endian: bool,
    ) -> tuple[int, bytes, bytes]:
        """Write one integer element without touching adjacent bytes.

        Returns its image offset plus the before/after byte strings.  Range,
        bounds and integer checks are deliberately here at the byte boundary;
        no caller can accidentally get Python's truncation or wrapping.
        """
        positions = self.positions(offset)
        if not 0 <= index < len(positions):
            raise XdfError(
                f"cell index {index} is outside {self.rows}x{self.cols} data"
            )
        if isinstance(raw, bool) or int(raw) != raw:
            raise XdfError(f"raw value {raw!r} is not an integer")
        raw = int(raw)
        if self.signed:
            low, high = -(1 << (self.size_bits - 1)), (1 << (self.size_bits - 1)) - 1
        else:
            low, high = 0, (1 << self.size_bits) - 1
        if not low <= raw <= high:
            raise XdfError(
                f"raw value {raw} is outside the {self.size_bits}-bit "
                f"{'signed' if self.signed else 'unsigned'} range {low}..{high}"
            )
        pos, size = positions[index]
        if pos < 0 or pos + size > len(image):
            raise XdfError(
                f"data at 0x{self.address:X} falls outside the image"
            )
        before = bytes(image[pos : pos + size])
        after = raw.to_bytes(
            size, "little" if little_endian else "big", signed=self.signed
        )
        image[pos : pos + size] = after
        return pos, before, after


@dataclass
class Axis:
    """One axis of a table: static LABELs or values embedded in the dump."""

    ident: str                    # "x" | "y"
    units: str = ""
    labels: list[str] = field(default_factory=list)
    count: int = 1
    embedded: Embedded | None = None
    math: str = "X"

    @classmethod
    def parse(cls, node: ET.Element, *, signed_default: bool) -> "Axis":
        units = (node.findtext("units") or "").strip()
        count = max(1, _int(node.findtext("indexcount"), 1))
        labels: dict[int, str] = {}
        for label in node.findall("LABEL"):
            labels[_int(label.get("index"))] = (label.get("value") or "").strip()
        math = _math_equation(node)

        embedded = None
        data_node = node.find("EMBEDDEDDATA")
        if data_node is not None and data_node.get("mmedaddress") is not None:
            embedded = Embedded.parse(data_node, signed_default=signed_default)
            embedded.rows, embedded.cols = 1, count

        return cls(
            ident=node.get("id") or "?",
            units=units,
            labels=[labels.get(i, "") for i in range(count)],
            count=count,
            embedded=embedded,
            math=math,
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
        return {
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
        }


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

    def raw(self, image: bytes, offset: int, *, little_endian: bool) -> int:
        if self.embedded is None:
            raise XdfError(f"{self.title}: no embedded data")
        return self.embedded.read(image, offset, little_endian=little_endian)[0]

    def value(self, image: bytes, offset: int, *, little_endian: bool) -> float:
        return eval_math(
            self.math, self.raw(image, offset, little_endian=little_endian)
        )

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
            "editable": self.embedded is not None,
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

    def values(self, image: bytes, offset: int,
               *, little_endian: bool) -> list[list[float]]:
        """Engineering values, one row per y (row) axis entry."""
        if self.embedded is None:
            raise XdfError(f"{self.title}: no embedded data")
        raw = self.embedded.read(image, offset, little_endian=little_endian)
        rows: list[list[float]] = []
        for r in range(self.embedded.rows):
            row = []
            for c in range(self.embedded.cols):
                value = eval_math(self.math, raw[r * self.embedded.cols + c])
                row.append(round(value, self.decimalpl) if self.decimalpl else value)
            rows.append(row)
        return rows

    @property
    def item_id(self) -> str:
        return self.uniqueid or (
            f"address:0x{self.embedded.address:X}" if self.embedded else self.title
        )

    def as_dict(self, image: bytes, offsets: dict,
                *, little_endian: bool) -> dict:
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
            "values": self.values(image, offsets["data"], little_endian=little_endian),
            "raw_values": raw_rows,
            "equation": self.math,
            "size_bits": self.embedded.size_bits if self.embedded else 0,
            "signed": self.embedded.signed if self.embedded else False,
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
    region_size: int | None = None
    base_offset: int = 0
    base_subtract: bool = False
    little_endian: bool = False
    signed_default: bool = False
    categories: dict[int, str] = field(default_factory=dict)
    tables: list[XdfTable] = field(default_factory=list)
    constants: list[XdfConstant] = field(default_factory=list)
    checksums: list[str] = field(default_factory=list)
    unsupported: list[dict] = field(default_factory=list)

    # -- parsing ----------------------------------------------------------
    @classmethod
    def from_file(cls, path: str | Path) -> "XdfFile":
        path = Path(path)
        try:
            text = path.read_text(encoding="ISO-8859-1")
        except OSError as exc:
            raise XdfError(f"cannot read {path}: {exc}") from exc
        xdf = cls.from_string(text)
        xdf.path = str(path)
        return xdf

    @classmethod
    def from_string(cls, text: str) -> "XdfFile":
        try:
            root = ET.fromstring(text)
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

        for node in root.findall("XDFCHECKSUM"):
            title = (node.findtext("title") or "").strip()
            if title:
                xdf.checksums.append(title)

        if not xdf.tables and not xdf.constants:
            raise XdfError(
                f"no readable tables or constants (root tag {root.tag!r})"
            )
        return xdf

    @staticmethod
    def _check_math(node: ET.Element, what: str) -> str:
        """Reject per-cell or cross-referencing equations we cannot honour."""
        maths = node.findall("MATH")
        equation = _math_equation(node)
        if len(maths) > 1 or any(
            var.get("type") for m in maths for var in m.findall("VAR")
        ):
            raise XdfError(
                f"{what}: per-cell or address-linked equations are not supported"
            )
        if not _MATH_ALLOWED.match(equation):
            raise XdfError(f"{what}: unsupported equation {equation!r}")
        return equation

    @classmethod
    def _parse_table(cls, node: ET.Element, category: str,
                     xdf: "XdfFile") -> XdfTable:
        title = (node.findtext("title") or "").strip() or "(untitled table)"
        axes: dict[str, Axis] = {}
        for axis_node in node.findall("XDFAXIS"):
            axis = Axis.parse(axis_node, signed_default=xdf.signed_default)
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
        table.math = cls._check_math(z_node, title)
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
            embedded=Embedded.parse(data_node, signed_default=xdf.signed_default),
            math=cls._check_math(node, title),
            decimalpl=_int(node.findtext("decimalpl")) or None
            if node.findtext("decimalpl") else None,
            uniqueid=node.get("uniqueid") or "",
        )

    # -- addressing -------------------------------------------------------
    def file_offset(self, address: int) -> int:
        """XDF address -> offset in the bin the XDF was authored against."""
        if self.base_subtract:
            return address - self.base_offset
        return address + self.base_offset

    def _offsets(self) -> list[tuple[str, int, int]]:
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

    def render(self, image, *, address_base: int | None = None) -> dict:
        """Every table and constant with its engineering values."""
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
            try:
                entry = table.as_dict(
                    data,
                    {
                        "data": data_offset,
                        "x": axis_offset(table.x, data_offset),
                        "y": axis_offset(table.y, data_offset),
                    },
                    little_endian=self.little_endian,
                )
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
            "unsupported": self.unsupported,
            "errors": errors,
            "checksums": self.checksums,
        }

    def _item(self, kind: str, ref: str):
        """Resolve a stable item id, with an unambiguous title fallback."""
        items = self.tables if kind == "table" else self.constants if kind == "constant" else []
        if not items:
            if kind not in ("table", "constant"):
                raise XdfError(f"unknown change kind {kind!r}")
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

    def apply_changes(
        self, image, changes: list[dict], *, address_base: int | None = None
    ) -> tuple[bytes, list[dict]]:
        """Apply explicit engineering-value edits to a copy of an image.

        Every request names an XDF item and carries the raw value the operator
        saw.  That optimistic-lock value prevents a recommendation prepared
        against one map being silently applied to another.  The source bytes
        are never mutated and the result records the exact byte offset and
        quantised value for a reviewable build manifest.
        """
        source = self._bytes(image)
        if address_base is None:
            address_base = self.suggest_address_base(len(source))
        if not isinstance(changes, list) or not changes:
            raise XdfError("at least one map change is required")
        if len(changes) > 4096:
            raise XdfError("a tuning build is limited to 4096 explicit changes")

        output = bytearray(source)
        applied: list[dict] = []
        touched: set[tuple[str, str, int]] = set()
        for number, change in enumerate(changes, 1):
            if not isinstance(change, dict):
                raise XdfError(f"change {number} is not an object")
            kind = str(change.get("kind") or "").strip().lower()
            ref = str(change.get("id") or change.get("item_id") or change.get("title") or "")
            if not ref:
                raise XdfError(f"change {number} has no item id")

            axis_name = ""
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
                if embedded is None:  # defensive: parsed items always have one
                    raise XdfError(f"{item.title}: no embedded data")
                item_id = item.item_id
                title = item.title
                units = item.units
                equation = item.math
                decimalpl = item.decimalpl
                if kind == "table":
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

            new_raw, actual = inverse_math(
                equation,
                change.get("value"),
                size_bits=embedded.size_bits,
                signed=embedded.signed,
                decimalpl=decimalpl,
            )
            before_value = eval_math(equation, before_raw)
            if decimalpl is not None:
                before_value = round(before_value, decimalpl)
            if new_raw == before_raw:
                raise XdfError(
                    f"{title}: requested value leaves ({row}, {col}) unchanged"
                )
            pos, before_bytes, after_bytes = embedded.write_one(
                output, offset, index, new_raw,
                little_endian=self.little_endian,
            )
            requested = float(change["value"])
            applied.append({
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
            })

        return bytes(output), applied

    def diff(self, before, after, *, address_base: int | None = None) -> dict:
        """Named differences between two dumps, table by table."""
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
                before_rows = table.values(a, offset, little_endian=self.little_endian)
                after_rows = table.values(b, offset, little_endian=self.little_endian)
                x_offset = (
                    self.file_offset(table.x.embedded.address) - address_base
                    if table.x.embedded is not None else offset
                )
                y_offset = (
                    self.file_offset(table.y.embedded.address) - address_base
                    if table.y.embedded is not None else offset
                )
                x = table.x.header(
                    a, x_offset, little_endian=self.little_endian,
                )
                y = table.y.header(
                    a, y_offset, little_endian=self.little_endian,
                )
                x_after = table.x.header(
                    b, x_offset, little_endian=self.little_endian,
                )
                y_after = table.y.header(
                    b, y_offset, little_endian=self.little_endian,
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

        return {
            "xdf": {"title": self.title, "path": self.path},
            "image_size": len(a),
            "address_base": address_base,
            "identical": not tables and not constants,
            "tables": tables,
            "constants": constants,
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
                "ok", "calibration-checksum",
                "definition declares no calibration checksum",
            )
        fitted = fitment(self.path)
        if not fitted.get("family"):
            add("fatal", "fitment", "filename/catalog provides no ECU family")
        else:
            add("ok", "fitment", f"cataloged for {fitted['family']}")

        ids: dict[tuple[str, str], list[str]] = {}
        for kind, items in (("table", self.tables), ("constant", self.constants)):
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
        for name, offset, span_bits in self._offsets():
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
            if embedded.signed:
                low, high = -(1 << (embedded.size_bits - 1)), (1 << (embedded.size_bits - 1)) - 1
            else:
                low, high = 0, (1 << embedded.size_bits) - 1
            samples = {low, high, low + (high - low) // 2}
            usable = 0
            for raw in samples:
                try:
                    engineering = eval_math(equation, raw)
                    inverse, _ = inverse_math(
                        equation, engineering, size_bits=embedded.size_bits,
                        signed=embedded.signed, decimalpl=decimals,
                    )
                    if inverse == raw:
                        usable += 1
                except XdfError:
                    pass
            if not usable:
                add(
                    "fatal", "write-equation",
                    f"{kind} equation {equation!r} cannot round-trip a raw value",
                    title,
                )
            elif usable < len(samples):
                add(
                    "warn", "write-equation",
                    f"equation {equation!r} round-tripped {usable}/{len(samples)} samples",
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
