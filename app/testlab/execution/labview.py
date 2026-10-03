"""Read a LabVIEW/DCS text export (M2A).

The format is recognised from the content, never from the file name: the
exports have no extension. Observed layout of a test-bench export:

    10/01/26<TAB>11:43:01 AM<TAB>PROJECT - Customer<TAB>…        metadata line(s)
    Time<TAB>(T04) LBI<TAB>(T05) LBO<TAB>…<TAB>Motor Torque          signal names
    Hrs<TAB>T [C]<TAB>T [C]<TAB>…<TAB>Nm                             units
    0.000144<TAB>22.799<TAB>21.475<TAB>…                             numbers, one row per sample

Tab, semicolon and comma separators are recognised (semicolon files may use
a decimal comma). The numeric block is found by content; the two lines
above it are signal names and units (or only names). Nothing in a signal
name is interpreted: names and units are kept as written.

parse() is a pure function of the bytes and the file name; it raises
LabviewFormatError with a readable reason for anything it cannot read.
"""

import math
import re
from array import array
from dataclasses import dataclass, field
from datetime import date, datetime

DELIMITERS = ["\t", ";", ","]
NAMES = {"\t": "tab", ";": "semicolon", ",": "comma"}
MAX_HEADER_LINES = 50
CONFIRM_ROWS = 5

# Time column units, as factor to hours.
TIME_UNITS = {
    "hrs": 1.0, "hr": 1.0, "h": 1.0, "hours": 1.0, "hour": 1.0,
    "min": 1 / 60, "mins": 1 / 60, "minutes": 1 / 60,
    "s": 1 / 3600, "sec": 1 / 3600, "secs": 1 / 3600, "seconds": 1 / 3600,
}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
HEADER_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")
HEADER_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?$")
NAME_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
MAX_WARNINGS = 20


class LabviewFormatError(ValueError):
    """The file is not a readable LabVIEW/DCS text export."""


@dataclass
class ParsedDataset:
    encoding: str
    delimiter: str
    header_lines: list
    names: list
    units: list
    time_column: int
    time_unit: str
    columns: list  # array("d") per column; the time column converted to hours; NaN = no value
    recording_started_at: datetime | None
    recording_start_note: str
    warnings: list = field(default_factory=list)

    @property
    def sample_count(self):
        return len(self.columns[0]) if self.columns else 0

    @property
    def time_h(self):
        return self.columns[self.time_column]


def _number(text, decimal_comma):
    text = text.strip()
    if decimal_comma:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _fields(line, delimiter):
    return line.rstrip("\r").split(delimiter)


def _trim(fields):
    """Fields without trailing empty ones (LabVIEW pads metadata lines with tabs)."""
    while fields and not fields[-1].strip():
        fields = fields[:-1]
    return fields


def _is_numeric_row(fields, width, decimal_comma):
    filled = [f for f in fields if f.strip()]
    if len(fields) < width or len(filled) < 2:
        return False
    numeric = sum(1 for f in filled if _number(f, decimal_comma) is not None)
    return numeric / len(filled) > 0.5


def _find_block(lines, delimiter):
    """(start index, column count) of the numeric block for a delimiter, or None."""
    decimal_comma = delimiter == ";"
    for index, line in enumerate(lines[: MAX_HEADER_LINES + 1]):
        fields = _trim(_fields(line, delimiter))
        width = len(fields)
        if width < 2 or not _is_numeric_row(fields, width, decimal_comma):
            continue
        following = [l for l in lines[index + 1 : index + 1 + CONFIRM_ROWS * 2] if l.strip()][:CONFIRM_ROWS]
        if all(_is_numeric_row(_trim(_fields(l, delimiter)), width, decimal_comma) for l in following):
            return index, width
    return None


def _decode(data):
    if b"\x00" in data[:65536]:
        raise LabviewFormatError("This is a binary file, not a LabVIEW/DCS text export.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise LabviewFormatError("The file is not readable text.")  # cp1252 fails only on a few bytes


def _looks_like_units(fields):
    """A units row: short tokens such as "Hrs", "T [C]", "BarG", "RPM"."""
    filled = [f.strip() for f in fields if f.strip()]
    return bool(filled) and sum(len(f) for f in filled) / len(filled) <= 8


def _time_column(names, units):
    for index, (name, unit) in enumerate(zip(names, units)):
        if "time" in name.lower() or unit.strip().lower() in TIME_UNITS:
            return index
    return 0


def _header_start(header_lines, delimiter, file_name):
    """Recording start from the first metadata line (date + time), checked against the file name.

    LabVIEW writes the date as digits only (10/01/26). Month/day order is not
    stated in the file; it is decided only when it is unambiguous: one valid
    reading, or the file name ("… Thu, Oct 01, 2026 11 43 AM") names the date.
    """
    if not header_lines:
        return None, "No metadata line before the signal names."
    tokens = [t.strip() for t in _fields(header_lines[0], delimiter) if t.strip()]
    date_match = next((m for m in map(HEADER_DATE.match, tokens) if m), None)
    time_match = next((m for m in map(HEADER_TIME.match, tokens) if m), None)
    if not date_match or not time_match:
        return None, "No date and time in the metadata line."
    a, b, year = (int(g) for g in date_match.groups())
    year += 2000 if year < 100 else 0
    candidates = []
    for month, day in ((a, b), (b, a)):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    hour, minute, second, meridiem = time_match.groups()
    hour, minute, second = int(hour), int(minute), int(second or 0)
    if meridiem:
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    named = NAME_DATE.search(file_name or "")
    raw = f"{date_match.group(0)} {time_match.group(0)}"
    if named:
        month_name, day, named_year = named.groups()
        named_date = date(int(named_year), MONTHS[month_name[:3].lower()], int(day))
        if named_date not in candidates:
            return None, f"The date in the file ({raw}) does not match the date in the file name; start not set."
        chosen, how = named_date, "date confirmed by the file name"
    elif len(candidates) == 1:
        chosen, how = candidates[0], "date unambiguous"
    else:
        return None, f"The date {date_match.group(0)} can be read as month/day or day/month; start not set."
    try:
        start = datetime(chosen.year, chosen.month, chosen.day, hour, minute, second)
    except ValueError:
        return None, f"Invalid time {time_match.group(0)} in the metadata line."
    return start, f"From the metadata line “{raw}” ({how})."


def parse(data, file_name=""):
    """Parse an export; see the module docstring."""
    text, encoding = _decode(data)
    lines = text.splitlines()
    found = {d: _find_block(lines, d) for d in DELIMITERS}
    candidates = [(block[1], -DELIMITERS.index(d), d) for d, block in found.items() if block]
    if not candidates:
        raise LabviewFormatError(
            "No block of numeric data with tab, semicolon or comma separated columns was found."
        )
    width, _, delimiter = max(candidates)
    start, width = found[delimiter]
    decimal_comma = delimiter == ";"

    header = [line for line in lines[:start] if line.strip()]
    if len(header) >= 2 and _looks_like_units(_fields(header[-1], delimiter)):
        names, units, meta = _fields(header[-2], delimiter), _fields(header[-1], delimiter), header[:-2]
    elif header:
        names, units, meta = _fields(header[-1], delimiter), [], header[:-1]
    else:
        names, units, meta = [], [], []
    names = [(names[i].strip() if i < len(names) else "") or f"Column {i + 1}" for i in range(width)]
    units = [units[i].strip() if i < len(units) else "" for i in range(width)]

    warnings = []
    columns = [array("d") for _ in range(width)]
    nan = math.nan
    bad_rows = bad_values = 0
    for number, line in enumerate(lines[start:], start=start + 1):
        if not line.strip():
            continue
        fields = _fields(line, delimiter)
        if len(_trim(fields)) > width or len(fields) < width:
            bad_rows += 1
            if bad_rows <= MAX_WARNINGS:
                warnings.append(f"Line {number}: {len(_trim(fields))} columns instead of {width}; missing values left empty.")
        for column in range(width):
            value = _number(fields[column], decimal_comma) if column < len(fields) else None
            if value is None:
                if column < len(fields) and fields[column].strip():
                    bad_values += 1
                value = nan
            columns[column].append(value)
    if bad_values:
        warnings.append(f"{bad_values} non-numeric value(s) in the data were left empty.")
    if not columns[0]:
        raise LabviewFormatError("The file contains no data rows.")

    time_column = _time_column(names, units)
    time_unit = units[time_column]
    factor = TIME_UNITS.get(time_unit.lower())
    if factor is None:
        factor = 1.0
        warnings.append(f"Time unit “{time_unit or 'none'}” of “{names[time_column]}” not recognised; read as hours.")
    if factor != 1.0:
        columns[time_column] = array("d", (t * factor for t in columns[time_column]))
    time = columns[time_column]
    if any(math.isnan(t) for t in time):
        raise LabviewFormatError(f"The time column “{names[time_column]}” has rows without a time.")
    backwards = sum(1 for previous, current in zip(time, time[1:]) if current < previous)
    if backwards:
        warnings.append(f"Time goes backwards {backwards} time(s); the data is plotted in file order.")

    started_at, start_note = _header_start(meta, delimiter, file_name)
    return ParsedDataset(
        encoding=encoding,
        delimiter=delimiter,
        header_lines=[line.rstrip("\r") for line in meta],
        names=names,
        units=units,
        time_column=time_column,
        time_unit=time_unit,
        columns=columns,
        recording_started_at=started_at,
        recording_start_note=start_note,
        warnings=warnings,
    )
