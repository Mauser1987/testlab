"""Manual log of a Test Run: configuration, calculated values, saving (M2A).

Entered: date/time of the observation, readings (measurements.py), collected
leakage volume, an optional event category and note and, when needed, the
leakage collection period. Known: who entered it (the logged-in user). Calculated, never typed:

* elapsed hours — clock time (stops and the static periods before and
  after running included) since t = 0 of the run: the start of its LabVIEW
  recording, whose time column starts at 0. Readings before the recording
  have negative values. Until a recording with a known start is imported,
  elapsed hours count from the first reading and are marked provisional;
* hours since the previous entry;
* leakage rate [ml/h] = collected volume / collection period, where the
  period is the clock time since the previous entry (legacy practice: the
  cup is emptied at every reading) unless the technician entered the
  period. Leakage is taken as logged, also when the shaft is not turning
  (static leakage): nothing is filtered on speed.

No rate is given — with the reason — for the first entry of a run without
an entered period, for a period of zero, or without a volume. Rates are
always derived from the stored values, so they follow corrections.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from .measurements import is_known, measurement, run_measurements
from .models import ManualLogEntry, ManualMeasurement


def run_setup(test_run):
    """The configuration the run is instructed with: its current TCN revision's setup."""
    return test_run.current_revision().setup


def log_columns(test_run, entries=()):
    """Measurements to show: the run's configuration, plus codes stored earlier that no longer apply."""
    setup = run_setup(test_run)
    columns = run_measurements(setup.arrangement, setup.plug_seal_present, setup.monitored_parameters)
    present = {m.code for m in columns}
    for entry in entries:
        for value in entry.measurements.all():
            if value.code not in present and is_known(value.code):
                columns.append(measurement(value.code, setup.arrangement))
                present.add(value.code)
    return columns


def instructed_codes(test_run):
    """Parameters the TCN instructs to log (its "Parameters to log")."""
    return set(run_setup(test_run).monitored_parameters)


@dataclass
class TimelineOrigin:
    at: object  # datetime of t = 0, or None
    dataset: object = None  # the DcsDataset whose recording start is t = 0

    @property
    def provisional(self):
        return self.dataset is None


def timeline_origin(test_run):
    """t = 0 of the run: the earliest known LabVIEW/DCS recording start."""
    dataset = (
        test_run.dcs_datasets.filter(recording_started_at__isnull=False).order_by("recording_started_at").first()
    )
    return TimelineOrigin(dataset.recording_started_at, dataset) if dataset else TimelineOrigin(None)


@dataclass
class Leakage:
    volume: Decimal | None
    hours: float | None  # collection period used
    period_source: str  # "entered", "since previous reading", ""
    rate: float | None  # ml/h
    note: str = ""  # why there is no rate


@dataclass
class LogRow:
    entry: ManualLogEntry
    values: dict  # code → ManualMeasurement
    elapsed_h: float
    since_previous_h: float | None
    leakage: dict  # code → Leakage


def _hours(delta):
    return delta.total_seconds() / 3600


def leakage_for(volume, entered_hours, since_previous_h):
    if entered_hours is not None:
        hours, source = float(entered_hours), "entered"
    elif since_previous_h is not None:
        hours, source = since_previous_h, "since previous reading"
    else:
        return Leakage(volume, None, "", None, "first reading: collection period unknown")
    if volume is None:
        return Leakage(None, hours, source, None)
    if hours <= 0:
        return Leakage(volume, hours, source, None, "collection period is zero")
    return Leakage(volume, hours, source, float(volume) / hours)


def log_rows(test_run, columns=None, origin=None):
    """Entries in time order with their calculated values; elapsed hours from `origin` (timeline_origin)."""
    entries = list(test_run.manual_log_entries.select_related("entered_by").prefetch_related("measurements"))
    if columns is None:
        columns = log_columns(test_run, entries)
    leakage_codes = [m.code for m in columns if m.is_leakage]
    origin = origin or timeline_origin(test_run)
    zero = origin.at or (entries[0].observed_at if entries else None)
    rows, previous = [], None
    for entry in entries:
        values = {value.code: value for value in entry.measurements.all()}
        since_previous = _hours(entry.observed_at - previous.observed_at) if previous else None
        leakage = {}
        for code in leakage_codes:
            value = values.get(code)
            if value is not None or entry.leakage_hours is not None:
                leakage[code] = leakage_for(value.value if value else None, entry.leakage_hours, since_previous)
        rows.append(LogRow(entry, values, _hours(entry.observed_at - zero), since_previous, leakage))
        previous = entry
    return rows


def save_entry(test_run, cleaned, columns, user, entry=None):
    """Create or update an entry from cleaned form data (values keyed by measurement code)."""
    with transaction.atomic():
        if entry is None:
            entry = ManualLogEntry(test_run=test_run, entered_by=user)
        entry.observed_at = cleaned["observed_at"]
        entry.note = cleaned["note"]
        entry.category = cleaned.get("category", "")
        entry.leakage_hours = cleaned["leakage_hours"]
        entry.updated_by = user
        entry.save()
        for column in columns:
            value = cleaned.get(column.code)
            if value is None:
                entry.measurements.filter(code=column.code).delete()
            else:
                ManualMeasurement.objects.update_or_create(
                    entry=entry, code=column.code, defaults={"value": value, "unit": column.unit}
                )
    return entry


def column_groups(columns):
    """[(group heading, [measurements])] in column order, for headings and form panels."""
    groups = []
    for column in columns:
        if groups and groups[-1][0] == column.group:
            groups[-1][1].append(column)
        else:
            groups.append((column.group, [column]))
    return groups
