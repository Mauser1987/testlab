"""LabVIEW/DCS export parser (M2A). Recognised by content, never by file name."""

import math
from datetime import datetime
from pathlib import Path

import pytest

from testlab.execution import labview

REFERENCE = Path(__file__).resolve().parents[4] / "reference" / "M2-tes-results" / "labview"

HEADER = "10/01/26\t11:43:01 AM\tPROJECT - Customer\tPROJECT - TCN001\t\t\t\n"
NAMES = "Time\t(T04) LBI\t(X22) Process Syst Press\tMotor Speed\n"
UNITS = "Hrs\tT [C]\tBarG\tRPM\n"


def export(rows=20, header=HEADER):
    lines = [f"{i * 5 / 3600:.6f}\t{40 + i * 0.1:.3f}\t{30 + (i % 3) * 0.01:.3f}\t{5600 + i:.3f}\n" for i in range(rows)]
    return (header + NAMES + UNITS + "".join(lines)).encode("ascii")


NAME = "PROJECT - TCN001 Thu, Oct 01, 2026 11 43 AM"


def test_labview_layout():
    parsed = labview.parse(export(), NAME)
    assert parsed.delimiter == "\t"
    assert parsed.header_lines == [HEADER.rstrip("\n")]
    assert parsed.names == ["Time", "(T04) LBI", "(X22) Process Syst Press", "Motor Speed"]
    assert parsed.units == ["Hrs", "T [C]", "BarG", "RPM"]
    assert parsed.time_column == 0 and parsed.time_unit == "Hrs"
    assert parsed.sample_count == 20
    assert parsed.columns[3][19] == 5619
    assert parsed.warnings == []


def test_start_date_confirmed_by_file_name():
    parsed = labview.parse(export(), NAME)
    assert parsed.recording_started_at == datetime(2026, 10, 1, 11, 43, 1)
    assert "confirmed by the file name" in parsed.recording_start_note


def test_ambiguous_date_without_file_name_is_not_guessed():
    parsed = labview.parse(export(), "export")
    assert parsed.recording_started_at is None
    assert "month/day or day/month" in parsed.recording_start_note


def test_unambiguous_date_without_file_name():
    parsed = labview.parse(export(header="10/25/26\t1:05:00 PM\n"), "export")
    assert parsed.recording_started_at == datetime(2026, 10, 25, 13, 5)


def test_file_name_date_that_does_not_match_is_reported():
    parsed = labview.parse(export(), "PROJECT Mon, Nov 02, 2026 9 00 AM")
    assert parsed.recording_started_at is None and "does not match" in parsed.recording_start_note


def test_semicolon_with_decimal_comma_and_seconds():
    content = "Zeit;Druck\ns;bar\n0;1,5\n5;1,6\n10;1,7\n15;1,8\n20;1,9\n25;2,0\n".encode("cp1252")
    parsed = labview.parse(content, "data")
    assert parsed.delimiter == ";" and parsed.names == ["Zeit", "Druck"]
    assert list(parsed.columns[1]) == [1.5, 1.6, 1.7, 1.8, 1.9, 2.0]
    assert parsed.time_h[1] == pytest.approx(5 / 3600)  # seconds → hours


def test_comma_separated_with_names_only():
    content = b"time,flow,leak\n" + b"".join(f"{i},{i * 2},{i * 3}\n".encode() for i in range(10))
    parsed = labview.parse(content, "x")
    assert parsed.delimiter == "," and parsed.names == ["time", "flow", "leak"] and parsed.units == ["", "", ""]
    assert any("not recognised" in w for w in parsed.warnings)  # no time unit: read as hours, said so


def test_cp1252_degree_sign():
    content = "Time\tT\nHrs\t°C\n" + "".join(f"{i}\t{i}.5\n" for i in range(8))
    parsed = labview.parse(content.encode("cp1252"), "x")
    assert parsed.units[1] == "°C" and parsed.encoding == "cp1252"


def test_bad_values_and_ragged_rows_are_kept_as_gaps_with_warnings():
    content = export(10) + b"0.020000\tERR\t30.0\t5600\n0.021000\t41.0\n"
    parsed = labview.parse(content, NAME)
    assert parsed.sample_count == 12
    assert math.isnan(parsed.columns[1][10]) and math.isnan(parsed.columns[3][11])
    assert any("non-numeric" in w for w in parsed.warnings)
    assert any("columns instead of 4" in w for w in parsed.warnings)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"\x00\x01\x02binary", "binary"),
        (b"just some\ntext without\nnumbers\n", "No block of numeric data"),
        (b"", "No block of numeric data"),
    ],
)
def test_not_an_export(content, reason):
    with pytest.raises(labview.LabviewFormatError, match=reason):
        labview.parse(content, "x")


@pytest.mark.skipif(not REFERENCE.is_dir(), reason="reference/ is kept locally only")
def test_real_reference_export():
    path = next(REFERENCE.iterdir())
    parsed = labview.parse(path.read_bytes(), path.name)
    assert parsed.sample_count == 14118 and len(parsed.names) == 12
    assert parsed.recording_started_at == datetime(2026, 10, 1, 11, 43, 1)
    assert parsed.warnings == []
