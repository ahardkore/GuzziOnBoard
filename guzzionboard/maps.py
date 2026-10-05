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

XDFs are third-party files and do not ship with this project: drop them into
``~/.guzzionboard/xdfs/`` the same way key providers go into
``~/.guzzionboard/keys/``. The files are at
https://www.von-der-salierburg.de/download/GuzziDiag/ (TunerPro XDF section).

One wrinkle worth understanding: XDF addresses are offsets into the *file
the XDF was authored against* - usually the full device image including the
bootloader. A GuzziOnBoard flash read is the 0x4C000-byte region starting at
device 0x4000, so rendering a region dump needs ``address_base=0x4000``.
That base is auto-detected from the image size and always reported back.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

#: Where user-supplied XDFs are looked for, mirroring the key plugin dir.
XDF_DIR = Path.home() / ".guzzionboard" / "xdfs"


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

    def read(self, image: bytes, offset: int, *, little_endian: bool) -> list[int]:
        """Every raw element, row-major."""
        size = self.size_bits // 8
        minor = (self.minor_stride_bits or self.size_bits) // 8
        if self.major_stride_bits:
            major = self.major_stride_bits // 8
        else:
            major = minor * self.cols
        out: list[int] = []
        for r in range(self.rows):
            for c in range(self.cols):
                pos = offset + r * major + c * minor
                chunk = image[pos : pos + size]
                if len(chunk) != size:
                    raise XdfError(
                        f"data at 0x{self.address:X} falls outside the image"
                    )
                out.append(int.from_bytes(chunk, "little" if little_endian
                                          else "big", signed=self.signed))
        return out


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

    def as_dict(self, image: bytes, offset: int,
                *, little_endian: bool) -> dict:
        raw = self.raw(image, offset, little_endian=little_endian)
        value = eval_math(self.math, raw)
        return {
            "title": self.title,
            "category": self.category,
            "units": self.units,
            "address": f"0x{self.embedded.address:X}" if self.embedded else "",
            "raw": raw,
            "value": round(value, self.decimalpl) if self.decimalpl else value,
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

    def as_dict(self, image: bytes, offsets: dict,
                *, little_endian: bool) -> dict:
        """``offsets`` carries the image offsets of the data and both axes."""
        return {
            "title": self.title,
            "category": self.category,
            "units": self.units,
            "address": f"0x{self.embedded.address:X}" if self.embedded else "",
            "rows": self.y.count,
            "cols": self.x.count,
            "x": self.x.header(image, offsets["x"], little_endian=little_endian),
            "y": self.y.header(image, offsets["y"], little_endian=little_endian),
            "values": self.values(image, offsets["data"], little_endian=little_endian),
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
                x = table.x.header(
                    a,
                    self.file_offset(table.x.embedded.address) - address_base
                    if table.x.embedded is not None else offset,
                    little_endian=self.little_endian,
                )
                y = table.y.header(
                    a,
                    self.file_offset(table.y.embedded.address) - address_base
                    if table.y.embedded is not None else offset,
                    little_endian=self.little_endian,
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
            if cells:
                tables.append({
                    "title": table.title,
                    "category": table.category,
                    "units": table.units,
                    "changed_cells": len(cells),
                    "cells": cells[:512],
                    "cells_truncated": len(cells) > 512,
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
        }


def load_xdfs(directory: str | Path = XDF_DIR) -> list[XdfFile]:
    """Every parseable XDF in the plugin directory, like the key loader."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[XdfFile] = []
    for path in sorted(directory.glob("*.xdf")) + sorted(directory.glob("*.XDF")):
        try:
            out.append(XdfFile.from_file(path))
        except XdfError:
            continue          # a broken third-party file must not kill the app
    return out
