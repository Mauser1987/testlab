"""What the Result derives from the run's execution evidence (M2B).

Nothing here is stored: every figure is recalculated from the manual log and
the DCS datasets when shown, so it follows corrections and stays traceable
to the readings it comes from. Where the evidence does not support a value,
the value is None and is shown as "—" with the reason.

Leakage per seal (manual log):

* total collected [ml] — every volume logged for the seal;
* collection period [h] — the sum of the periods over which those volumes
  were collected (clock time since the previous reading, or the period the
  technician entered; manual_log.leakage_for);
* average leakage rate [ml/h] = Σ volume / Σ collection period, over the
  readings that have both. Never the mean of the interval rates: a long
  interval weighs more than a short one. A volume without a known period
  (the first reading of a run without an entered period) is reported but
  left out of the rate.

Per the M2A decision, leakage is taken as logged, static periods included,
and nothing is filtered on speed: the collection period is clock time, not
shaft-running time. Whether "total running hours" in the leakage rule must
exclude static periods is an open engineering question (README, M2B).

Face wear rate = (Pre − Post face length) / collection period of that seal:
in the legacy report the run time per seal (IB 22.25 h, OB 22.5 h) is the
period its leakage was collected over, and the wear rate 5.3E-6 in/h is
0.00012 in / 22.5 h. Open question as well; shown with its basis.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from testlab.execution import manual_log
from testlab.execution.measurements import LEAKAGE
from testlab.projects import conditions
from testlab.projects.arrangements import SealRole


@dataclass
class SealLeakage:
    position: str
    label: str  # e.g. "Inboard Seal"
    code: str  # manual log code, e.g. "inboard_leakage"
    total_volume: Decimal | None = None  # every logged volume; None: nothing logged
    rated_volume: Decimal = Decimal(0)  # volumes with a known collection period
    hours: float = 0.0  # Σ collection periods of those volumes
    intervals: int = 0
    unrated_volume: Decimal = Decimal(0)  # logged without a known period: not in the rate
    unrated_notes: list = field(default_factory=list)

    @property
    def average(self):
        """Σ volume / Σ period [ml/h], or None when no volume has a known period."""
        if not self.intervals or self.hours <= 0:
            return None
        return float(self.rated_volume) / self.hours

    @property
    def reason(self):
        if self.total_volume is None:
            return "no leakage logged"
        if self.average is None:
            return "no leakage volume with a known collection period"
        return ""


def leakage_summary(test_run, rows=None, columns=None):
    """Leakage per seal position logged in the manual log, in column order."""
    if columns is None:
        columns = manual_log.log_columns(test_run, list(test_run.manual_log_entries.prefetch_related("measurements")))
    if rows is None:
        rows = manual_log.log_rows(test_run, columns)
    summaries = []
    for column in columns:
        if column.kind != LEAKAGE:
            continue
        position = column.code.removesuffix("_leakage")
        seal = SealLeakage(position, SealRole(position).label, column.code)
        for row in rows:
            leak = row.leakage.get(column.code)
            if leak is None or leak.volume is None:
                continue
            seal.total_volume = (seal.total_volume or Decimal(0)) + leak.volume
            if leak.rate is not None:
                seal.rated_volume += leak.volume
                seal.hours += leak.hours
                seal.intervals += 1
            else:
                seal.unrated_volume += leak.volume
                seal.unrated_notes.append(f"{row.entry.observed_at:%d-%b-%Y %H:%M}: {leak.note}")
        summaries.append(seal)
    return summaries


@dataclass
class LoggedPeriod:
    start: object  # datetime or None
    end: object
    start_source: str
    end_source: str
    provisional: bool  # no LabVIEW recording start known: t = 0 is the first reading

    @property
    def hours(self):
        if self.start is None or self.end is None:
            return None
        return (self.end - self.start).total_seconds() / 3600


def logged_period(test_run, rows=None, origin=None):
    """From t = 0 of the run to the last evidence: the last reading or the end of a DCS recording.

    Clock time: stops and static periods are included. It is the span of the
    evidence, not shaft-running hours.
    """
    origin = origin or manual_log.timeline_origin(test_run)
    rows = manual_log.log_rows(test_run, origin=origin) if rows is None else rows
    start, start_source = origin.at, "start of the LabVIEW recording"
    if start is None and rows:
        start, start_source = rows[0].entry.observed_at, "first manual log reading (provisional)"
    ends = []
    if rows:
        ends.append((rows[-1].entry.observed_at, "last manual log reading"))
    for dataset in test_run.dcs_datasets.filter(recording_started_at__isnull=False):
        end = dataset.recording_started_at + timedelta(hours=dataset.time_end_h)
        ends.append((end, f"end of {dataset.original_name}"))
    end, end_source = max(ends, key=lambda pair: pair[0]) if ends else (None, "")
    return LoggedPeriod(start, end, start_source if start else "", end_source, origin.provisional)


# TCN fields holding the instructed value of a logged parameter (free text, unit printed by TestLab).
INSTRUCTED_FIELDS = {
    "speed": "speed",
    "process_pressure": "process_pressure",
    "process_inlet_temp": "process_inlet_temperature",
    "process_flow": "process_flow",
    "seal_support_pressure": "seal_support_pressure",
    "seal_support_inlet_temp": "seal_support_inlet_temperature",
    "seal_support_flow": "seal_support_flow",
}


@dataclass
class LoggedRange:
    measurement: object  # execution.measurements.Measurement
    instructed: str  # as on the TCN, with unit; "" when the TCN has no value for it
    count: int
    minimum: Decimal | None
    maximum: Decimal | None


def logged_ranges(test_run, rows, columns):
    """Min–max of every logged reading (not leakage), beside the TCN value where one exists.

    Shown side by side only: no deviation is judged here.
    """
    setup = manual_log.run_setup(test_run)
    ranges = []
    for column in columns:
        if column.kind == LEAKAGE:
            continue
        values = [row.values[column.code].value for row in rows if column.code in row.values]
        if not values:
            continue
        instructed = instructed_value(setup, column.code)
        if instructed:
            unit = conditions.field_unit(INSTRUCTED_FIELDS[column.code])
            instructed = f"{instructed} {unit}" if unit else instructed
        ranges.append(LoggedRange(column, instructed, len(values), min(values), max(values)))
    return ranges


def instructed_value(setup, code):
    """The TCN value of a logged parameter as typed (free text, no unit), or ""."""
    field_name = INSTRUCTED_FIELDS.get(code)
    return getattr(setup, field_name) if field_name else ""


def events(rows):
    """Manual log entries that record an event or observation (category or note), in time order."""
    return [row for row in rows if row.entry.category or row.entry.note.strip()]


@dataclass
class ComponentWear:
    component: object  # ResultComponent
    measurement: object  # InspectionMeasurement of a wear quantity
    wear: Decimal | None
    hours: float | None  # collection period of the seal
    hours_source: str

    @property
    def rate(self):
        if self.wear is None or not self.hours:
            return None
        return float(self.wear) / self.hours


def component_wear(components, leakage):
    """Wear and wear rate of every component with a wear quantity (face length) entered."""
    hours = {seal.position: seal for seal in leakage}
    found = []
    for component in components:
        for measurement in component.measurements.all():
            if not measurement.definition.wear:
                continue
            seal = hours.get(component.position)
            seal_hours = seal.hours if seal and seal.intervals else None
            source = f"{seal.label} leakage collection period" if seal_hours else "no collection period logged"
            found.append(ComponentWear(component, measurement, measurement.wear, seal_hours, source))
    return found


def collect(test_run, result):
    """Everything the Result derives from the run's evidence, computed once (Result page, report)."""
    entries = list(test_run.manual_log_entries.select_related("entered_by").prefetch_related("measurements"))
    columns = manual_log.log_columns(test_run, entries)
    origin = manual_log.timeline_origin(test_run)
    rows = manual_log.log_rows(test_run, columns, origin)
    leakage = leakage_summary(test_run, rows, columns)
    components = sorted(result.components.all(), key=lambda c: c.sort_key) if result else []
    return {
        "columns": columns,
        "origin": origin,
        "rows": rows,
        "leakage": leakage,
        "period": logged_period(test_run, rows, origin),
        "ranges": logged_ranges(test_run, rows, columns),
        "events": events(rows),
        "wear": component_wear(components, leakage),
        "components": components,
        "datasets": list(test_run.dcs_datasets.all()),
    }
