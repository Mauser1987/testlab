"""Reading an Excel manual log (.xlsx) into a SourceSheet (M2F).

The sheet is read as it is, nothing is interpreted here:

* the header row is the row in the top of the sheet that looks most like
  column headings (date, time, rpm, temp., leakage, units in brackets…);
  the row above it is a group row ("Job", "PLUG") when it holds short
  headings and no "label:" cells; its headings apply to their merged range,
  and to the following columns with a unit until the next heading;
* everything above holds the run's header information: "label:" cells with
  the value next to them, a yes/no next to a text, or free text;
* data rows are the rows below the header with at least one typed value;
  rows that are empty or hold only formulas (prepared, unused rows) are
  ignored and listed.

Every non-empty cell of a data row is kept with its kind, its value, the
number exactly as stored in the file and its formula, so that the import
record shows what TestLab read. Numbers are taken from the file's XML text,
not from a binary float: "80.31" stays 80.31.

Only .xlsx (Office Open XML) is read. Legacy .xls workbooks must be saved as
.xlsx in Excel first.
"""

import io
import posixpath
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from xml.etree import ElementTree

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries

MAX_ROWS = 20000
MAX_COLUMNS = 200
HEADER_SCAN_ROWS = 40

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Words that make a cell look like a log column heading.
_HEADER_WORDS = {
    "date", "time", "rpm", "speed", "torque", "temp", "temperature", "press", "pressure", "flow", "leakage",
    "leak", "note", "notes", "by", "hours", "over", "rate", "face", "fi", "fo", "inlet", "outlet",
}  # fmt: skip
_UNIT_PATTERN = re.compile(r"[\[(]([^\[\]()]*)[\])]\s*$")
_YES_NO = {"yes", "no", "y", "n", "ja", "nee", "true", "false", "x"}


class WorkbookError(Exception):
    """The file cannot be read as an Excel manual log."""


@dataclass
class SourceColumn:
    letter: str
    group: str  # group heading above it ("Job", "PLUG"), "" when none
    label: str  # heading without its unit, whitespace collapsed
    unit: str  # from "[…]" or "(…)" at the end of the heading, "" when none
    header: str  # heading as written (line breaks kept)

    def as_dict(self):
        return {"letter": self.letter, "group": self.group, "label": self.label, "unit": self.unit,
                "header": self.header}  # fmt: skip


@dataclass
class SourceSheet:
    name: str
    sheet_names: list
    header_row: int
    group_row: int | None
    columns: list  # [SourceColumn]
    header_items: list  # [{"cell", "label", "value", "value_cell"}]
    rows: list  # [(sheet row, {letter: cell})]
    ignored_rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def check_format(content):
    if content[:4] == b"\xd0\xcf\x11\xe0":
        raise WorkbookError("This is a legacy .xls workbook. Open it in Excel and save it as .xlsx, then import that.")
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise WorkbookError("This is not an .xlsx workbook.")


def _load(content, data_only):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl warns about Excel extensions it does not keep
        return openpyxl.load_workbook(io.BytesIO(content), data_only=data_only)


def sheet_names(content):
    check_format(content)
    try:
        return _load(content, data_only=True).sheetnames
    except Exception as error:  # openpyxl raises many kinds for damaged files
        raise WorkbookError(f"The workbook could not be read: {error}") from error


def _text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


def _words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _raw_numbers(content, name):
    """{cell reference: number text as stored in the sheet XML} of the sheet called `name`."""
    archive = zipfile.ZipFile(io.BytesIO(content))
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target") for rel in rels.iter(f"{_PKG_REL_NS}Relationship")}
    for sheet in workbook.iter(f"{_MAIN_NS}sheet"):
        if sheet.get("name") == name:
            target = targets[sheet.get(f"{_REL_NS}id")]
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            break
    else:
        return {}
    numbers = {}
    with archive.open(path) as stream:
        for _, element in ElementTree.iterparse(stream):
            if element.tag == f"{_MAIN_NS}c":
                value = element.find(f"{_MAIN_NS}v")
                if element.get("t", "n") == "n" and value is not None and value.text:
                    numbers[element.get("r")] = value.text.strip()
                element.clear()
    return numbers


def _cell(formula_cell, value_cell, raw):
    """A cell as kept in the import record, or None when it is empty without a formula."""
    formula = None
    if formula_cell.data_type == "f":
        formula = getattr(formula_cell.value, "text", None) or str(formula_cell.value)
    value = value_cell.value
    if value is None:
        return {"k": "empty", "v": "", "f": formula} if formula else None
    if isinstance(value, bool):
        cell = {"k": "bool", "v": "TRUE" if value else "FALSE"}
    elif isinstance(value, datetime):
        cell = {"k": "datetime", "v": value.isoformat()}
    elif isinstance(value, date):
        cell = {"k": "date", "v": value.isoformat()}
    elif isinstance(value, time):
        cell = {"k": "time", "v": value.isoformat()}
    elif isinstance(value, timedelta):
        cell = {"k": "duration", "v": str(value.total_seconds())}
    elif isinstance(value, (int, float)):
        cell = {"k": "number", "v": repr(value), "raw": raw.get(value_cell.coordinate, repr(value))}
    elif value_cell.data_type == "e":
        cell = {"k": "error", "v": str(value)}
    else:
        if str(value).strip() == "":
            return {"k": "empty", "v": "", "f": formula} if formula else None
        cell = {"k": "text", "v": str(value)}
    if formula:
        cell["f"] = formula
    return cell


def _merged_origin(sheet):
    """{(row, column): (row, column) of the top-left cell} for the cells inside merged ranges."""
    origin = {}
    for merged in sheet.merged_cells.ranges:
        for row in range(merged.min_row, merged.max_row + 1):
            for column in range(merged.min_col, merged.max_col + 1):
                origin[(row, column)] = (merged.min_row, merged.min_col)
    return origin


def _find_header_row(sheet, max_column):
    best, best_score = None, 0
    for row in range(1, min(sheet.max_row, HEADER_SCAN_ROWS) + 1):
        score = 0
        for column in range(1, max_column + 1):
            value = sheet.cell(row, column).value
            if not isinstance(value, str) or value.strip().endswith(":"):
                continue
            if set(_words(value)) & _HEADER_WORDS or _UNIT_PATTERN.search(value.strip()):
                score += 1
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= 3 else None


def _split_unit(header):
    text = _norm(header)
    match = _UNIT_PATTERN.search(text)
    if match:
        return _norm(text[: match.start()]), match.group(1).strip()
    return text, ""


def _list_sources(sheet):
    """Cells that hold the choices of a drop-down list (data validation) on this sheet: not header values."""
    cells = set()
    for validation in sheet.data_validations.dataValidation:
        if validation.type != "list" or not validation.formula1:
            continue
        reference = validation.formula1.split("!")[-1].replace("$", "")
        try:
            min_col, min_row, max_col, max_row = range_boundaries(reference)
        except (TypeError, ValueError):
            continue  # a literal list ("yes,no") or a named range
        if None in (min_col, min_row, max_col, max_row):
            continue
        cells.update((row, column) for row in range(min_row, max_row + 1) for column in range(min_col, max_col + 1))
    return cells


def _header_items(sheet, last_row, max_column, merged):
    """Label/value pairs and free text above the log table, in reading order.

    The choices of a drop-down list kept on the sheet are listed as such (role "list"), never as the
    value of the text next to them.
    """
    list_cells = _list_sources(sheet)
    items = []
    for row in range(1, last_row + 1):
        cells, choices = [], []
        for column in range(1, max_column + 1):
            if merged.get((row, column), (row, column)) != (row, column):
                continue  # inside a merged range: the value is in its top-left cell
            value = sheet.cell(row, column).value
            if value is None or not _text(value).strip():
                continue
            ref = f"{get_column_letter(column)}{row}"
            if (row, column) in list_cells:
                choices.append({"cell": ref, "label": "", "value": _text(value), "value_cell": "", "role": "list"})
            else:
                cells.append((ref, _text(value)))
        index = 0
        while index < len(cells):
            ref, text = cells[index]
            following = cells[index + 1] if index + 1 < len(cells) else None
            is_label = text.strip().endswith(":")
            if following and not following[1].strip().endswith(":") and (
                is_label or following[1].strip().lower() in _YES_NO
            ):
                items.append({"cell": ref, "label": text, "value": following[1], "value_cell": following[0]})
                index += 2
            else:
                items.append({"cell": ref, "label": text if is_label else "", "value": "" if is_label else text,
                              "value_cell": ""})  # fmt: skip
                index += 1
        items += choices
    return items


def read_sheet(content, name=None):
    """The SourceSheet of sheet `name`, or of the first sheet with a log table."""
    check_format(content)
    try:
        formulas = _load(content, data_only=False)
        values = _load(content, data_only=True)
    except Exception as error:
        raise WorkbookError(f"The workbook could not be read: {error}") from error
    names = values.sheetnames
    candidates = [name] if name else names
    for candidate in candidates:
        if candidate not in names:
            raise WorkbookError(f"The workbook has no sheet “{candidate}”.")
        sheet = values[candidate]
        max_column = min(sheet.max_column, MAX_COLUMNS)
        header_row = _find_header_row(sheet, max_column)
        if header_row:
            return _read(content, names, formulas[candidate], sheet, header_row, max_column)
    if name:
        raise WorkbookError(f"No log table found on sheet “{name}”: no row with column headings such as Date, "
                            "Time, RPM, Temp., Leakage.")  # fmt: skip
    raise WorkbookError("No log table found: no sheet has a row with column headings such as Date, Time, RPM, "
                        "Temp., Leakage.")  # fmt: skip


def _read(content, names, formula_sheet, sheet, header_row, max_column):
    merged = _merged_origin(sheet)
    found_warnings = []
    if sheet.max_row > MAX_ROWS:
        found_warnings.append(f"Only the first {MAX_ROWS} rows are read.")
    if sheet.max_column > MAX_COLUMNS:
        found_warnings.append(f"Only the first {MAX_COLUMNS} columns are read.")

    headings = {}
    for column in range(1, max_column + 1):
        if merged.get((header_row, column), (header_row, column)) != (header_row, column):
            continue
        value = sheet.cell(header_row, column).value
        if value is not None and _text(value).strip():
            headings[column] = _text(value)

    group_row = None
    if header_row > 1:
        above = header_row - 1
        texts = {}
        for column in headings:
            origin = merged.get((above, column), (above, column))
            value = sheet.cell(*origin).value
            if value is not None and _text(value).strip():
                texts[column] = (origin, _text(value))
        if texts and not any(text.strip().endswith(":") for _, text in texts.values()):
            group_row = above

    columns, carried = [], ""
    for column, heading in headings.items():
        label, unit = _split_unit(heading)
        group = ""
        if group_row:
            origin = merged.get((group_row, column), (group_row, column))
            value = sheet.cell(*origin).value
            group = _norm(_text(value)) if value is not None else ""
        if group:
            carried = group
        elif carried and unit:
            group = carried  # a heading over its first column applies to the following columns with a unit
        else:
            carried = ""
        columns.append(SourceColumn(get_column_letter(column), group, label, unit, heading))

    raw = _raw_numbers(content, sheet.title)
    rows, ignored = [], []
    header_columns = set(headings)
    stray = set()
    for row in range(header_row + 1, min(sheet.max_row, MAX_ROWS) + 1):
        cells = {}
        for column in range(1, max_column + 1):
            if merged.get((row, column), (row, column)) != (row, column):
                continue
            cell = _cell(formula_sheet.cell(row, column), sheet.cell(row, column), raw)
            if cell is not None:
                cells[get_column_letter(column)] = cell
        typed = [letter for letter, cell in cells.items() if cell["k"] != "empty" and "f" not in cell]
        if not typed:
            if cells:
                ignored.append(row)
            continue
        rows.append((row, cells))
        for letter in typed:
            index = openpyxl.utils.column_index_from_string(letter)
            if index not in header_columns:
                stray.add(letter)
    for letter in sorted(stray, key=openpyxl.utils.column_index_from_string):
        found_warnings.append(f"Column {letter} has values but no heading: it is kept in the import record, "
                              "not imported.")  # fmt: skip

    return SourceSheet(
        name=sheet.title,
        sheet_names=names,
        header_row=header_row,
        group_row=group_row,
        columns=columns,
        header_items=_header_items(sheet, (group_row or header_row) - 1, max_column, merged),
        rows=rows,
        ignored_rows=ignored,
        warnings=found_warnings,
    )
