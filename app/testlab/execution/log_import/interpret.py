"""What a workbook row says in manual-log terms, under a confirmed mapping (M2F).

Values are taken exactly as recorded:

* a number is the text stored in the workbook, kept to Excel's own
  precision of 15 significant digits (a stored 0.30000000000000004 is the
  0.3 Excel shows); it must fit the manual log's storage (4 decimals, as the
  entry form): otherwise the row is an error, never rounded;
* 0 is a reading; an empty cell is "not measured";
* a number typed as text ("80,5") is read as the entry form reads it and
  flagged; any other text, an Excel error or a formula without a stored
  result in a mapped measurement makes the row an error. An error row is
  never imported in part: it is skipped, or the workbook is corrected and
  imported again;
* the collection period ("Over [hours]"): a formula or an empty cell is
  the workbook's default (since the previous row) and is not imported;
  TestLab uses its own default, since the previous reading. A typed period
  is imported as entered. A typed 0 is not a period. When the periods of
  the leakages of one row disagree (one value per entry in TestLab) the
  engineer chooses;
* date and time are local lab time (TIME_ZONE); a time in a daylight-saving
  change (missing or doubled hour) is an error.
"""

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from django.utils import timezone

from .mapping import DATE, DATETIME, INTERVAL, NOTE, OPERATOR, TIME

EXCEL_DIGITS = 15
VALUE_MAX_DIGITS, VALUE_DECIMALS = 12, 4  # ManualMeasurement.value
PERIOD_MAX_DIGITS, PERIOD_DECIMALS = 8, 3  # ManualLogEntry.leakage_hours

_NUMBER_TEXT = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*$")
_DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"]
_TIME_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
_EXCEL_EPOCHS = {date(1899, 12, 30), date(1899, 12, 31), date(1900, 1, 1)}


class CellError(Exception):
    pass


def excel_decimal(text):
    """The number a workbook stores as `text`, to Excel's 15 significant digits."""
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise CellError(f"“{text}” is not a number") from error
    if not number.is_finite():
        raise CellError(f"“{text}” is not a number")
    with localcontext() as context:
        context.prec = EXCEL_DIGITS
        number = +number
    return Decimal(0) if number.is_zero() else number.normalize()


def fits(number, max_digits, decimals):
    _, digits, exponent = number.as_tuple()
    places = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    return places <= decimals and integer_digits <= max_digits - decimals


def plain(number):
    return format(number, "f")


def number_of(cell, ref, flags, max_digits=VALUE_MAX_DIGITS, decimals=VALUE_DECIMALS):
    """Decimal of a numeric cell; raises CellError. Flags what was read differently from a typed number."""
    kind = cell["k"]
    if kind == "number":
        number = excel_decimal(cell.get("raw") or cell["v"])
        if "f" in cell:
            flags.append({"cell": ref, "message": f"Formula result {plain(number)} (formula {cell['f']})."})
    elif kind == "text":
        match = _NUMBER_TEXT.match(cell["v"])
        if not match:
            raise CellError(f"“{cell['v']}” is not a number")
        number = excel_decimal(match.group(1).replace(",", "."))
        flags.append({"cell": ref, "message": f"Number stored as text “{cell['v'].strip()}”, read as {plain(number)}."})
    elif kind == "empty":
        raise CellError(f"formula {cell.get('f', '')} without a stored result")
    else:
        raise CellError(f"“{cell['v']}” ({kind}) is not a number")
    if not fits(number, max_digits, decimals):
        raise CellError(f"{plain(number)} has more decimals or digits than TestLab stores ({decimals} decimals)")
    return number


def _date_of(cell):
    kind = cell["k"]
    if kind in ("datetime", "date"):
        return datetime.fromisoformat(cell["v"])
    if kind == "text":
        for pattern in _DATE_FORMATS:
            try:
                return datetime.strptime(cell["v"].strip(), pattern)
            except ValueError:
                continue
    raise CellError(f"“{cell['v']}” is not a date")


def _time_of(cell):
    kind = cell["k"]
    if kind == "time":
        return time.fromisoformat(cell["v"])
    if kind == "datetime":
        value = datetime.fromisoformat(cell["v"])
        if value.date() in _EXCEL_EPOCHS:
            return value.time()
    if kind == "number":
        fraction = Decimal(cell.get("raw") or cell["v"])
        if 0 <= fraction < 1:
            seconds = int((fraction * 86400).to_integral_value())
            return (datetime.min + timedelta(seconds=seconds)).time()
    if kind == "duration":
        seconds = float(cell["v"])
        if 0 <= seconds < 86400:
            return (datetime.min + timedelta(seconds=round(seconds))).time()
    if kind == "text":
        match = _TIME_PATTERN.match(cell["v"])
        if match and int(match.group(1)) < 24 and int(match.group(2)) < 60:
            return time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    raise CellError(f"“{cell['v']}” is not a time")


def _whole_second(value):
    """Excel stores times as fractions of a day: 08:25:59.9999 is 08:26:00."""
    if value.microsecond >= 500000:
        value += timedelta(seconds=1)
    return value.replace(microsecond=0)


def aware(local):
    """Lab time as an aware datetime; a time that does not exist or exists twice (DST) is an error."""
    zone = timezone.get_current_timezone()
    first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise CellError(f"{local:%d-%m-%Y %H:%M} falls in a daylight-saving change (missing or repeated hour)")
    return first


def observed_at(cells, by_target, row_no):
    """The row's date/time from its Date+Time or Date-and-time columns; raises CellError (message with cell)."""
    if DATETIME in by_target:
        letter = by_target[DATETIME]
        cell = cells.get(letter)
        if cell is None:
            raise CellError(f"{letter}{row_no}: no date/time")
        try:
            value = _date_of(cell) if cell["k"] != "text" else _text_datetime(cell["v"])
            return aware(_whole_second(value))
        except CellError as error:
            raise CellError(f"{letter}{row_no}: {error}") from error
    date_letter, time_letter = by_target[DATE], by_target.get(TIME)
    date_cell = cells.get(date_letter)
    if date_cell is None:
        raise CellError(f"{date_letter}{row_no}: no date")
    try:
        day = _date_of(date_cell)
    except CellError as error:
        raise CellError(f"{date_letter}{row_no}: {error}") from error
    time_cell = cells.get(time_letter) if time_letter else None
    if time_cell is None:
        raise CellError(f"{time_letter}{row_no}: no time")
    try:
        return aware(_whole_second(datetime.combine(day.date(), _time_of(time_cell))))
    except CellError as error:
        raise CellError(f"{time_letter}{row_no}: {error}") from error


def _text_datetime(text):
    for pattern in _DATE_FORMATS:
        for clock in (" %H:%M", " %H:%M:%S"):
            try:
                return datetime.strptime(text.strip(), pattern + clock)
            except ValueError:
                continue
    raise CellError(f"“{text}” is not a date and time")


def _text_of(cell):
    return "" if cell is None or cell["k"] == "empty" else cell["v"]


def interpret(cells, row_no, mapping, codes):
    """{"observed_at", "values", "note", "operator", "intervals", "leakage_hours", "period_options",
    "errors", "flags"} of one row. mapping: {letter: target} of the confirmed mapping."""
    by_target = {target: letter for letter, target in mapping.items()}
    errors, flags, values, intervals = [], [], {}, {}
    result = {"observed_at": None, "values": values, "note": "", "operator": "", "intervals": intervals,
              "leakage_hours": None, "period_options": [], "errors": errors, "flags": flags}  # fmt: skip
    try:
        result["observed_at"] = observed_at(cells, by_target, row_no).isoformat()
    except CellError as error:
        message = str(error)
        cell_ref, _, text = message.partition(": ")
        errors.append({"cell": cell_ref, "message": text or message})
    if NOTE in by_target:
        result["note"] = _text_of(cells.get(by_target[NOTE])).strip()
    if OPERATOR in by_target:
        result["operator"] = _text_of(cells.get(by_target[OPERATOR])).strip()
    for letter, target in mapping.items():
        if target not in codes:
            continue
        cell = cells.get(letter)
        if cell is None or (cell["k"] == "empty" and "f" not in cell):
            continue  # not measured
        ref = f"{letter}{row_no}"
        try:
            values[target] = plain(number_of(cell, ref, flags))
        except CellError as error:
            errors.append({"cell": ref, "message": f"{codes[target].full_label}: {error}."})
    for letter, target in mapping.items():
        if not target.startswith(INTERVAL):
            continue
        code, ref, cell = target[len(INTERVAL):], f"{letter}{row_no}", cells.get(letter)
        if cell is None or "f" in cell or cell["k"] == "empty":
            intervals[code] = {"state": "default", "cell": ref}
            continue
        try:
            period = number_of(cell, ref, [], PERIOD_MAX_DIGITS, PERIOD_DECIMALS)
        except CellError as error:
            errors.append({"cell": ref, "message": f"Collection period: {error}."})
            continue
        if period < 0:
            errors.append({"cell": ref, "message": f"Collection period {plain(period)} h is negative."})
        elif period == 0:
            intervals[code] = {"state": "zero", "cell": ref}
            flags.append({"cell": ref, "message": "Typed 0 h collection period: not a period, not imported."})
        else:
            intervals[code] = {"state": "typed", "value": plain(period), "cell": ref}
    _resolve_period(result)
    return result


def _resolve_period(result):
    """One collection period for the entry from the typed periods of the leakages measured in the row."""
    intervals, values = result["intervals"], result["values"]
    measured = {code: state for code, state in intervals.items() if code in values}
    typed = {state["value"] for state in measured.values() if state["state"] == "typed"}
    unmeasured_typed = [s for c, s in intervals.items() if c not in values and s["state"] == "typed"]
    for state in unmeasured_typed:
        result["flags"].append({"cell": state["cell"], "message": "Collection period typed without a leakage "
                                                                  "volume: not used."})  # fmt: skip
    if not typed:
        return
    defaults = [s for s in measured.values() if s["state"] != "typed"]
    if len(typed) == 1 and not defaults:
        result["leakage_hours"] = typed.pop()
        return
    # The leakages of one row disagree: TestLab keeps one collection period per entry.
    result["period_options"] = sorted(typed, key=Decimal) + [""]
    cells = ", ".join(s["cell"] for s in measured.values())
    result["flags"].append({"cell": cells, "message": "The collection periods of this row's leakages differ: "
                                                      "choose the period for the entry."})  # fmt: skip


def has_content(interpreted):
    return bool(interpreted["values"] or interpreted["note"])


def decimal_values(interpreted):
    return {code: Decimal(text) for code, text in interpreted["values"].items()}
