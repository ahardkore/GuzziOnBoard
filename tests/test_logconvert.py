"""ZT-2 (ZDL) CSV -> LogWorks DIF conversion."""
import pytest

from guzzionboard.logconvert import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_TIMELINE_FACTOR,
    LogConvertError,
    convert_z2csv_to_dif,
)

CSV = "AFR,RPM,TPS,MAP,EGT\n11.2,2400,12,98.4,512\n11.4,2450,13,98.1,515\n11.3,2500,14,97.9,517\n"


def test_comma_export_converts_with_corrected_timeline():
    result = convert_z2csv_to_dif(CSV)
    lines = result["dif"].splitlines()
    assert lines[0].split("\t")[0] == "Time (s)"
    # nominal 65 Hz sampling and the documented "logs 4x more" factor
    step = DEFAULT_TIMELINE_FACTOR / DEFAULT_SAMPLE_RATE
    second = lines[1].split("\t")
    third = lines[2].split("\t")
    assert second[0] == "0.000"
    assert float(third[0]) == pytest.approx(step, abs=1e-3)
    assert second[1:] == ["11.2", "2400", "12", "98.4", "512"]
    assert result["rows"] == 3
    assert result["duration_s"] == pytest.approx(2 * step, abs=1e-3)


def test_factor_one_reproduces_the_reference_tools_timeline():
    result = convert_z2csv_to_dif(CSV, timeline_factor=1.0)
    third = result["dif"].splitlines()[2].split("\t")
    assert float(third[0]) == pytest.approx(1 / DEFAULT_SAMPLE_RATE, abs=1e-3)


def test_semicolon_german_locale_and_comma_decimals():
    text = "Zeit;AFR;RPM;TPS\n0,0;11,2;2400;12\n0,1;11,4;2450;13\n"
    result = convert_z2csv_to_dif(text)
    assert result["rows"] == 2
    row = result["dif"].splitlines()[1].split("\t")
    assert row[1] == "0" and row[2] == "11.2" and row[3] == "2400"
    # a real Time column survives as a channel; the axis is still rebuilt
    assert result["channels"][0] == "Zeit"


def test_channel_labels_are_canonicalised_but_units_kept():
    text = "afr,egt (C),boost,user1\n11,500,1.2,0.5\n"
    result = convert_z2csv_to_dif(text)
    assert result["channels"] == ["AFR", "egt (C)", "Boost", "USER1"]


def test_rejects_input_that_is_not_a_zt2_export():
    with pytest.raises(LogConvertError):
        convert_z2csv_to_dif("")
    with pytest.raises(LogConvertError, match="AFR"):
        convert_z2csv_to_dif("foo,bar\n1,2\n")
    with pytest.raises(LogConvertError, match="fields"):
        convert_z2csv_to_dif("AFR,RPM\n11,2400,extra\n")
    with pytest.raises(LogConvertError, match="number"):
        convert_z2csv_to_dif("AFR,RPM\nsoon,2400\n")
    with pytest.raises(LogConvertError):
        convert_z2csv_to_dif(CSV, sample_rate=0)
    with pytest.raises(LogConvertError):
        convert_z2csv_to_dif(CSV, timeline_factor=-4)
