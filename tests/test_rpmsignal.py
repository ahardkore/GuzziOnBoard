"""Bench RPM trigger-signal generator (WAV)."""
import struct
import wave

import pytest

from guzzionboard.rpmsignal import (
    PRESETS,
    SignalError,
    TriggerWheel,
    DEFAULT_SAMPLE_RATE,
    generate,
    parse_events,
    render_samples,
)


def test_presets_match_the_reference_tools_config_files():
    # vendor/guzzidiag/tools/RPMSensorEmu_V0.17.zip: MotoGuzzi.cfg,
    # Ducati.cfg, MotoMorini.cfg say 46 present + 2 missing on the camshaft;
    # MVAgusta.cfg says 22 + 2 on the crankshaft.
    for name in ("motoguzzi", "ducati", "motomorini"):
        assert PRESETS[name] == TriggerWheel(46, 2, "camshaft")
    assert PRESETS["mvagusta"] == TriggerWheel(22, 2, "crankshaft")


def test_cam_wheel_turns_half_engine_speed():
    wheel = PRESETS["motoguzzi"]
    assert wheel.pattern_rev_rate(6000) == 50.0     # cam: rpm/2 per minute
    assert PRESETS["mvagusta"].pattern_rev_rate(6000) == 100.0  # crank


def test_batch_events_follow_the_reference_format():
    assert parse_events([[3000, 1000], [5000, 1000, 3000]]) == [
        (3000, 1000.0, 1000.0), (5000, 1000.0, 3000.0)
    ]
    with pytest.raises(SignalError, match="100"):
        parse_events([[1050, 1000]])        # not a 100 ms multiple
    with pytest.raises(SignalError, match="duration|rpm"):
        parse_events([[1000]])
    with pytest.raises(SignalError, match="positive"):
        parse_events([[1000, 0]])
    with pytest.raises(SignalError, match="no events"):
        parse_events([])


def _rising_edges(pcm: bytes) -> list[int]:
    values = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    edges = []
    for i in range(1, len(values)):
        if values[i - 1] < 0 <= values[i]:
            edges.append(i)
    return edges


def test_trigger_train_has_right_teeth_and_missing_gap():
    wheel = TriggerWheel(46, 2, "camshaft")
    rpm = 3000.0
    rendered = render_samples(wheel, [(2000, rpm, rpm)], sample_rate=DEFAULT_SAMPLE_RATE)
    edges = _rising_edges(rendered["pcm"])

    slot_samples = DEFAULT_SAMPLE_RATE / (wheel.pattern_rev_rate(rpm) * wheel.slots)
    intervals = [b - a for a, b in zip(edges, edges[1:])]
    nominal = [iv for iv in intervals if iv < 2 * slot_samples]
    gaps = [iv for iv in intervals if iv >= 2 * slot_samples]

    # every tooth interval is the slot period (±1 sample of quantisation)
    assert all(abs(iv - slot_samples) <= 2 for iv in nominal)
    # one synchronisation gap per wheel revolution,
    # (missing + the two low half-slots) = (missing + 1) slot periods long
    assert gaps, "no synchronisation gap found"
    assert all(
        abs(iv - (wheel.missing + 1) * slot_samples) <= 3 for iv in gaps
    )
    # one revolution spans slots * slot_samples; pulses per rev = present teeth
    total_span = DEFAULT_SAMPLE_RATE / wheel.pattern_rev_rate(rpm)
    revs = (len(rendered["pcm"]) // 2) / total_span
    assert len(edges) == pytest.approx(wheel.teeth * revs, rel=0.02)


def test_ramp_changes_the_tooth_rate():
    wheel = TriggerWheel(46, 2, "camshaft")
    rendered = render_samples(
        wheel, [(2000, 2000.0, 6000.0)], sample_rate=DEFAULT_SAMPLE_RATE
    )
    edges = _rising_edges(rendered["pcm"])
    early = edges[5] - edges[4]
    late = edges[-2] - edges[-3]
    # 3x rpm means ~1/3 the interval (allowing ramp course through the loop)
    assert late < early * 0.45


def test_generate_writes_a_valid_wav(tmp_path):
    result = generate(
        PRESETS["motoguzzi"], [[1000, 3000]], out_dir=tmp_path, name="test"
    )
    with wave.open(result["path"], "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == DEFAULT_SAMPLE_RATE
        assert w.getnframes() == DEFAULT_SAMPLE_RATE * 1  # 1000 ms
    assert result["teeth"] == 46 and result["missing"] == 2
    assert result["wheel"] == "camshaft"
    assert "safety" in result and "AC-couple" in result["safety"]
