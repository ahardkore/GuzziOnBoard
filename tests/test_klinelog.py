"""The capture characteriser: can it rebuild an identifier table?"""
from __future__ import annotations

import math

import pytest

from guzzionboard import klinelog
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


def frame(payload: bytes, target: int, source: int) -> bytes:
    body = bytes([0x80, target, source, len(payload)]) + payload
    return body + bytes([sum(body) & 0xFF])


def synthetic_capture(points=40):
    """A tester sweeping two identifiers while the engine is revved."""
    lines = []
    csv_rows = ["time,Engine speed,Battery"]
    for i in range(points):
        t = i * 0.2
        rpm_raw = 800 + i * 50                 # shown = raw * 10
        battery_raw = 1200 + i                 # shown = raw * 0.01
        for rli, raw in ((0x30, rpm_raw.to_bytes(2, "big")),
                         (0x42, battery_raw.to_bytes(2, "big"))):
            lines.append(f"{t:.3f} tx " + frame(bytes([0x21, rli]), 0x10, 0xF1).hex(" "))
            lines.append(
                f"{t + 0.02:.3f} rx "
                + frame(bytes([0x61, rli]) + raw, 0xF1, 0x10).hex(" ")
            )
        csv_rows.append(f"{t:.3f},{rpm_raw * 10},{battery_raw * 0.01:.2f}")
    return "\n".join(lines), "\n".join(csv_rows)


def test_parses_annotated_hex_lines():
    capture, _ = synthetic_capture(4)
    frames = klinelog.parse(capture)
    assert len(frames) == 16
    assert frames[0].direction == "tx"
    assert frames[0].service == 0x21
    assert frames[1].direction == "rx"


def test_parses_an_unstructured_hex_dump():
    blob = (frame(bytes([0x21, 0x30]), 0x10, 0xF1)
            + frame(bytes([0x61, 0x30, 0x0B, 0xB8]), 0xF1, 0x10)).hex()
    frames = klinelog.parse(blob)
    assert [f.service for f in frames] == [0x21, 0x61]
    # Direction is recovered from the addresses, not from any annotation.
    assert [f.direction for f in frames] == ["tx", "rx"]


def test_parses_session_jsonl():
    raw = frame(bytes([0x61, 0x30, 0x0B, 0xB8]), 0xF1, 0x10).hex(" ")
    text = (
        '{"kind": "note", "text": "ignored"}\n'
        '{"kind": "frame", "t": 1.5, "dir": "rx", "hex": "%s"}\n' % raw
    )
    frames = klinelog.parse(text)
    assert len(frames) == 1 and frames[0].t == 1.5


def test_empty_capture_is_refused():
    with pytest.raises(klinelog.KLineLogError):
        klinelog.parse("   ")
    with pytest.raises(klinelog.KLineLogError):
        klinelog.parse("nothing resembling a frame here")


def test_characterise_reports_each_identifier():
    capture, _ = synthetic_capture()
    result = klinelog.analyze(capture)
    ids = {entry["hex"]: entry for entry in result["identifiers"]}
    assert set(ids) == {"0x30", "0x42"}
    assert ids["0x30"]["answers"] == 40
    assert ids["0x30"]["length"] == 2
    assert ids["0x30"]["moved"] is True
    assert ids["0x30"]["always_zero"] is False
    assert result["summary"]["moved"] == 2
    assert any(s["name"] == "READ_DATA_BY_LOCAL_ID" for s in result["services_seen"])


def test_refusals_are_recorded_not_invented():
    capture = "\n".join([
        "0.0 tx " + frame(bytes([0x21, 0x7E]), 0x10, 0xF1).hex(" "),
        "0.1 rx " + frame(bytes([0x7F, 0x21, 0x12]), 0xF1, 0x10).hex(" "),
    ])
    result = klinelog.analyze(capture)
    entry = result["identifiers"][0]
    assert entry["answers"] == 0
    assert entry["refusals"] == 1
    assert entry["nrcs"] == ["0x12"]
    # A refused identifier never reaches the draft catalog.
    assert result["draft"]["parameters"] == []


def test_a_dead_slot_is_marked_dead_not_dropped():
    lines = []
    for i in range(6):
        lines.append(f"{i * 0.2:.1f} tx " + frame(bytes([0x21, 0x55]), 0x10, 0xF1).hex(" "))
        lines.append(f"{i * 0.2 + 0.02:.2f} rx "
                     + frame(bytes([0x61, 0x55, 0x00, 0x00]), 0xF1, 0x10).hex(" "))
    result = klinelog.analyze("\n".join(lines))
    param = result["draft"]["parameters"][0]
    assert param["dead"] is True
    assert param["confidence"] == "verified-capture"


def test_scaling_is_solved_against_a_reference_log():
    capture, reference = synthetic_capture()
    result = klinelog.analyze(capture, reference, family="15M")
    matches = {m["channel"]: m for m in result["matches"]}
    assert set(matches) == {"Engine speed", "Battery"}
    assert matches["Engine speed"]["local_id"] == 0x30
    assert matches["Engine speed"]["scale"] == 10.0
    assert math.isclose(matches["Engine speed"]["bias"], 0.0, abs_tol=1e-6)
    assert matches["Battery"]["local_id"] == 0x42
    assert matches["Battery"]["scale"] == 0.01
    assert matches["Engine speed"]["fit"] >= 0.999


def test_a_solved_channel_earns_verified_capture_and_nothing_else_does():
    capture, reference = synthetic_capture()
    # A third identifier that moves but has no column in the reference log.
    extra = []
    for i in range(10):
        t = i * 0.2
        extra.append(f"{t:.3f} tx " + frame(bytes([0x21, 0x60]), 0x10, 0xF1).hex(" "))
        extra.append(f"{t + 0.02:.3f} rx "
                     + frame(bytes([0x61, 0x60, i * 7]), 0xF1, 0x10).hex(" "))
    result = klinelog.analyze(capture + "\n" + "\n".join(extra), reference,
                              family="15M")
    params = {p["local_id"]: p for p in result["draft"]["parameters"]}
    assert params[0x30]["confidence"] == "verified-capture"
    assert params[0x30]["key"] == "engine_speed"
    assert "r^2" in params[0x30]["source_note"]
    assert params[0x60]["confidence"] == "unknown"
    assert params[0x60]["key"] == "unknown_60"
    assert "needs a reference log" in params[0x60]["source_note"]
    assert result["draft"]["family"] == "15M"


def test_a_coincidence_is_refused():
    """Noise must not be dignified with a scaling."""
    lines, rows = [], ["time,Something"]
    for i in range(20):
        t = i * 0.2
        value = (i * 37) % 251
        lines.append(f"{t:.3f} tx " + frame(bytes([0x21, 0x31]), 0x10, 0xF1).hex(" "))
        lines.append(f"{t + 0.02:.3f} rx "
                     + frame(bytes([0x61, 0x31, value]), 0xF1, 0x10).hex(" "))
        rows.append(f"{t:.3f},{(i * 91) % 173}")
    result = klinelog.analyze("\n".join(lines), "\n".join(rows))
    assert result["matches"] == []


def test_ecu_identification_is_carried_through():
    payload = bytes([0x5A, 0x80]) + b"IAW15M"
    capture = "0.0 rx " + frame(payload, 0xF1, 0x10).hex(" ")
    result = klinelog.analyze(capture)
    assert result["identification"][0]["ascii"] == "IAW15M"


def test_reference_csv_with_a_units_row_is_tolerated():
    reference = klinelog.read_reference_csv(
        "time,Engine speed\n,rpm\n0.0,1000\n0.2,1100\n"
    )
    assert reference["times"] == [0.0, 0.2]
    assert reference["columns"]["Engine speed"] == [1000.0, 1100.0]


def test_short_reference_csv_is_refused():
    with pytest.raises(klinelog.KLineLogError):
        klinelog.read_reference_csv("time,x\n0,1\n")


def test_api_endpoint_characterises_pasted_text():
    api = Api(Workstation(record=False))
    capture, reference = synthetic_capture()
    status, body = api.post_tools_klinelog(
        {"text": capture, "reference": reference, "family": "15M"})
    assert status == 200
    assert body["draft"]["family"] == "15M"
    assert len(body["matches"]) == 2
    assert "observations" not in body        # internals stay internal


def test_api_endpoint_needs_a_capture():
    api = Api(Workstation(record=False))
    status, body = api.post_tools_klinelog({})
    assert status == 400 and "capture" in body["error"]


def test_api_endpoint_reports_a_bad_capture():
    api = Api(Workstation(record=False))
    status, body = api.post_tools_klinelog({"text": "hello"})
    assert status == 400 and "no KWP2000 frames" in body["error"]


def test_api_endpoint_reports_a_missing_file():
    api = Api(Workstation(record=False))
    status, body = api.post_tools_klinelog({"path": "/nope/missing.log"})
    assert status == 400 and "no such capture" in body["error"]
