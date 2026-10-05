"""Session export and replay.

A recorded session is only useful if it can leave the tool. These cover the
CSV shape (units and raw bytes travel with the numbers) and the replay path,
where the derived channels and findings are recomputed from the recorded
bytes with the recorded timestamps.
"""
from __future__ import annotations

import csv
import io

from guzzionboard import replay
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


def sample_event(t, key, value, unit="", raw="00", local_id=0x30):
    return {"t": t, "kind": "sample", "key": key, "value": value,
            "unit": unit, "raw": raw, "local_id": local_id}


def a_session(sweeps=4, start=1000.0):
    events = [{"t": start - 1, "kind": "session_start", "meta": {}}]
    for i in range(sweeps):
        t = start + i
        events += [
            sample_event(t, "rpm", 1200 + i * 50, "rpm", "04 b0"),
            sample_event(t + 0.05, "battery", 14.1, "V", "8d", 0x3C),
            sample_event(t + 0.1, "injection_ms", 2.0 + i * 0.1, "ms", "07 d0", 0x39),
        ]
    events.append({"t": start + sweeps, "kind": "frame", "dir": "tx", "hex": "81 10"})
    return events


# ---------------------------------------------------------------- sweeps

def test_samples_are_grouped_into_polling_sweeps():
    grouped = replay.sweeps(a_session(sweeps=3))
    assert len(grouped) == 3
    assert set(grouped[0]["values"]) == {"rpm", "battery", "injection_ms"}


def test_a_repeated_channel_starts_a_new_sweep():
    events = [sample_event(1.0, "rpm", 1000, "rpm"),
              sample_event(1.1, "rpm", 1010, "rpm")]
    assert len(replay.sweeps(events)) == 2


def test_non_sample_events_are_ignored():
    events = [{"t": 1.0, "kind": "frame", "hex": "81"},
              sample_event(2.0, "rpm", 1000, "rpm")]
    assert len(replay.sweeps(events)) == 1


# ------------------------------------------------------------------- csv

def test_csv_carries_units_and_raw_bytes():
    text = replay.to_csv(a_session(sweeps=2))
    rows = list(csv.reader(io.StringIO(text)))
    header, units = rows[0], rows[1]
    assert header[:2] == ["time_unix", "elapsed_s"]
    assert "rpm" in header and "rpm_raw" in header
    assert units[header.index("battery")] == "V"
    assert rows[2][header.index("rpm_raw")] == "04 b0"
    assert len(rows) == 4                      # header + units + two sweeps


def test_csv_elapsed_time_starts_at_zero():
    rows = list(csv.reader(io.StringIO(replay.to_csv(a_session(sweeps=3)))))
    assert rows[2][1] == "0.000"
    assert float(rows[4][1]) == 2.0


def test_csv_can_leave_the_raw_bytes_out():
    text = replay.to_csv(a_session(sweeps=1), include_raw=False)
    assert "_raw" not in text


def test_an_empty_session_still_produces_a_valid_header():
    text = replay.to_csv([{"t": 1, "kind": "frame"}])
    assert text.splitlines()[0] == "time_unix,elapsed_s"


# ---------------------------------------------------------------- replay

def test_replay_recomputes_derived_values_and_findings():
    out = replay.frames(a_session(sweeps=4))
    assert len(out["frames"]) == 4
    assert out["duration_s"] == 3.0
    last = out["frames"][-1]
    assert any(c["key"] == "inj_duty" for c in last["derived"])
    assert last["values"]["rpm"]["raw"] == "04 b0"
    assert "recomputed now" in out["note"]


def test_replay_uses_the_recorded_clock_not_the_wall_clock():
    """The analyzer's window must mean the same thing on replay."""
    events = []
    for i in range(6):
        t = 1000.0 + i * 20          # 20 s apart: a 100 s span
        events.append(sample_event(t, "lambda_f", 450 + (i % 2) * 300, "mV"))
    out = replay.frames(events)
    swing = next(c for c in out["frames"][-1]["derived"]
                 if c["key"] == "lambda_swing_f")
    # Only the samples inside the 60 s window may contribute.
    assert swing["value"] == 300


# ------------------------------------------------------------ through API

def test_export_and_replay_endpoints(tmp_path):
    api = Api(Workstation(session_dir=tmp_path))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    api.ws.connect(mode="simulator")
    for _ in range(3):
        api.get_live({"keys": ["rpm,injection_ms,battery"]})
    name = api.ws.log.path.name
    api.ws.disconnect()

    status, body = api.get_export({"name": [name]})
    assert status == 200
    assert body["filename"].endswith(".csv")
    assert body["rows"] >= 3
    assert "rpm" in body["content"].splitlines()[0]
    assert body["content"].splitlines()[1].startswith(",s,")   # the units row

    status, body = api.get_session_replay({"name": [name]})
    assert status == 200
    assert len(body["frames"]) >= 3
    assert "rpm" in body["channels"]
    assert body["frames"][-1]["derived"]


def test_a_session_outside_the_session_directory_is_refused(tmp_path):
    api = Api(Workstation(session_dir=tmp_path))
    assert api.get_export({"name": ["../../etc/passwd"]})[0] == 404
    assert api.get_export({"name": ["x.jsonl"], "format": ["xml"]})[0] == 400
    assert api.get_session_replay({"name": ["nope.jsonl"]})[0] == 404
