"""CAN capture analysis: the tool that turns a sniffed log into the id pair.

The CAN-era Guzzi ECUs speak ISO-TP, and the one unknown is which
request/response pair they sit on. The analyzer reads candump, SavvyCAN CSV
and CRTD captures and finds the pair that behaves like diagnostics - flow
control answering a first frame is the strongest evidence, service ids the
confirmation. A pair nobody can prove is not reported, per project policy.
"""
from __future__ import annotations

import pytest

from guzzionboard.canlog import (
    CanFrame,
    CanLogError,
    analyze_capture_text,
    analyze_frames,
    parse_capture,
    parse_capture_file,
)


def candump_session(
    tx: str = "7E0",
    rx: str = "7E8",
    *,
    noise: bool = True,
    tester_present: int = 6,
) -> str:
    """A realistic sniffed session: session start, a long exchange with flow
    control both ways, periodic tester present, and unrelated bus traffic."""
    lines: list[str] = []
    t = 100.0

    def f(ts: float, ident: str, data: bytes) -> None:
        lines.append(f"({ts:.6f}) can0 {ident}#{data.hex().upper()}")

    f(t, tx, bytes([0x02, 0x10, 0x03]) + b"\xAA" * 5)          # start session
    f(t + 0.004, rx, bytes([0x06, 0x50, 0x03, 0x00, 0x32, 0x01, 0xF4]) + b"\xAA")
    f(t + 0.500, tx, bytes([0x10, 0x08, 0x1A, 0x80]) + b"\xAA" * 4)  # FF
    f(t + 0.505, rx, bytes([0x30, 0x00, 0x07]) + b"\xAA" * 5)        # FC
    f(t + 0.520, rx, bytes([0x10, 0x14, 0x5A, 0x80, 0x43, 0x4D, 0x30, 0x30]))
    f(t + 0.525, tx, bytes([0x30, 0x00, 0x0A]) + b"\xAA" * 5)        # FC back
    for i in range(3):                                                # CFs
        f(t + 0.527 + i * 0.006, rx, bytes([0x20 + i]) + b"0" * 7)
    for i in range(tester_present):
        f(t + 1.0 + i * 2.0, tx, bytes([0x02, 0x3E, 0x00]) + b"\xAA" * 5)
        f(t + 1.004 + i * 2.0, rx, bytes([0x02, 0x7E, 0x00]) + b"\xAA" * 5)
    if noise:                       # starts with 0x11 - looks like a first frame
        for i in range(30):
            f(t + i * 0.1, "123",
              bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]))
    return "\n".join(lines)


# -- parsing ---------------------------------------------------------------


def test_candump_compact_and_verbose_layouts():
    compact = "(1.000000) can0 7E0#023E00AAAAAAAAAA"
    verbose = "(1.004000)  can0  7E8   [8]  02 7E 00 AA AA AA AA AA"
    frames, fmt, _ = parse_capture(f"{compact}\n{verbose}\ncan0 123#1122334455667788")
    assert fmt == "candump" and len(frames) == 3
    assert frames[0].id == 0x7E0 and frames[0].data == bytes.fromhex("023e00aaaaaaaaaa")
    assert frames[1].id == 0x7E8
    assert frames[2].timestamp == 0.0          # no clock in that line


def test_candump_extended_ids_and_timestamp_formats():
    text = "\n".join([
        "(1700000000.123456) can0 18DA10F1#021003AAAAAAAAAA",
        "(0:00:02.500000) can0 18DAF110#06500300003201F4AA",
    ])
    frames, _, _ = parse_capture(text)
    assert frames[0].extended and frames[0].id == 0x18DA10F1
    assert frames[1].timestamp == 2.5


def test_savvycan_csv_v2_with_dir_column():
    text = (
        "Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n"
        "1635520000000,7E0,0,Rx,0,8,02,10,03,AA,AA,AA,AA,AA\n"
        "1635520004000,7E8,0,Rx,0,8,06,50,03,00,32,01,F4,AA\n"
    )
    frames, fmt, _ = parse_capture(text)
    assert fmt == "savvycan-csv"
    assert frames[0].id == 0x7E0 and frames[0].direction == "Rx"
    assert frames[1].data[:3] == bytes([0x06, 0x50, 0x03])


def test_savvycan_csv_legacy_header_without_dir():
    text = (
        "Time Stamp,ID,Extended,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n"
        "1000,7E0,0,0,3,02,3E,00,00,00,00,00,00\n"
    )
    frames, fmt, _ = parse_capture(text)
    assert fmt == "savvycan-csv" and frames[0].data == bytes([0x02, 0x3E, 0x00])


def test_crtd_lines():
    text = "\n".join([
        "1320745424.002 R11 7E0 02 10 03 AA AA AA AA AA",
        "1320745424.006 R11 7E8 06 50 03 00 32 01 F4 AA",
    ])
    frames, fmt, _ = parse_capture(text)
    assert fmt == "crtd"
    assert frames[0].direction == "Rx" and not frames[0].extended


def test_garbage_and_comments_are_skipped_or_rejected(tmp_path):
    text = "# a comment\n\n(1.0) can0 7E0#023E00AAAAAAAAAA\nthis is not a frame\n"
    frames, _, warnings = parse_capture(text)
    assert len(frames) == 1 and any("skipped" in w for w in warnings)

    with pytest.raises(CanLogError, match="no frames"):
        parse_capture("just some words\nnothing frame-like")
    with pytest.raises(CanLogError, match="empty"):
        parse_capture("   \n")

    bad = tmp_path / "nope.log"
    with pytest.raises(CanLogError, match="cannot read"):
        parse_capture_file(bad)


# -- analysis --------------------------------------------------------------


def test_finds_the_standard_pair_through_the_noise():
    result = analyze_capture_text(candump_session())
    assert result["diagnostic_traffic_found"] is True
    assert len(result["pairs"]) == 1           # junk pairs are not reported
    top = result["pairs"][0]

    assert top["request_id"] == "0x7E0"
    assert top["response_id"] == "0x7E8"
    assert top["confidence"] == "strong"
    assert "reference pair" in top["matches"]  # recognition label, not a bike default
    assert top["tester_present_interval_s"] == 2.0
    assert top["padding_byte"] == "0xAA"
    assert "0x3E tester present" in top["request_sids"]
    assert "0x10 start diagnostic session" in top["request_sids"]
    assert top["evidence"]["multi_frame_to_ecu"] >= 1
    assert top["evidence"]["multi_frame_from_ecu"] >= 1
    # session 2 + exchange 7 (2 FF, 2 FC, 3 CF) + tester present 12 + noise 30
    assert result["frames"] == 51


def test_29_bit_pair_is_recognised_as_extended():
    result = analyze_capture_text(
        candump_session(tx="18DA10F1", rx="18DAF110")
    )
    top = result["pairs"][0]
    assert top["request_id"] == "0x18DA10F1"
    assert top["extended"] is True
    assert "29-bit" in top["matches"]


def test_an_oddball_pair_is_reported_with_no_match_note():
    result = analyze_capture_text(candump_session(tx="756", rx="757"))
    top = result["pairs"][0]
    assert (top["request_id"], top["response_id"]) == ("0x756", "0x757")
    assert top["matches"] is None               # neither standard pair


def test_noise_only_capture_is_honest_about_finding_nothing():
    noise = "\n".join(
        f"({100 + i * 0.1:.6f}) can0 123#1122334455667788" for i in range(20)
    )
    result = analyze_capture_text(noise)
    assert result["diagnostic_traffic_found"] is False
    assert result["pairs"] == []
    assert any("No ISO-TP diagnostic traffic" in n for n in result["notes"])


def test_unanswered_first_frames_are_not_evidence():
    """Bus chatter that happens to start with 0x1X is not a multi-frame
    exchange: a first frame nobody answers with flow control is noise."""
    chatter = "\n".join(
        f"({100 + i * 0.05:.6f}) can0 200#{bytes([0x11, i, 3, 4, 5, 6, 7, 8]).hex()}"
        for i in range(10)
    ) + "\n(101.0) can0 7E0#023E00AAAAAAAAAA"
    result = analyze_capture_text(chatter)
    assert result["diagnostic_traffic_found"] is False


def test_negative_responses_mark_the_ecu_side(tmp_path):
    text = "\n".join([
        "(1.000) can0 7E0#0227 01AAAAAAAA".replace(" ", ""),
        "(1.004) can0 7E8#037F27 11AAAAAAAA".replace(" ", ""),
        "(3.000) can0 7E0#023E00AAAAAAAAAA",
        "(3.004) can0 7E8#027E00AAAAAAAAAA",
    ])
    result = analyze_capture_text(text)
    assert result["pairs"], "a negative response is still evidence"
    assert result["pairs"][0]["evidence"]["response_frames"] >= 1


def test_frame_helpers():
    frame = CanFrame(1.0, 0x7E0, False, bytes([0x02, 0x3E, 0x00]))
    assert frame.pci == "sf" and frame.payload_sid() == 0x3E
    ff = CanFrame(1.0, 0x7E0, False, bytes([0x10, 0x14, 0x5A]))
    assert ff.pci == "ff" and ff.payload_sid() == 0x5A
    fc = CanFrame(1.0, 0x7E0, False, bytes([0x30, 0x00, 0x07]))
    assert fc.pci == "fc" and fc.payload_sid() is None


def test_analyze_frames_requires_input():
    with pytest.raises(CanLogError):
        analyze_frames([])


def test_how_to_capture_text_exists_for_the_ui():
    from guzzionboard.canlog import HOW_TO_CAPTURE
    assert "candump" in HOW_TO_CAPTURE and "SavvyCAN" in HOW_TO_CAPTURE


# -- HTTP API ----------------------------------------------------------------


class TestCanLogApi:
    @pytest.fixture
    def api(self, tmp_path):
        from guzzionboard.server import Api
        from guzzionboard.workstation import Workstation

        return Api(Workstation(session_dir=tmp_path / "sessions"))

    def test_analyze_pasted_text(self, api):
        status, payload = api.post_tools_canlog(
            {"text": candump_session(tester_present=3)}
        )
        assert status == 200
        assert payload["diagnostic_traffic_found"] is True
        assert payload["pairs"][0]["request_id"] == "0x7E0"

    def test_analyze_from_a_file(self, api, tmp_path):
        capture = tmp_path / "session.log"
        capture.write_text(candump_session(), encoding="utf-8")
        status, payload = api.post_tools_canlog({"path": str(capture)})
        assert status == 200
        assert payload["format"] == "candump"

    def test_errors(self, api, tmp_path):
        assert api.post_tools_canlog({})[0] == 400
        assert api.post_tools_canlog({"text": "   "})[0] == 400
        status, payload = api.post_tools_canlog({"path": str(tmp_path / "nope")})
        assert status == 400 and "cannot read" in payload["error"]
