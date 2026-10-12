"""Is a workbook row already in the run's manual log? (M2F)

Rows and entries meet on the minute of their date/time (Excel logs whole
minutes; readings one minute apart are different observations, so only the
same minute counts):

* no entry in that minute: NEW (imported by default);
* an entry in that minute with the same measured values (the same codes,
  equal numbers; blank ≠ 0): POSSIBLE DUPLICATE (skipped by default). A
  different note is shown, it does not make the row new;
* an entry in that minute with any other content: CONFLICT. The engineer
  decides: skip, or import as an additional entry. An existing entry is
  never changed or replaced by an import.

Earlier rows of the same workbook count as entries too (a row logged
twice). A row with an error is ERROR, a row without values or note EMPTY.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from ..models import ManualLogImportRow
from .interpret import decimal_values, has_content

Classification = ManualLogImportRow.Classification


def minute(moment):
    return moment.replace(second=0, microsecond=0)


def _plain(number):
    return format(number.normalize(), "f") if number is not None else "—"


def _compare(values, note, other_values, other_note, labels):
    """(same values?, differences, note differs?)"""
    differences = []
    for code in sorted(set(values) | set(other_values)):
        mine, theirs = values.get(code), other_values.get(code)
        if mine is None or theirs is None or mine != theirs:
            differences.append({"code": code, "label": labels.get(code, code), "existing": _plain(theirs),
                                "imported": _plain(mine)})  # fmt: skip
    return not differences, differences, note.strip() != (other_note or "").strip()


def _describe(entry):
    if entry.source_row_id:
        row = entry.source_row
        return f"imported from {row.batch.original_name} row {row.sheet_row}"
    return "entered in TestLab"


def classify(test_run, rows, labels, exclude_batch=None):
    """{row.pk: (classification, matched entry or None, details)} for interpreted rows, in sheet order."""
    existing = defaultdict(list)
    entries = test_run.manual_log_entries.prefetch_related("measurements").select_related("source_row__batch")
    for entry in entries:
        if exclude_batch is not None and entry.source_row_id and entry.source_row.batch_id == exclude_batch.pk:
            continue
        existing[minute(entry.observed_at)].append(entry)
    earlier = defaultdict(list)
    found = {}
    for row in rows:
        data = row.interpreted
        if data.get("errors"):
            found[row.pk] = (Classification.ERROR, None, {})
            continue
        if not has_content(data):
            found[row.pk] = (Classification.EMPTY, None, {})
            continue
        at = minute(datetime.fromisoformat(data["observed_at"]))
        values, note = decimal_values(data), data["note"]
        result = None
        for entry in existing[at]:
            other = {m.code: Decimal(m.value) for m in entry.measurements.all()}
            same, differences, note_differs = _compare(values, note, other, entry.note, labels)
            details = {"entry": entry.pk, "observed_at": entry.observed_at.isoformat(), "source": _describe(entry),
                       "differences": differences, "note_differs": note_differs, "existing_note": entry.note,
                       "same_file": bool(entry.source_row_id and row.batch.sha256 == entry.source_row.batch.sha256)}
            if same and (values or not note_differs):
                result = (Classification.DUPLICATE, entry, details)
                break
            result = result or (Classification.CONFLICT, entry, details)
        if result is None or result[0] != Classification.DUPLICATE:
            for other_row, other_values, other_note in earlier[at]:
                same, differences, note_differs = _compare(values, note, other_values, other_note, labels)
                details = {"row": other_row, "source": f"row {other_row} of this workbook",
                           "differences": differences, "note_differs": note_differs, "existing_note": other_note}
                if same and (values or not note_differs):
                    result = (Classification.DUPLICATE, None, details)
                    break
                result = result or (Classification.CONFLICT, None, details)
        earlier[at].append((row.sheet_row, values, note))
        found[row.pk] = result or (Classification.NEW, None, {})
    return found


DEFAULT_DECISION = {
    Classification.NEW: ManualLogImportRow.Decision.IMPORT,
    Classification.DUPLICATE: ManualLogImportRow.Decision.SKIP,
    Classification.CONFLICT: "",  # the engineer decides
    Classification.ERROR: ManualLogImportRow.Decision.SKIP,
    Classification.EMPTY: ManualLogImportRow.Decision.SKIP,
}
