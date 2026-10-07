"""XDF parsing: a GuzziDiag definition file turned into named tables.

The fixture below mirrors a real TunerPro v5 XDF (format 1.60): the
structure was read from a production GM file, and the GuzziDiag files
published for the IAW families use the same generator. What is exercised:

* header, categories, defaults (endianness / signedness)
* constants with MATH scaling, signed 16-bit little-endian
* 2D tables with static LABEL axes, 8-bit cells
* 3D tables with embedded axes, signed 16-bit big-endian, padded strides
* per-cell address-linked equations -> reported unsupported, never guessed
* BASEOFFSET add and subtract modes
* region vs. device addressing (the 5AM flash read starts at 0x4000)
* named diffs between two images
* the MATH evaluator safety net
"""
from __future__ import annotations

from pathlib import Path

import pytest

from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import (
    BUNDLED_XDF_DIR,
    XDF_DIR,
    XdfError,
    XdfFile,
    available_xdfs,
    eval_math,
    load_bundled_xdfs,
    load_xdfs,
)

DEVICE_SIZE = 0x50000          # the 5AM full image including bootloader
REGION_SIZE = 0x4C000          # what a flash read returns
XDF_TITLE = "5AM GuzziDiag One Lambda"


def build_xdf(
    *,
    lsbfirst: int = 0,
    signed: int = 0,
    base_offset: str = 'offset="0" subtract="0"',
    engine_table: bool = True,
) -> str:
    """A realistic XDF: one constant, one 2D and two 3D tables."""
    engine = ""
    if engine_table:
        engine = """
  <XDFTABLE uniqueid="0x2" flags="0x30">
    <title>Ignition advance</title>
    <description>Main spark table, degrees BTDC</description>
    <CATEGORYMEM index="0" category="1" />
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedaddress="0x8300" mmedelementsizebits="16" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <units>RPM</units>
      <indexcount>3</indexcount>
      <decimalpl>0</decimalpl>
      <outputtype>2</outputtype>
      <MATH equation="X*100"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <units>TPS</units>
      <indexcount>2</indexcount>
      <outputtype>2</outputtype>
      <LABEL index="0" value="closed" />
      <LABEL index="1" value="open" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z" uniqueid="0x0">
      <EMBEDDEDDATA mmedtypeflags="0x01" mmedaddress="0x8200" mmedelementsizebits="16" mmedrowcount="2" mmedcolcount="3" mmedmajorstridebits="64" mmedminorstridebits="0" />
      <units>Degrees</units>
      <decimalpl>1</decimalpl>
      <outputtype>1</outputtype>
      <MATH equation="X/45.5"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>"""
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<!-- Written 2026 by TunerPro test suite -->
<XDFFORMAT version="1.60">
  <XDFHEADER>
    <flags>0x1</flags>
    <fileversion>V1.41</fileversion>
    <deftitle>5AM GuzziDiag One Lambda</deftitle>
    <description>Test definitions for the IAW 5AM</description>
    <BASEOFFSET {base_offset} />
    <DEFAULTS datasizeinbits="16" sigdigits="2" outputtype="1" signed="{signed}" lsbfirst="{lsbfirst}" float="0" />
    <REGION type="0xFFFFFFFF" startaddress="0x0" size="0x50000" regionflags="0x0" name="Binary File" desc="Binary File" />
    <CATEGORY index="0x0" name="Fuel" />
    <CATEGORY index="0x1" name="Ignition" />
    <CATEGORY index="0xA" name="Speedo" />
  </XDFHEADER>
  <XDFCONSTANT uniqueid="0x1" flags="0xC">
    <title>Rev limiter</title>
    <description>Cut-off RPM</description>
    <CATEGORYMEM index="0" category="0" />
    <EMBEDDEDDATA mmedtypeflags="0x01" mmedaddress="0x8000" mmedelementsizebits="16" mmedmajorstridebits="0" mmedminorstridebits="0" />
    <units>RPM</units>
    <decimalpl>0</decimalpl>
    <outputtype>1</outputtype>
    <rangehigh>14000</rangehigh>
    <rangelow>0</rangelow>
    <MATH equation="X*25"><VAR id="X" /></MATH>
  </XDFCONSTANT>
  <XDFTABLE uniqueid="0x4" flags="0x30">
    <title>Speedo correction</title>
    <CATEGORYMEM index="0" category="10" />
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>1</indexcount>
      <outputtype>2</outputtype>
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>2</indexcount>
      <outputtype>2</outputtype>
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z" uniqueid="0x0">
      <EMBEDDEDDATA mmedaddress="0x8400" mmedelementsizebits="8" mmedrowcount="2" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <units>Percent</units>
      <decimalpl>0</decimalpl>
      <outputtype>1</outputtype>
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
  <XDFTABLE uniqueid="0x6" flags="0x30">
    <title>Lambda target</title>
    <CATEGORYMEM index="0" category="0" />
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <units>RPM</units>
      <indexcount>2</indexcount>
      <outputtype>2</outputtype>
      <LABEL index="0" value="1500" />
      <LABEL index="1" value="4500" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>1</indexcount>
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z" uniqueid="0x0">
      <EMBEDDEDDATA mmedaddress="0x4F000" mmedelementsizebits="8" mmedrowcount="1" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <units>Lambda</units>
      <decimalpl>3</decimalpl>
      <outputtype>1</outputtype>
      <MATH equation="X/255"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>{engine}
</XDFFORMAT>
"""


@pytest.fixture
def xdf() -> XdfFile:
    return XdfFile.from_string(build_xdf())


@pytest.fixture
def device_image() -> bytearray:
    """A full-device image with known bytes at every table location."""
    img = bytearray(DEVICE_SIZE)
    img[0x8000:0x8002] = (340).to_bytes(2, "big", signed=True)      # 340*25
    img[0x8200:0x8202] = (-455).to_bytes(2, "big", signed=True)    # row 0 col 0
    img[0x8202:0x8204] = (455).to_bytes(2, "big", signed=True)     # row 0 col 1
    img[0x8204:0x8206] = (910).to_bytes(2, "big", signed=True)     # row 0 col 2
    img[0x8208:0x820A] = (1820).to_bytes(2, "big", signed=True)    # row 1 col 0 (stride!)
    img[0x8400:0x8402] = bytes([30, 34])                           # speedo 2D
    img[0x8300:0x8306] = b"".join(
        v.to_bytes(2, "big") for v in (8, 16, 24)
    )                                                              # rpm axis *100
    img[0x4F000:0x4F002] = bytes([128, 200])                       # lambda 1D
    return img


# -- parsing --------------------------------------------------------------


def test_parses_header_categories_and_defaults(xdf: XdfFile):
    assert xdf.title == "5AM GuzziDiag One Lambda"
    assert xdf.version == "V1.41"
    assert xdf.region_size == DEVICE_SIZE
    assert xdf.base_offset == 0 and not xdf.base_subtract
    assert not xdf.little_endian          # lsbfirst=0 -> big-endian
    assert not xdf.signed_default
    assert xdf.categories == {0x0: "Fuel", 0x1: "Ignition", 0xA: "Speedo"}
    assert len(xdf.tables) == 3 and len(xdf.constants) == 1
    assert not xdf.unsupported


def test_categories_resolve_via_decimal_categorymem(xdf: XdfFile):
    spark = next(t for t in xdf.tables if "Ignition" in t.title)
    speedo = next(t for t in xdf.tables if "Speedo" in t.title)
    const = xdf.constants[0]
    assert spark.category == "Ignition"
    assert speedo.category == "Speedo"    # CATEGORYMEM category="10" == index 0xA
    assert const.category == "Fuel"


def test_rejects_files_that_are_not_xdfs():
    with pytest.raises(XdfError):
        XdfFile.from_string("<html><body>nope</body></html>")
    with pytest.raises(XdfError):
        XdfFile.from_string("<XDFFORMAT></XDFFORMAT>")   # no header, no items


def test_missing_items_make_the_file_useless(tmp_path):
    path = tmp_path / "empty.xdf"
    path.write_text(
        "<XDFFORMAT><XDFHEADER><deftitle>x</deftitle></XDFHEADER></XDFFORMAT>",
        encoding="utf-8",
    )
    with pytest.raises(XdfError, match="no readable tables"):
        XdfFile.from_file(path)


# -- constants -------------------------------------------------------------


def test_constant_with_math_and_signed_little_endian(xdf: XdfFile,
                                                     device_image: bytearray):
    device_image[0x8000:0x8002] = (340).to_bytes(2, "little", signed=True)
    xdf.little_endian = True             # DEFAULTS lsbfirst=1 in a sibling file
    entry = xdf.render(bytes(device_image))["constants"][0]
    assert entry["title"] == "Rev limiter"
    assert entry["raw"] == 340
    assert entry["value"] == 8500        # 340 * 25
    assert entry["units"] == "RPM"
    assert entry["address"] == "0x8000"


def test_signed_values_respect_mmedtypeflags_not_defaults():
    # DEFAULTS signed=0 but the constant carries mmedtypeflags 0x01
    xdf = XdfFile.from_string(build_xdf(signed=0))
    const = xdf.constants[0]
    assert const.embedded.signed
    raw = (-2).to_bytes(2, "big", signed=True)
    assert const.raw(raw + b"\x00" * 8, 0, little_endian=False) == -2


# -- tables ----------------------------------------------------------------


def test_3d_table_embedded_axis_signed_be_with_strides(xdf: XdfFile,
                                                       device_image: bytearray):
    table = next(t for t in xdf.tables if t.title == "Ignition advance")
    assert table.embedded.rows == 2 and table.embedded.cols == 3
    assert table.embedded.major_stride_bits == 64
    assert table.embedded.span_bits == (1 * 64) + (2 * 16) + 16  # 112 bits

    render = xdf.render(bytes(device_image))
    entry = render["tables"][0]
    # order: tables are parsed in file order; find it by title
    entry = next(t for t in render["tables"] if t["title"] == "Ignition advance")
    assert entry["x"] == ["800", "1600", "2400"]     # 8,16,24 * 100
    assert entry["y"] == ["closed", "open"]
    assert entry["values"] == [
        [-10.0, 10.0, 20.0],        # -455, 455, 910 over 45.5
        [40.0, 0.0, 0.0],           # 1820/45.5 = 40; rest of row reads zeros
    ]
    assert entry["units"] == "Degrees"
    assert entry["rows"] == 2 and entry["cols"] == 3
    assert render["address_base"] == 0


def test_2d_table_static_labels_8bit(xdf: XdfFile, device_image: bytearray):
    render = xdf.render(bytes(device_image))
    entry = next(t for t in render["tables"] if t["title"] == "Speedo correction")
    assert entry["x"] == ["0"]              # no labels, no data: plain indexes
    assert entry["y"] == ["0", "1"]
    assert entry["values"] == [[30], [34]]


def test_rowcount_is_reconciled_with_the_y_axis():
    xdf = XdfFile.from_string(build_xdf().replace('mmedrowcount="2"', 'mmedrowcount="9"'))
    table = next(t for t in xdf.tables if t.title == "Ignition advance")
    assert table.embedded.rows == 2          # indexcount wins


def test_missing_colcount_comes_from_the_x_axis():
    xdf = XdfFile.from_string(
        build_xdf().replace('mmedrowcount="2" mmedcolcount="3"', 'mmedrowcount="2"')
    )
    table = next(t for t in xdf.tables if t.title == "Ignition advance")
    assert table.embedded.cols == 3


def test_per_cell_math_is_reported_unsupported_never_guessed():
    # a table with per-cell address-linked VARs
    xdf = XdfFile.from_string(build_xdf(engine_table=False).replace(
        "</XDFFORMAT>",
        """  <XDFTABLE uniqueid="0x5" flags="0x30">
    <title>Segment info</title>
    <XDFAXIS id="x" uniqueid="0x0"><indexcount>1</indexcount>
      <MATH equation="X"><VAR id="X" /></MATH></XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0"><indexcount>2</indexcount>
      <MATH equation="X"><VAR id="X" /></MATH></XDFAXIS>
    <XDFAXIS id="z">
      <EMBEDDEDDATA mmedaddress="0x504" mmedelementsizebits="16" mmedrowcount="2" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <MATH row="1" col="1" equation="X"><VAR id="X" type="address" address="0x504" sizeinbits="32" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
</XDFFORMAT>"""))
    assert not [t for t in xdf.tables if t.title == "Segment info"]
    assert xdf.unsupported[0]["title"] == "Segment info"
    assert "not supported" in xdf.unsupported[0]["reason"]
    # everything else still parses (Speedo + Lambda)
    assert sorted(t.title for t in xdf.tables) == \
        ["Lambda target", "Speedo correction"]


# -- linked legends ---------------------------------------------------------
#
# TunerPro writes ``<embedinfo type="3" linkobjid="0x7FDD" />`` on an axis
# that has no data of its own: its labels are another item's values. In this
# library that item is always a *legend* table holding the breakpoints, and
# resolving it is what turns a row header from "13" into "82" (°C).


def legend_definition(*, link: str = "0x4ce6", legend_rows: int = 4) -> str:
    """A legend table plus a table whose y axis is its four-row legend."""
    legend_labels = "".join(
        f'\n      <LABEL index="{i}" value="{i + 1}" />' for i in range(legend_rows)
    )
    return f"""
  <XDFTABLE uniqueid="0x4CE6" flags="0x30">
    <title>Legend EngineTemp</title>
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="16" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>1</indexcount>
      <LABEL index="0" value="0" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="16" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>{legend_rows}</indexcount>{legend_labels}
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z" uniqueid="0x0">
      <EMBEDDEDDATA mmedaddress="0x8600" mmedelementsizebits="16" mmedrowcount="{legend_rows}" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <decimalpl>1</decimalpl>
      <MATH equation="X-40"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
  <XDFTABLE uniqueid="0x2F84" flags="0x30">
    <title>Ignition engine temperature correction</title>
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="16" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <indexcount>1</indexcount>
      <LABEL index="0" value="0" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="16" mmedmajorstridebits="-32" mmedminorstridebits="0" />
      <units>&#176;C</units>
      <indexcount>4</indexcount>
      <embedinfo type="3" linkobjid="{link}" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z" uniqueid="0x0">
      <EMBEDDEDDATA mmedaddress="0x8700" mmedelementsizebits="16" mmedrowcount="4" mmedmajorstridebits="0" mmedminorstridebits="0" />
      <decimalpl>1</decimalpl>
      <MATH equation="X/10"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
"""


def linked_render_tables(**kwargs) -> tuple[XdfFile, bytearray, dict]:
    """The fixture plus known legend and table data, and its render payload."""
    xdf = XdfFile.from_string(
        build_xdf().replace("</XDFFORMAT>", legend_definition(**kwargs) + "</XDFFORMAT>")
    )
    legend = next(t for t in xdf.tables if t.uniqueid == "0x4CE6")
    table = next(t for t in xdf.tables if t.uniqueid == "0x2F84")
    image = bytearray(DEVICE_SIZE)
    for index, raw in enumerate((40, 60, 80, 100)[:legend.embedded.count]):
        legend.embedded.write_one(
            image, xdf.file_offset(legend.embedded.address), index, raw,
            little_endian=xdf.little_endian,
        )
    for index, raw in enumerate((100, 200, 300, 400)):
        table.embedded.write_one(
            image, xdf.file_offset(table.embedded.address), index, raw,
            little_endian=xdf.little_endian,
        )
    render = xdf.render(bytes(image))
    entry = next(t for t in render["tables"] if t["title"] == table.title)
    return xdf, image, entry


def test_a_linked_axis_takes_its_labels_from_the_legend_it_names():
    _, _, table = linked_render_tables()
    # 40, 60, 80, 100 through the legend's own "X-40", not 0..3
    assert table["y"] == ["0", "20", "40", "60"]
    assert table["y_units"] == "°C"
    assert table["axes"]["y"]["legend"] == {
        "id": "0x4CE6", "title": "Legend EngineTemp",
        "count": 4, "applied": 4, "reason": "",
    }
    # it is still a definition, not image data: nothing to edit or write
    assert table["axes"]["y"]["editable"] is False
    assert table["axes"]["y"]["address"] == ""
    assert table["axes"]["y"]["raw_values"] == []
    # and the cell values keep coming from the z data
    assert table["values"] == [[10.0], [20.0], [30.0], [40.0]]


def test_a_dangling_link_falls_back_to_indexes_and_says_so():
    _, _, table = linked_render_tables(link="0x9999")
    assert table["y"] == ["0", "1", "2", "3"]
    assert table["axes"]["y"]["legend"] == {
        "id": "0x9999", "title": "", "count": 0, "applied": 0,
        "reason": "no table in this definition has id 0x9999",
    }


def test_a_legend_shorter_than_its_axis_labels_the_part_it_defines():
    _, _, table = linked_render_tables(legend_rows=2)
    assert table["y"] == ["0", "20", "2", "3"]      # the tail keeps indexes
    legend = table["axes"]["y"]["legend"]
    assert legend["count"] == 2 and legend["applied"] == 2
    assert legend["reason"] == (
        "Legend EngineTemp defines 2 labels for a 4-entry axis"
    )


def test_an_axis_with_its_own_data_keeps_its_own_labels():
    # the definition also names a legend, but this axis stores its breakpoints
    # itself - those are what the map actually reads and edits
    xdf = XdfFile.from_string(build_xdf().replace(
        "</XDFFORMAT>",
        legend_definition().replace(
            '<EMBEDDEDDATA mmedelementsizebits="16" mmedmajorstridebits="-32" '
            'mmedminorstridebits="0" />\n      <units>&#176;C</units>',
            '<EMBEDDEDDATA mmedaddress="0x8800" mmedelementsizebits="16" '
            'mmedmajorstridebits="0" mmedminorstridebits="0" />\n'
            '      <units>&#176;C</units>',
        ) + "</XDFFORMAT>",
    ))
    image = bytearray(DEVICE_SIZE)
    image[0x8800:0x8808] = b"".join(
        value.to_bytes(2, "big") for value in (7, 8, 9, 10)
    )
    render = xdf.render(bytes(image))
    table = next(t for t in render["tables"]
                 if t["title"] == "Ignition engine temperature correction")
    assert table["y"] == ["7", "8", "9", "10"]
    assert table["axes"]["y"]["legend"] is None


def test_diff_names_rows_with_the_linked_legend():
    xdf, image, _ = linked_render_tables()
    modified = bytearray(image)
    modified[0x8702:0x8704] = (250).to_bytes(2, "big")     # row 1 -> 25.0
    diff = xdf.diff(bytes(image), bytes(modified))
    table = next(t for t in diff["tables"]
                 if t["title"] == "Ignition engine temperature correction")
    assert table["cells"][0]["row"] == 1
    assert table["cells"][0]["y"] == "20"                  # not "1"


def test_the_bundled_5am_definitions_resolve_their_engine_temp_legend():
    """The file the bug report names: `linkobjid="0x7FDD"` on the °C rows."""
    xdf = XdfFile.from_file(
        BUNDLED_XDF_DIR / "aprilia" / "5AM_Aprilia_GP850_V1.00.xdf"
    )
    legend = next(t for t in xdf.tables if t.uniqueid.upper() == "0X7FDD")
    assert legend.title == "4C E 68 Legend EngineTemp"
    image = bytearray(DEVICE_SIZE)
    raws = (40, 60, 80, 100, 120, 140, 160, 180,
            200, 220, 240, 250, 260, 270, 280, 290)
    for index, raw in enumerate(raws):
        legend.embedded.write_one(
            image, xdf.file_offset(legend.embedded.address), index, raw,
            little_endian=xdf.little_endian,
        )
    render = xdf.render(bytes(image))
    table = next(t for t in render["tables"]
                 if t["title"] == "49 4 A0 Ignition Engine Temp correction Idle_1")
    assert table["y"] == [str(raw - 40) for raw in raws]
    assert table["axes"]["y"]["legend"] == {
        "id": "0x7FDD", "title": "4C E 68 Legend EngineTemp",
        "count": 16, "applied": 16, "reason": "",
    }


def test_a_legend_that_is_shorter_than_the_axis_is_reported_not_padded():
    """7SM RSV4 1037 links a nine-value legend to 24-row tables. Only the nine
    labels it defines are used; inventing fifteen more would mislabel rows."""
    xdf = XdfFile.from_file(
        BUNDLED_XDF_DIR / "aprilia" / "7SM_RSV4_1037AH01_V1.03.xdf"
    )
    render = xdf.render(bytes(xdf.data_end() + 16))
    table = next(t for t in render["tables"] if t["title"] == "90 A AA Fuel Main Left 1")
    legend = table["axes"]["y"]["legend"]
    assert legend["id"] == "0x2056" and legend["count"] == 9
    assert legend["applied"] == 9 and table["rows"] == 24
    assert legend["reason"] == (
        "92 F DE RPM 9B Legend defines 9 labels for a 24-entry axis"
    )
    assert table["y"][9:] == [str(index) for index in range(9, 24)]


# -- addressing ------------------------------------------------------------


def test_baseoffset_add_mode():
    xdf = XdfFile.from_string(build_xdf(base_offset='offset="0x100" subtract="0"'))
    assert xdf.file_offset(0x8000) == 0x8100
    assert xdf.data_end() > 0x8400 + 0x100


def test_baseoffset_subtract_mode():
    xdf = XdfFile.from_string(build_xdf(base_offset='offset="0x400000" subtract="1"'))
    assert xdf.file_offset(0x408000) == 0x8000


def test_region_dump_gets_base_0x4000(xdf: XdfFile, device_image: bytearray):
    full = xdf.render(bytes(device_image))
    region = bytes(device_image)[0x4000:]
    assert len(region) == REGION_SIZE

    render = xdf.render(region)
    assert render["address_base"] == 0x4000
    by_title = {t["title"]: t for t in render["tables"]}
    full_by_title = {t["title"]: t for t in full["tables"]}
    assert by_title["Ignition advance"]["values"] == \
        full_by_title["Ignition advance"]["values"]
    assert by_title["Lambda target"]["values"] == \
        full_by_title["Lambda target"]["values"]
    assert by_title["Lambda target"]["values"] == [[round(128 / 255, 3), round(200 / 255, 3)]]
    assert render["constants"][0]["value"] == 8500


def test_full_device_dump_gets_base_0(xdf: XdfFile, device_image: bytearray):
    assert xdf.render(bytes(device_image))["address_base"] == 0


def test_items_outside_the_image_are_reported_not_swallowed(
        xdf: XdfFile, device_image: bytearray):
    # force the wrong base: everything lands 0x4000 too low, tables escape
    # the far end of a region-size image
    render = xdf.render(bytes(device_image)[0x4000:], address_base=0)
    assert [e["title"] for e in render["errors"]] == ["Lambda target"]
    assert "outside" in render["errors"][0]["reason"]
    # the low-flash tables still rendered; only the escaped one is missing
    assert sorted(t["title"] for t in render["tables"]) == \
        ["Ignition advance", "Speedo correction"]


def test_render_accepts_firmware_images(xdf: XdfFile, device_image: bytearray):
    image = FirmwareImage(data=bytes(device_image), region="flash")
    render = xdf.render(image)
    assert render["image_size"] == DEVICE_SIZE
    assert render["constants"][0]["value"] == 8500


# -- diff ------------------------------------------------------------------


def test_diff_names_changed_cells_and_constants(xdf: XdfFile,
                                                device_image: bytearray):
    modified = bytearray(device_image)
    modified[0x8202:0x8204] = (910).to_bytes(2, "big", signed=True)   # 10 -> 20 deg
    modified[0x8401] = 58                                            # speedo 34 -> 58
    modified[0x8000:0x8002] = (360).to_bytes(2, "big", signed=True)     # 8500 -> 9000

    d = xdf.diff(bytes(device_image), bytes(modified))
    assert d["identical"] is False
    spark = next(t for t in d["tables"] if t["title"] == "Ignition advance")
    assert spark["changed_cells"] == 1
    cell = spark["cells"][0]
    assert cell == {
        "row": 0, "col": 1, "x": "1600", "y": "closed",
        "before": 10.0, "after": 20.0,
    }
    speedo = next(t for t in d["tables"] if t["title"] == "Speedo correction")
    assert speedo["changed_cells"] == 1
    assert d["constants"] == [
        {"title": "Rev limiter", "units": "RPM", "before": 8500, "after": 9000}
    ]


def test_diff_of_identical_images(xdf: XdfFile, device_image: bytearray):
    d = xdf.diff(bytes(device_image), bytes(device_image))
    assert d["identical"] is True
    assert d["tables"] == [] and d["constants"] == []


def test_diff_rejects_mismatched_sizes(xdf: XdfFile, device_image: bytearray):
    with pytest.raises(XdfError, match="differ in size"):
        xdf.diff(bytes(device_image), bytes(device_image)[:-1])


# -- math safety -------------------------------------------------------------


@pytest.mark.parametrize("equation", [
    "X + Y", "X**2", "__import__('os')", "X and X", "len(X)",
    "", "X;X", "lambda: X", "X.__class__",
])
def test_math_rejects_anything_beyond_plain_arithmetic(equation):
    with pytest.raises(XdfError):
        eval_math(equation, 100)


@pytest.mark.parametrize("equation,x,expected", [
    ("X", 5, 5.0),
    ("X*25", 340, 8500.0),
    ("X/45.5", 455, 10.0),
    ("(X-128)*0.05859372", 228, 5.859372),
    ("x * 2", 3, 6.0),            # lowercase variable
    ("X/4096", 8192, 2.0),
])
def test_math_handles_the_tunerpro_vocabulary(equation, x, expected):
    assert eval_math(equation, x) == pytest.approx(expected)


# -- loader ---------------------------------------------------------------


def test_load_xdfs_reads_the_directory_and_skips_broken_files(tmp_path,
                                                              monkeypatch):
    (tmp_path / "good1.xdf").write_text(build_xdf(), encoding="utf-8")
    (tmp_path / "good2.XDF").write_text(build_xdf(), encoding="utf-8")
    (tmp_path / "broken.xdf").write_text("<not-an-xdf/>", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("ignore me", encoding="utf-8")

    loaded = load_xdfs(tmp_path)
    assert len(loaded) == 2
    assert all(isinstance(x, XdfFile) for x in loaded)
    # sorted order, uppercase suffix included
    assert Path(loaded[0].path).name in ("good1.xdf", "good2.XDF")

    assert load_xdfs(tmp_path / "does-not-exist") == []
    assert XDF_DIR.name == "xdfs"


def test_load_xdfs_recursive_walks_brand_subfolders(tmp_path):
    (tmp_path / "moto_guzzi").mkdir()
    (tmp_path / "ducati").mkdir()
    (tmp_path / "moto_guzzi" / "a.xdf").write_text(build_xdf(), encoding="utf-8")
    (tmp_path / "ducati" / "b.xdf").write_text(build_xdf(), encoding="utf-8")
    (tmp_path / "top.xdf").write_text(build_xdf(), encoding="utf-8")

    assert len(load_xdfs(tmp_path)) == 1        # flat glob only sees "top.xdf"
    assert len(load_xdfs(tmp_path, recursive=True)) == 3


def test_bundled_xdf_library_all_parse_and_are_discoverable():
    """Whatever ships under guzzionboard/xdfs/ must actually be valid XDFs -
    a quality gate for anything added via scripts/import_xdfs.py."""
    bundled = load_bundled_xdfs()
    assert BUNDLED_XDF_DIR.is_dir()
    on_disk = list(BUNDLED_XDF_DIR.rglob("*.xdf"))
    assert len(bundled) == len(on_disk), "a vendored file failed to parse"
    assert all(x.tables or x.constants for x in bundled)


def _with_title(xdf_text: str, title: str) -> str:
    return xdf_text.replace(f"<deftitle>{XDF_TITLE}</deftitle>",
                             f"<deftitle>{title}</deftitle>")


def test_available_xdfs_merges_bundled_and_user_override(tmp_path):
    user_only = tmp_path / "Only_In_User.xdf"
    user_only.write_text(_with_title(build_xdf(), "User Override Title"),
                          encoding="utf-8")

    merged = available_xdfs(tmp_path)
    titles = [x.title for x in merged]
    assert "User Override Title" in titles
    # bundled files are still present alongside the user addition
    assert len(merged) == len(load_bundled_xdfs()) + 1


def test_available_xdfs_user_file_overrides_the_same_filename(tmp_path):
    """Filenames, not titles, decide what overrides what.

    XDF titles collide - "15M Marelli" is on several unrelated files, and
    some have no title at all - so a title match must not make one
    definition disappear behind another.
    """
    bundled = load_bundled_xdfs()
    assert bundled, "need at least one bundled xdf for this test to mean anything"
    shadowed = Path(bundled[0].path).name

    shadowing = tmp_path / shadowed
    shadowing.write_text(_with_title(build_xdf(), "My Corrected Copy"), encoding="utf-8")

    merged = available_xdfs(tmp_path)
    matches = [x for x in merged if Path(x.path).name == shadowed]
    assert len(matches) == 1
    assert matches[0].title == "My Corrected Copy"
    assert len(merged) == len(bundled)


def test_a_colliding_title_does_not_hide_a_bundled_definition(tmp_path):
    bundled = load_bundled_xdfs()
    shadow_title = next(x.title for x in bundled if x.title)

    (tmp_path / "shadow.xdf").write_text(
        _with_title(build_xdf(), shadow_title), encoding="utf-8"
    )
    merged = available_xdfs(tmp_path)
    assert len(merged) == len(bundled) + 1
    assert len([x for x in merged if x.title == shadow_title]) >= 2


def test_describe_summarises_the_file(xdf: XdfFile):
    d = xdf.describe()
    assert d["tables"] == 3 and d["constants"] == 1
    assert d["unsupported"] == 0
    assert d["region_size"] == DEVICE_SIZE
    assert "Fuel" in d["categories"]


# -- HTTP API ---------------------------------------------------------------


class TestMapsApi:
    """The Api methods behind GET /api/maps and its two POST neighbours."""

    @pytest.fixture
    def api(self, tmp_path, monkeypatch, xdf):
        from guzzionboard import server
        from guzzionboard.workstation import Workstation

        xdf.path = str(tmp_path / "5am.xdf")     # pretend it came from the dir
        monkeypatch.setattr(server, "available_xdfs", lambda directory=None: [xdf])
        return server.Api(Workstation(session_dir=tmp_path / "sessions"))

    def test_lists_available_xdfs(self, api):
        status, payload = api.get_maps({})
        assert status == 200
        assert payload["directory"].endswith("xdfs")
        entry = next(x for x in payload["xdfs"] if x["title"] == XDF_TITLE)
        assert entry["tables"] == 3 and entry["constants"] == 1

    def test_render_by_title(self, api, tmp_path, device_image):
        image = tmp_path / "5am-flash-read.bin"
        image.write_bytes(bytes(device_image))
        status, payload = api.post_maps_render(
            {"path": str(image), "xdf": XDF_TITLE}
        )
        assert status == 200
        assert payload["address_base"] == 0
        assert len(payload["tables"]) == 3
        assert payload["constants"][0]["value"] == 8500
        assert payload["image"]["path"] == str(image)

    def test_render_by_xdf_path(self, api, tmp_path, device_image):
        xdf_file = tmp_path / "custom.xdf"
        xdf_file.write_text(build_xdf(), encoding="utf-8")
        image = tmp_path / "a.bin"
        image.write_bytes(bytes(device_image))
        status, payload = api.post_maps_render(
            {"path": str(image), "xdf": str(xdf_file)}
        )
        assert status == 200
        assert payload["tables"]

    def test_render_region_read_auto_base(self, api, tmp_path, device_image):
        image = tmp_path / "region.bin"
        image.write_bytes(bytes(device_image)[0x4000:])
        status, payload = api.post_maps_render(
            {"path": str(image), "xdf": XDF_TITLE}
        )
        assert status == 200
        assert payload["address_base"] == 0x4000

    def test_render_rejects_bad_requests(self, api, tmp_path):
        assert api.post_maps_render({})[0] == 400
        assert api.post_maps_render({"path": "/nope"})[0] == 400
        status, payload = api.post_maps_render({"path": "/nope", "xdf": XDF_TITLE})
        assert status == 400 and "error" in payload
        status, payload = api.post_maps_render(
            {"path": "/nope", "xdf": XDF_TITLE, "address_base": "wat"}
        )
        assert status == 400

    def test_diff_between_two_images(self, api, tmp_path, device_image):
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        modified = bytearray(device_image)
        modified[0x8401] = 58
        a.write_bytes(bytes(device_image))
        b.write_bytes(bytes(modified))
        status, payload = api.post_maps_diff(
            {"path_a": str(a), "path_b": str(b), "xdf": XDF_TITLE}
        )
        assert status == 200
        assert payload["identical"] is False
        assert payload["tables"][0]["title"] == "Speedo correction"

    def test_diff_of_identical_images(self, api, tmp_path, device_image):
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        a.write_bytes(bytes(device_image))
        b.write_bytes(bytes(device_image))
        status, payload = api.post_maps_diff(
            {"path_a": str(a), "path_b": str(b), "xdf": XDF_TITLE}
        )
        assert status == 200 and payload["identical"] is True

    def test_diff_rejects_missing_paths(self, api):
        assert api.post_maps_diff({"xdf": XDF_TITLE})[0] == 400
        assert api.post_maps_diff({"path_a": "/a"})[0] == 400
        assert api.post_maps_diff({"path_a": "/a", "path_b": "/b"})[0] == 400

