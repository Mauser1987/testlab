"""What the Result derives from the run's execution evidence (M2B, M2E).

Nothing here is stored: every figure is recalculated from the manual log and
the DCS datasets when shown, so it follows corrections and stays traceable
to the readings it comes from. Where the evidence does not support a value,
the value is None and is shown as "—" with the reason. Finalization freezes
what was shown (the report snapshot), not these functions.

Time (runtime.py): elapsed clock time of the logged period and
shaft-running hours are separate quantities; running hours come only from
evidence that says the shaft turned, unknown periods are never counted as
running.

Leakage per seal (manual log collections, manual_log.log_rows): every
collection is classified on the running timeline —

* dynamic: the shaft was running for the whole collection period;
* static: stopped for the whole period;
* mixed: running and stopped (static leakage cannot be separated): a
  mixed-period collection rate = volume / collection period, labelled as
  such, never called dynamic leakage;
* not used: running state unknown for part of the period, collection
  period unknown (first reading), or not measured (blank; an explicit 0
  is a measured zero).

Average dynamic leakage [ml/h] = Σ volumes of the dynamic collections /
Σ their running hours: numerator and denominator cover exactly the same
collection intervals. Never a mean of interval rates, and never partial
collections divided by the whole test's running time. The running hours
not covered by a dynamic collection are shown as coverage. Static
collections give a static rate the same way.

Face wear (seal faces, reported face length): Δ = Post − Pre as measured
(signed), and material loss = Pre − Post (a shorter face = material
removed). Wear rate = material loss / shaft-running hours between the Pre
and Post inspections (their measurement times when recorded, else the
whole running timeline of the run); unavailable while any of that period
has an unknown running state. Taper, roughness and flatness changes are
never wear.
"""

import bisect
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from testlab.execution import datasets as dataset_store
from testlab.execution import manual_log, running_intervals, signal_mapping
from testlab.execution.measurements import LEAKAGE
from testlab.execution.models import ManualLogEntry
from testlab.projects import conditions
from testlab.projects.arrangements import SealRole

from . import inspection, measurement_summary, runtime
from .inspection import Applicability, MeasurementKind

EPSILON_H = 1e-6  # hours; below this a share of a period is rounding, not evidence

DYNAMIC = "dynamic"
STATIC = "static"
MIXED = "mixed"
UNCLASSIFIED = "unclassified"
NO_PERIOD = "no_period"
NOT_MEASURED = "not_measured"
ZERO_PERIOD = "zero_period"

COLLECTION_LABELS = {
    DYNAMIC: "dynamic",
    STATIC: "static",
    MIXED: "mixed period",
    UNCLASSIFIED: "running state unknown",
    NO_PERIOD: "collection period unknown",
    NOT_MEASURED: "not measured",
    ZERO_PERIOD: "collection period zero",
}
COLLECTION_REASONS = {
    STATIC: "shaft stopped throughout: static leakage",
    MIXED: "running and stopped within the period: static leakage cannot be separated",
    UNCLASSIFIED: "running state unknown for part of the period",
    NO_PERIOD: "first reading: start of the collection period unknown",
    NOT_MEASURED: "blank reading: not measured",
    ZERO_PERIOD: "collection period is zero",
}


@dataclass
class Collection:
    """One leakage collection of one seal: volume over its period, classified on the timeline."""

    end: object  # datetime of the collection point
    start: object  # datetime, None when unknown
    hours: float | None
    period_source: str
    volume: Decimal | None  # None: not measured
    kind: str
    split: object = None  # runtime.Split of the period

    @property
    def rate(self):
        """Volume / collection period [ml/h] (a dynamic, static or mixed-period rate), or None."""
        if self.volume is None or not self.hours:
            return None
        return float(self.volume) / self.hours

    @property
    def label(self):
        return COLLECTION_LABELS[self.kind]

    @property
    def reason(self):
        return COLLECTION_REASONS.get(self.kind, "")


@dataclass
class SealLeakage:
    position: str
    label: str  # e.g. "Inboard Seal"
    code: str  # manual log code, e.g. "inboard_leakage"
    collections: list = field(default_factory=list)
    run_running_h: float | None = None  # shaft-running hours of the whole timeline

    def _of(self, kind):
        return [c for c in self.collections if c.kind == kind]

    @property
    def measured(self):
        return [c for c in self.collections if c.volume is not None]

    @property
    def total_volume(self):
        """Every measured volume; None: nothing measured."""
        measured = self.measured
        return sum((c.volume for c in measured), Decimal(0)) if measured else None

    @property
    def dynamic(self):
        return self._of(DYNAMIC)

    @property
    def dynamic_volume(self):
        return sum((c.volume for c in self.dynamic), Decimal(0))

    @property
    def dynamic_hours(self):
        return sum(c.hours for c in self.dynamic)

    @property
    def average(self):
        """Average dynamic leakage: Σ dynamic volumes / Σ their running hours [ml/h], or None."""
        if not self.dynamic or self.dynamic_hours <= 0:
            return None
        return float(self.dynamic_volume) / self.dynamic_hours

    @property
    def static(self):
        return self._of(STATIC)

    @property
    def static_volume(self):
        return sum((c.volume for c in self.static), Decimal(0))

    @property
    def static_hours(self):
        return sum(c.hours for c in self.static)

    @property
    def static_average(self):
        if not self.static or self.static_hours <= 0:
            return None
        return float(self.static_volume) / self.static_hours

    @property
    def mixed(self):
        return self._of(MIXED)

    @property
    def excluded(self):
        """Collections not in the dynamic average, with their reason (static and mixed ones included)."""
        return [c for c in self.collections if c.kind != DYNAMIC]

    @property
    def uncovered_running_h(self):
        """Running hours of the run not covered by a dynamic collection of this seal."""
        if self.run_running_h is None:
            return None
        return max(self.run_running_h - self.dynamic_hours, 0.0)

    @property
    def reason(self):
        if self.total_volume is None:
            return "no leakage measured"
        if self.average is None:
            return "no collection with the shaft running throughout a known collection period"
        return ""


def classify(leak, timeline):
    """Kind and running split of one manual-log collection (manual_log.Leakage)."""
    if leak.volume is None:
        return NOT_MEASURED, None
    if leak.hours is None or leak.start is None:
        return NO_PERIOD, None
    if leak.hours <= 0:
        return ZERO_PERIOD, None
    split = timeline.split(leak.start, leak.end) if timeline.known else runtime.Split(unknown=leak.hours)
    if split.unknown > EPSILON_H or not timeline.known:
        return UNCLASSIFIED, split
    if split.stopped <= EPSILON_H:
        return DYNAMIC, split
    if split.running <= EPSILON_H:
        return STATIC, split
    return MIXED, split


def leakage_summary(test_run, rows=None, columns=None, timeline=None):
    """Leakage per seal position logged in the manual log, in column order."""
    if columns is None:
        columns = manual_log.log_columns(test_run, list(test_run.manual_log_entries.prefetch_related("measurements")))
    if rows is None:
        rows = manual_log.log_rows(test_run, columns)
    if timeline is None:
        timeline = runtime.build(test_run, rows, logged_period(test_run, rows))
    summaries = []
    for column in columns:
        if column.kind != LEAKAGE:
            continue
        position = column.code.removesuffix("_leakage")
        seal = SealLeakage(position, SealRole(position).label, column.code, run_running_h=timeline.running_h)
        for row in rows:
            leak = row.leakage.get(column.code)
            if leak is None:
                continue
            kind, split = classify(leak, timeline)
            seal.collections.append(Collection(leak.end, leak.start, leak.hours, leak.period_source, leak.volume,
                                               kind, split))  # fmt: skip
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

    Elapsed clock time: stops and static periods are included. It is the
    span of the evidence, not shaft-running hours (runtime.py).
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


class Scope:
    """Which samples of a DCS signal a statistic covers; every statistic states its scope.

    Operating values (the actual ranges of the Result and the report) use
    RUNNING_INTERVALS. A steady-state scope (operating speed reached,
    transients excluded) is anticipated but deliberately not implemented.
    """

    FULL_RECORDING = "full_recording"  # every sample of the recording
    RUNNING_INTERVALS = "running_intervals"  # samples inside the effective running intervals (transients included)


SCOPE_LABELS = {
    Scope.FULL_RECORDING: "complete recording",
    Scope.RUNNING_INTERVALS: "shaft running",
}


@dataclass
class Stats:
    count: int
    minimum: object
    maximum: object
    scope: str = ""
    provisional: bool = False  # from running intervals not confirmed or overridden yet


def _stats(values, scope="", provisional=False):
    return Stats(len(values), min(values), max(values), scope, provisional) if values else None


@dataclass
class ActualRange:
    """Actual values of one logged parameter: shaft-running readings by default, stopped readings
    separately (a static summary), from one stated source. Not a steady-state range."""

    measurement: object  # execution.measurements.Measurement
    instructed: str  # as on the TCN, with unit; "" when the TCN has no value for it
    source: str  # "manual log" or "DCS <file> › <signal> [unit]"
    running: Stats | None
    stopped: Stats | None
    unknown_count: int  # readings at a time of unknown running state: in no summary
    source_label: str = ""  # compact: "DCS · X22 Process Syst Press", "Manual log"
    full: Stats | None = None  # DCS: the complete recording (scope full_recording), for reference
    provisional: bool = False  # running intervals not confirmed or overridden yet

    @property
    def scope(self):
        return Scope.RUNNING_INTERVALS

    # Compatibility with the M2B summary (shaft-running readings).
    @property
    def count(self):
        return self.running.count if self.running else 0

    @property
    def minimum(self):
        return self.running.minimum if self.running else None

    @property
    def maximum(self):
        return self.running.maximum if self.running else None


def _manual_state(row, timeline):
    speed = runtime._speed(row)
    if speed is not None:
        return runtime.RUNNING if speed >= runtime.threshold_rpm() else runtime.STOPPED
    return timeline.state_at(row.entry.observed_at)


def _samples(dataset, column):
    columns = dataset_store.load_columns(dataset)
    return sorted((t, v) for t, v in zip(columns[dataset.time_column], columns[column]) if t == t and v == v)


def _within(spans, t):
    """t inside one of the sorted, separate closed spans [(a, b)]."""
    index = bisect.bisect_right([a for a, _ in spans], t) - 1
    return index >= 0 and t <= spans[index][1]


def _dcs_values(dataset, column, timeline):
    """{state: [values]} of a DCS signal.

    A recording with running intervals of its own: inside an effective
    interval running (except the samples of a bridged dip below the
    threshold: in no summary), elsewhere stopped (every sample lies in its
    coverage).
    Another recording (no speed signal of its own): each sample placed on
    the run's timeline.
    """
    found = {runtime.RUNNING: [], runtime.STOPPED: [], runtime.UNKNOWN: []}
    samples = _samples(dataset, column)
    own = timeline.dcs.get(dataset.pk)
    if own is not None:
        spans = running_intervals.clipped(own.intervals, own.coverage)
        readings = own.statistic_spans
        for t, value in samples:
            if _within(readings, t):
                found[runtime.RUNNING].append(value)
            elif _within(spans, t):
                found[runtime.UNKNOWN].append(value)  # a bridged dip: running time, not a running reading
            else:
                found[runtime.STOPPED].append(value)
        return found
    start = dataset.recording_started_at
    running = [(s.start, s.end) for s in timeline.segments if s.state == runtime.RUNNING]
    for t, value in samples:
        moment = start + timedelta(hours=t)
        if _within(running, moment):
            state = runtime.RUNNING
        else:
            state = timeline.state_at(moment)
            state = runtime.UNKNOWN if state == runtime.RUNNING else state
        found[state].append(value)
    return found


def _dcs_provisional(dataset, timeline):
    own = timeline.dcs.get(dataset.pk)
    return own.provisional if own is not None else bool(timeline.provisional)


def dcs_statistics(dataset, column, scope, timeline):
    """Count, min and max of one DCS signal over a scope (Scope), stating the scope. Generic: any signal."""
    if scope == Scope.FULL_RECORDING:
        return _stats([v for _, v in _samples(dataset, column)], scope)
    if scope == Scope.RUNNING_INTERVALS:
        values = _dcs_values(dataset, column, timeline)[runtime.RUNNING]
        return _stats(values, scope, _dcs_provisional(dataset, timeline))
    raise ValueError(f"Statistics scope {scope!r} is not implemented")


def actual_ranges(test_run, rows, columns, timeline, datasets=None):
    """Actual min–max of every logged parameter (not leakage), beside the TCN value where one exists.

    Source: a reviewed DCS signal mapped to the parameter (continuous data)
    when there is one, else the manual readings. A DCS range covers the
    samples inside the running intervals (scope running_intervals: start-up
    and stop transients included, pre-start and post-stop recording not).
    Shown side by side only: no deviation is judged here, and the TCN value
    is never an acceptance limit.
    """
    setup = manual_log.run_setup(test_run)
    datasets = list(test_run.dcs_datasets.all()) if datasets is None else datasets
    ranges = []
    for column in columns:
        if column.kind == LEAKAGE:
            continue
        dataset = next((d for d in datasets if d.recording_started_at is not None
                        and signal_mapping.mapped_column(d, column.code) is not None), None)  # fmt: skip
        full, provisional = None, False
        if dataset is not None and timeline.known:
            mapped = signal_mapping.mapped_column(dataset, column.code)
            by_state = _dcs_values(dataset, mapped, timeline)
            source = f"DCS {signal_mapping.describe(dataset, column.code)}"
            label = f"DCS · {signal_mapping.short_name(dataset, column.code)}"
            full = dcs_statistics(dataset, mapped, Scope.FULL_RECORDING, timeline)
            provisional = _dcs_provisional(dataset, timeline)
        else:
            by_state = {runtime.RUNNING: [], runtime.STOPPED: [], runtime.UNKNOWN: []}
            for row in rows:
                if column.code in row.values:
                    by_state[_manual_state(row, timeline)].append(row.values[column.code].value)
            source, label = "manual log", "Manual log"
        if not any(by_state.values()):
            continue
        instructed = instructed_value(setup, column.code)
        if instructed:
            unit = conditions.field_unit(INSTRUCTED_FIELDS[column.code])
            instructed = f"{instructed} {unit}" if unit else instructed
        ranges.append(ActualRange(
            column, instructed, source,
            _stats(by_state[runtime.RUNNING], Scope.RUNNING_INTERVALS, provisional),
            _stats(by_state[runtime.STOPPED]), len(by_state[runtime.UNKNOWN]),
            source_label=label, full=full, provisional=provisional,
        ))  # fmt: skip
    return ranges


def instructed_value(setup, code):
    """The TCN value of a logged parameter as typed (free text, no unit), or ""."""
    field_name = INSTRUCTED_FIELDS.get(code)
    return getattr(setup, field_name) if field_name else ""


def events(rows):
    """Manual log entries that record an event or observation (category or note), in time order."""
    return [row for row in rows if row.entry.category or row.entry.note.strip()]


@dataclass
class Discrepancy:
    at: object  # datetime of the manual entry
    message: str


def discrepancies(rows, timeline, datasets):
    """Manual log entries that contradict the DCS running intervals: listed for review, never resolved.

    A Stop event or a speed reading below the manual threshold inside a DCS
    running interval, or a speed reading at or above it where the DCS shows
    the shaft stopped. Entries within TESTLAB_RUNNING_DISCREPANCY_MIN of a
    DCS start or stop are not listed (clocks and log times differ).
    """
    margin_h = settings.TESTLAB_RUNNING_DISCREPANCY_MIN / 60
    threshold = runtime.threshold_rpm()
    found = []
    for dataset in datasets:
        own = timeline.dcs.get(dataset.pk)
        if own is None or dataset.recording_started_at is None:
            continue
        spans = running_intervals.clipped(own.intervals, own.coverage)
        edges = [t for span in spans for t in span]
        for row in rows:
            t = (row.entry.observed_at - dataset.recording_started_at).total_seconds() / 3600
            if not any(a <= t <= b for a, b in own.coverage):
                continue
            if any(abs(t - edge) <= margin_h for edge in edges):
                continue
            running = _within(spans, t)
            when = timezone.localtime(row.entry.observed_at).strftime("%d-%b-%Y %H:%M")
            speed = runtime._speed(row)
            where = f"{dataset.original_name}"
            if running and row.entry.category == ManualLogEntry.Category.STOP:
                found.append(Discrepancy(row.entry.observed_at,
                                         f"Manual Stop event at {when} lies inside a DCS running interval ({where})."))
            if speed is not None and running and speed < threshold:
                found.append(Discrepancy(row.entry.observed_at, f"Manual speed reading {speed:g} rpm at {when} "
                                         f"(below {threshold:g} rpm) lies inside a DCS running interval ({where})."))
            if speed is not None and not running and speed >= threshold:
                found.append(Discrepancy(row.entry.observed_at, f"Manual speed reading {speed:g} rpm at {when} "
                                         f"lies where the DCS shows the shaft stopped ({where})."))
    return sorted(found, key=lambda d: d.at)


WEAR_DIRECTION = "Wear = Pre − Post face length (a shorter face is material removed)"


@dataclass
class ComponentWear:
    component: object  # ResultComponent (a seal face)
    pre: object  # reported DimensionalReading (face length), or None
    post: object
    delta: Decimal | None  # Post − Pre, signed, as measured
    loss: Decimal | None  # Pre − Post: material removed (negative: the face measured longer)
    split: object  # runtime.Split between the inspections, or None
    hours_source: str
    direction: str = WEAR_DIRECTION

    @property
    def unit(self):
        return (self.pre or self.post).unit

    @property
    def hours(self):
        """Shaft-running hours between the inspections."""
        return self.split.running if self.split is not None else None

    # Compatibility: "wear" is the material loss.
    @property
    def wear(self):
        return self.loss

    @property
    def rate(self):
        if self.loss is None or self.split is None or self.split.unknown > EPSILON_H or not self.hours:
            return None
        return float(self.loss) / self.hours

    @property
    def reason(self):
        if self.pre is not None and self.post is not None and self.pre.unit != self.post.unit:
            return f"Pre in {self.pre.unit}, Post in {self.post.unit}: not compared"
        if self.loss is None:
            return "Pre or Post face length missing"
        if self.split is None:
            return "no running timeline (no manual log or DCS data)"
        if self.split.unknown > EPSILON_H:
            return f"running state unknown for {self.split.unknown:.2f} h between the inspections"
        if not self.hours:
            return "no shaft-running hours between the inspections"
        return ""


def _measured_at(reading):
    return reading.measurement.measured_at if reading is not None else None


def component_wear(components, timeline):
    """Wear and wear rate of every seal face with a reported face length (measurement_summary)."""
    found = []
    for component in components:
        if not component.is_face:
            continue  # a sleeve or backing ring dimension has no wear meaning
        if component.applicability(MeasurementKind.DIMENSIONAL) == Applicability.NOT_APPLICABLE:
            continue
        pre, post = measurement_summary.reported_dimensional(component)
        if pre is None and post is None:
            continue
        values = (pre.value if pre else None, post.value if post else None)
        if pre is not None and post is not None and pre.unit != post.unit:
            values = (None, None)  # different units: not subtracted
        delta = inspection.delta(*values)
        loss = inspection.wear("face_length", *values)
        split, source = None, "no running timeline"
        if timeline.known:
            start, end = _measured_at(pre), _measured_at(post)
            split = timeline.split(start, end)
            if start or end:
                source = "shaft-running hours between the Pre and Post inspections"
            else:
                source = "shaft-running hours of the run (inspection times not recorded: Pre before, Post after)"
        found.append(ComponentWear(component, pre, post, delta, loss, split, source))
    return found


def collect(test_run, result):
    """Everything the Result derives from the run's evidence, computed once (Result page, report)."""
    entries = list(test_run.manual_log_entries.select_related("entered_by").prefetch_related("measurements"))
    columns = manual_log.log_columns(test_run, entries)
    origin = manual_log.timeline_origin(test_run)
    rows = manual_log.log_rows(test_run, columns, origin)
    period = logged_period(test_run, rows, origin)
    datasets = list(test_run.dcs_datasets.all())
    timeline = runtime.build(test_run, rows, period, datasets)
    leakage = leakage_summary(test_run, rows, columns, timeline)
    components = sorted(result.components.all(), key=lambda c: c.sort_key) if result else []
    return {
        "columns": columns,
        "origin": origin,
        "rows": rows,
        "leakage": leakage,
        "period": period,
        "timeline": timeline,
        "ranges": actual_ranges(test_run, rows, columns, timeline, datasets),
        "events": events(rows),
        "discrepancies": discrepancies(rows, timeline, datasets),
        "wear": component_wear(components, timeline),
        "components": components,
        "datasets": datasets,
    }
