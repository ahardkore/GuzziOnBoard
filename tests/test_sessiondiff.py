"""Session comparison: two recorded sessions, channel by channel.

A second session is the cheapest baseline there is - record one cold,
another after a change, and the comparison names the channels that moved.
Sessions are not aligned in time, so means are compared, never points.
"""
from __future__ import annotations

import pytest

from guzzionboard.sessiondiff import SessionDiffError, compare, summarise
from guzzionboard.sessionlog import SessionLog


def record(tmp_path, name: str, meta: dict, samples: list[tuple[str, float, str]],
           dtcs: list[str] | None = None) -> object:
    log = SessionLog(directory=tmp_path, meta=meta, enabled=True)
    for key, value, unit in samples:
        log.sample(key, 0x01, bytes([int(value) & 0xFF]), value, unit)
    if dtcs is not None:
        log.action("read_dtcs", {
            "count": len(dtcs),
            "dtcs": [{"code": c} for c in dtcs],
            "context": {"rpm": {"value": 1250, "unit": "rpm"}},
        })
    log.close()
    return log


def test_summarise_distils_one_session(tmp_path):
    log = record(tmp_path, "a", {"model": "Griso 1200 8V", "ecu_family": "IAW 5AM"},
                 [("rpm", 1250.0, "rpm"), ("rpm", 1300.0, "rpm"),
                  ("coolant_temp", 60.0, "°C")],
                 dtcs=["P0130", "P0505"])
    summary = summarise(log.path)
    assert summary["meta"]["model"] == "Griso 1200 8V"
    assert summary["channels"]["rpm"]["mean"] == 1275.0
    assert summary["channels"]["rpm"]["min"] == 1250.0
    assert summary["channels"]["coolant_temp"]["mean"] == 60.0
    assert summary["dtcs"] == ["P0130", "P0505"]


def test_compare_names_what_moved(tmp_path):
    cold = record(tmp_path, "cold", {"model": "V7 III Stone"},
                  [("rpm", 1200.0, "rpm"), ("coolant_temp", 20.0, "°C")],
                  dtcs=["P0130"])
    warm = record(tmp_path, "warm", {"model": "V7 III Stone"},
                  [("rpm", 1400.0, "rpm"), ("coolant_temp", 88.0, "°C")],
                  dtcs=["P0130", "P0505"])

    d = compare(cold.path, warm.path)
    by_key = {c["key"]: c for c in d["channels"]}
    assert by_key["rpm"]["a"]["mean"] == 1200.0
    assert by_key["rpm"]["b"]["mean"] == 1400.0
    assert by_key["rpm"]["delta_mean"] == 200.0
    assert by_key["coolant_temp"]["delta_mean"] == 68.0
    assert d["dtcs"] == {"both": ["P0130"], "only_a": [], "only_b": ["P0505"]}
    assert d["channels_only_in_a"] == [] and d["channels_only_in_b"] == []


def test_compare_reports_channels_sampled_on_one_side_only(tmp_path):
    a = record(tmp_path, "a", {}, [("rpm", 1250.0, "rpm"), ("tp", 12.0, "%")])
    b = record(tmp_path, "b", {}, [("rpm", 1300.0, "rpm"), ("lambda", 1.02, "")])
    d = compare(a.path, b.path)
    assert d["channels_only_in_a"] == ["tp"]
    assert d["channels_only_in_b"] == ["lambda"]
    by_key = {c["key"]: c for c in d["channels"]}
    assert by_key["tp"]["delta_mean"] is None


def test_unreadable_sessions_are_refused(tmp_path):
    with pytest.raises(SessionDiffError):
        summarise(tmp_path / "nope.jsonl")
    good = record(tmp_path, "good", {}, [("rpm", 1.0, "rpm")])
    with pytest.raises(SessionDiffError):
        compare(good.path, tmp_path / "nope.jsonl")


class TestCompareApi:
    @pytest.fixture
    def api(self, tmp_path):
        from guzzionboard.server import Api
        from guzzionboard.workstation import Workstation

        return Api(Workstation(session_dir=tmp_path, record=False))

    def test_compare_over_http(self, api, tmp_path):
        record(tmp_path, "a", {"model": "Griso"}, [("rpm", 1200.0, "rpm")])
        record(tmp_path, "b", {"model": "Griso"}, [("rpm", 1500.0, "rpm")])
        names = sorted(p.name for p in tmp_path.glob("*.jsonl"))
        status, payload = api.post_sessions_compare(
            {"a": names[0], "b": names[1]}
        )
        assert status == 200
        by_key = {c["key"]: c for c in payload["channels"]}
        assert by_key["rpm"]["delta_mean"] is not None

    def test_compare_rejects_bad_requests(self, api):
        assert api.post_sessions_compare({})[0] == 400
        assert api.post_sessions_compare({"a": "x", "b": "x"})[0] == 400
        status, payload = api.post_sessions_compare({"a": "x", "b": "y"})
        assert status == 404 and "no such session" in payload["error"]
