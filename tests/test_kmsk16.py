"""KMSK16 decoder guards: framing, the identifier table, and the honesty marks.

The arithmetic runs in two places — `guzzionboard/protocol/kmsk16.py` and its
browser twin `web/kmsk16.js` — and `tests/browser/kmsk16.spec.mjs` drives the
browser one the way an operator does. What is checked here is the part neither
of those can see on its own:

* the frames are real KWP2000 frames, built with the repository's own encoder,
  so a checksum change breaks this rather than a motorcycle;
* every entry that publishes a number says whether that number is stated by the
  source or inferred, and every entry whose source disagrees with itself carries
  the conflict instead of a resolution;
* the JavaScript table and the Python table are the same table.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from guzzionboard.protocol import kmsk16, kwp2000

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


# --------------------------------------------------------------------------
# Frame helpers — real frames, not hex typed by hand
# --------------------------------------------------------------------------


def response(payload: list[int]) -> str:
    """A captured ECU answer: target 0xF1, source 0x12 (the ECU)."""
    return kwp2000.encode_request(payload, target=0xF1, source=kmsk16.ECU_ADDRESS).hex(" ").upper()


def request(payload: list[int]) -> str:
    """A captured tester request: target 0x12, source 0xF1."""
    return kwp2000.encode_request(payload, target=kmsk16.ECU_ADDRESS, source=0xF1).hex(" ").upper()


def did(identifier: int, *value: int) -> str:
    return response([0x62, identifier >> 8, identifier & 0xFF, *value])


# -- framing ---------------------------------------------------------------


def test_the_addresses_and_line_speed_are_the_published_ones():
    assert kmsk16.ECU_ADDRESS == 0x12
    assert kmsk16.TESTER_ADDRESS == 0xF1
    assert kmsk16.BAUD_RATE == 10_400
    assert kmsk16.FAST_INIT_HALF_PERIOD_US == 25_000


def test_the_framing_is_the_repository_kwp2000_frame():
    """The source's `fmt = 0x80 + len + 1` is this repository's `0x80 | len`.

    Both count the service identifier inside the length, so a KMSK16 frame needs
    no separate codec — only the addresses differ from the IAW profiles.
    """
    raw = kwp2000.encode_request([0x22, 0x01, 0x00], target=0x12, source=0xF1)
    assert raw[0] == 0x80 | 3           # three payload bytes: 22 01 00
    assert raw[1:3] == bytes((0x12, 0xF1))
    assert raw[-1] == sum(raw[:-1]) & 0xFF
    frame = kwp2000.decode_frame(raw)
    assert frame.payload == bytes((0x22, 0x01, 0x00))


def test_a_checksum_from_the_published_encoder_is_accepted():
    """`80 F1 12 …` with a correct sum decodes; one byte off is refused."""
    good = did(0x0100, 0x0B, 0xB8)
    decoded = kmsk16.decode_line(good)
    assert decoded.ok
    assert decoded.identifier == 0x0100
    assert decoded.raw_value == 0x0BB8

    broken = good.rsplit(" ", 1)[0] + " AF"
    refused = kmsk16.decode_line(broken)
    assert not refused.ok
    assert "checksum" in refused.reason.lower()


@pytest.mark.parametrize(
    "line, reason",
    [
        ("", "no hex bytes"),
        ("80F112", "at least 5 bytes"),
        ("85 F1 12 62 01 00 0B B8 AE ZZ", "not a hex byte"),
        ("85 1 12 62 01 00 0B B8 AE", None),   # single digits are still bytes
        ("can0  0C0   [8]  01 02 03 04 05 06 07 08", None),
    ],
)
def test_only_hex_frames_are_read_as_frames(line, reason):
    result = kmsk16.decode_line(line)
    if reason is None:
        assert not result.ok        # a CAN line is not silently a KMSK16 frame
    else:
        assert not result.ok
        assert reason in result.reason


def test_a_long_run_without_separators_is_still_a_frame():
    good = did(0x0100, 0x0B, 0xB8)
    assert kmsk16.decode_line(good.replace(" ", "")).ok


# -- the identifier table --------------------------------------------------


def test_the_table_covers_the_identifiers_the_job_description_names():
    assert len(kmsk16.DATA_IDS) == 51
    for identifier in (0x0000, 0x0009, 0x0100, 0x0107, 0x0110, 0x0120, 0x0130,
                       0x0140, 0x0170, 0x0174, 0x0185, 0x0500, 0x0501,
                       0x0502, 0x0509, 0x0510, 0x2503):
        assert identifier in kmsk16.DATA_IDS, hex(identifier)


def test_every_published_number_says_where_it_came_from():
    for identifier, entry in kmsk16.DATA_IDS.items():
        if entry.scale is not None:
            assert entry.basis, f"0x{identifier:04X} has a scale and no basis"
            assert entry.inferred in (True, False)
        if entry.enum is not None:
            assert entry.scale is None, f"0x{identifier:04X} is an enumeration, not a number"
        if entry.formula:
            assert entry.note or entry.scale is not None, (
                f"0x{identifier:04X} quotes a formula but says nothing about applying it")


def test_the_two_read_only_checksum_routines_are_named():
    """`$31 0x0102/0x0104` ask the ECU about its own coding checksums."""
    assert "CheckCodingChecksum" in kmsk16.ROUTINES[0x0102]
    assert "CheckCodingChecksum" in kmsk16.ROUTINES[0x0104]
    assert "read-only" in kmsk16.ROUTINES[0x0102]
    # The erase routine may be named, but nothing in this project implements it.
    assert "not implemented" in kmsk16.ROUTINES[0x9000]


def test_the_security_key_is_not_in_the_project():
    """The source's 16-bit key was brute-forced and is supplier-specific."""
    for path in (ROOT / "guzzionboard/protocol/kmsk16.py", WEB / "kmsk16.js"):
        text = path.read_text(encoding="utf-8")
        assert "1EC3" not in text.upper(), path
        assert "SECRET_KEY" not in text, path


# -- decoding --------------------------------------------------------------


def test_engine_speed_uses_the_declared_range_and_says_so():
    decoded = kmsk16.decode_line(did(0x0100, 0x0B, 0xB8))
    text = "\n".join(decoded.lines)
    assert decoded.raw_value == 3000
    assert decoded.value == 750                 # 3000 × 0.25 rpm
    assert "inferred" in text
    assert "STATUS_ENGINE_SPEED" in text


def test_an_enumeration_identifier_reports_its_state():
    engaged = kmsk16.decode_line(did(0x0040, 0x00, 0xFF))
    assert engaged.state == "Gear engaged"
    neutral = kmsk16.decode_line(did(0x0040, 0x00, 0x00))
    assert neutral.state == "Neutral"
    unknown = kmsk16.decode_line(did(0x0040, 0x12, 0x34))
    assert unknown.state is None
    assert any("not one of the declared values" in line for line in unknown.lines)


def test_battery_voltage_reports_the_source_conflict_rather_than_a_guessed_range():
    decoded = kmsk16.decode_line(did(0x0006, 0x00, 0x75))
    text = "\n".join(decoded.lines)
    assert decoded.value == pytest.approx(11.7)
    assert "Source conflict" in text
    assert "0–5 V" in text


def test_the_over_rev_counters_keep_both_ranges():
    decoded = kmsk16.decode_line(did(0x0502, 0x05, 0xD1))
    text = "\n".join(decoded.lines)
    assert "Source conflict" in text
    assert decoded.value is None                # nothing is derived from a contradiction
    assert "0.1 s" in text and "3 min" in text


def test_the_calculated_load_formula_is_quoted_not_applied():
    decoded = kmsk16.decode_line(did(0x0107, 0x00, 0x50))
    text = "\n".join(decoded.lines)
    assert "PM1M" in text and "10103" in text
    assert decoded.value is None


def test_ascii_identifiers_are_shown_as_text():
    reference = b"HU0010xV1340"
    decoded = kmsk16.decode_line(
        response([0x62, 0x25, 0x03, *reference]))
    text = "\n".join(decoded.lines)
    assert "HU0010xV1340" in text
    assert "12 bytes of ASCII" in text


def test_a_negative_response_is_translated():
    decoded = kmsk16.decode_line(response([0x7F, 0x22, 0x31]))
    assert decoded.ok
    assert "Request out of range" in decoded.lines[0]
    assert "ReadDataByCommonIdentifier" in decoded.lines[0]


def test_a_request_names_what_it_asks_for():
    decoded = kmsk16.decode_line(request([0x22, 0x01, 0x00]))
    assert decoded.headline.startswith("request")
    assert any("Engine speed" in line for line in decoded.lines)


def test_a_routine_response_names_the_routine():
    decoded = kmsk16.decode_line(response([0x71, 0x01, 0x04, 0x00, 0x00]))
    assert "CheckCodingChecksum" in decoded.headline
    assert any("Result bytes" in line for line in decoded.lines)


def test_an_unknown_identifier_is_named_not_guessed():
    decoded = kmsk16.decode_line(did(0x0999, 0x00, 0x01))
    assert decoded.ok
    assert "not one of the" in decoded.lines[0]


def test_an_unknown_service_is_reported():
    decoded = kmsk16.decode_line(response([0x98, 0x01]))
    assert decoded.ok
    assert any("not one the KMSK16 job description names" in line for line in decoded.lines)


# -- several frames at once ------------------------------------------------


def test_the_second_throttle_percentage_needs_three_frames_and_says_it_is_rewritten():
    paste = "\n".join([
        did(0x0170, 0x02, 0x00),
        did(0x0172, 0x00, 0xE3),
        did(0x0173, 0x03, 0xA1),
    ])
    result = kmsk16.decode_capture(paste)
    assert result.accepted == 3
    derived = "\n".join(result.derived)
    assert "40.6 %" in derived                 # (512 − 227) / (929 − 227) × 100
    assert "rewritten" in derived


def test_a_partial_paste_says_which_identifier_is_missing():
    result = kmsk16.decode_capture(did(0x0170, 0x02, 0x00))
    assert "missing 0x0172, 0x0173" in result.derived[0]


def test_an_empty_reference_span_derives_nothing():
    paste = "\n".join([did(0x0170, 0x02, 0x00), did(0x0172, 0x03, 0xA1), did(0x0173, 0x00, 0xE3)])
    result = kmsk16.decode_capture(paste)
    assert "span is empty" in result.derived[0]


def test_a_bad_frame_does_not_stop_the_others():
    paste = "\n".join([did(0x0100, 0x0B, 0xB8), "85 F1 12 62 01 00 0B B8 ZZ"])
    result = kmsk16.decode_capture(paste)
    assert (result.accepted, result.rejected) == (1, 1)


def test_a_paste_is_bounded():
    with pytest.raises(kmsk16.DecodeError):
        kmsk16.decode_capture("\n".join([did(0x0100, 0, 1)] * 101))


# -- the browser twin ------------------------------------------------------


@pytest.fixture(scope="module")
def js_table() -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = (
        "const fs=require('fs');global.window={};"
        f"eval(fs.readFileSync({json.dumps(str(WEB / 'kmsk16.js'))},'utf8'));"
        "process.stdout.write(JSON.stringify(window.gobKmsk16.dataIds));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def test_the_browser_table_is_the_python_table(js_table):
    assert len(js_table) == len(kmsk16.DATA_IDS)
    js = {entry["id"]: entry for entry in js_table}
    assert set(js) == set(kmsk16.DATA_IDS)
    for identifier, entry in kmsk16.DATA_IDS.items():
        other = js[identifier]
        assert other["name"] == entry.name, hex(identifier)
        assert other["job"] == entry.job, hex(identifier)
        assert other.get("unit") == (entry.unit or None), hex(identifier)
        assert other.get("low") == (entry.low if entry.low is not None else None), hex(identifier)
        assert other.get("high") == (entry.high if entry.high is not None else None), hex(identifier)
        if entry.scale is None:
            assert "scale" not in other, hex(identifier)
        else:
            assert other["scale"] == pytest.approx(entry.scale), hex(identifier)
            assert other.get("bias", 0) == pytest.approx(entry.bias), hex(identifier)
            assert other.get("inferred") is True, hex(identifier)
        assert other.get("formula") == (entry.formula or None), hex(identifier)
        assert other.get("conflict") == (entry.conflict or None), hex(identifier)
        if entry.enum:
            assert other["enum"] == {str(key): value for key, value in entry.enum.items()}, hex(identifier)


def test_the_two_decoders_agree_on_a_frame():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    frame = did(0x0107, 0x00, 0x50)
    script = (
        "const fs=require('fs');global.window={};"
        f"eval(fs.readFileSync({json.dumps(str(WEB / 'kmsk16.js'))},'utf8'));"
        f"const d=window.gobKmsk16.decodeLine({json.dumps(frame)});"
        "process.stdout.write(JSON.stringify({headline:d.headline,lines:d.lines,id:d.identifier}));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    browser = json.loads(out.stdout)
    python = kmsk16.decode_line(frame)
    assert browser["headline"] == python.headline
    assert browser["id"] == python.identifier
    assert browser["lines"] == list(python.lines)


# -- the panels ------------------------------------------------------------


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("prefix, brand", [("ktm", "ktm"), ("husqvarna", "husqvarna")])
def test_each_brand_gets_a_panel_wired_to_the_shared_decoder(index_html, prefix, brand):
    panel = re.search(r'<article[^>]*id="' + prefix + r'Kmsk16"[^>]*>(.*?)</article>',
                      index_html, re.S)
    assert panel, prefix
    assert f'data-tool-brand="{brand}"' in panel.group(0)
    for element in (f"{prefix}Kmsk16Frames", f"{prefix}Kmsk16Decode",
                    f"{prefix}Kmsk16Clear", f"{prefix}Kmsk16Meta",
                    f"{prefix}Kmsk16Out", f"{prefix}Kmsk16Ref"):
        assert f'id="{element}"' in panel.group(1), element


def test_the_panel_script_is_loaded_once_after_the_shared_brand_layer(index_html):
    assert index_html.count('<script src="kmsk16.js"></script>') == 1
    assert index_html.index('brand-tools.js') < index_html.index('kmsk16.js')


def test_the_panel_copy_keeps_the_limits_visible(index_html):
    ktm = re.search(r'id="ktmKmsk16"[^>]*>(.*?)</article>', index_html, re.S).group(1)
    assert "no licence file" in ktm
    assert "not a fitment claim" in ktm
    assert "Nothing is transmitted" in ktm


def test_the_help_article_covers_the_panel_and_the_protocol():
    help_js = (WEB / "help-content.js").read_text(encoding="utf-8")
    assert "id: 'ktm-kmsk16-decoder'" in help_js
    assert "id: 'husqvarna-kmsk16-decoder'" in help_js
    assert "id: 'kmsk16'" in help_js
    assert "CheckCodingChecksum" in help_js
    assert "SecurityAccess" in help_js


def test_the_evidence_document_is_the_one_this_code_cites():
    doc = (ROOT / "docs/KMSK16_KLINE.md").read_text(encoding="utf-8")
    assert "43104d2" in doc
    assert "no licence" in doc.lower()
    assert "10,400" in doc
    assert "0x0100" in doc
