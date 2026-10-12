"""Shaft-running intervals of a DCS recording: detected, reviewed, stored (DcsRunningDetermination).

A LabVIEW recording usually starts before the shaft turns and goes on after
it stops. The recording interval (the whole file) and the running
intervals (shaft genuinely rotating) are different things and both are
kept; the file and its elapsed-hours axis are never changed.

Detection (method "threshold-debounce", version 1) on the reviewed speed
signal (signal_mapping), every setting stored with the result:

1. a sample is running when speed ≥ threshold_rpm (default 50 rpm, a fixed
   value, never a share of the instructed speed);
2. missing data is not a stopped shaft: a step between two samples longer
   than the gap limit (max(2 min, 5 × the median sampling step)) splits
   the coverage; that time stays unknown;
3. between two running stretches, a dip below the threshold of at most
   max_dropout_s (default 60 s) is bridged — samples exist, the speed only
   fell briefly — and listed. It counts as running time; its samples,
   being below the threshold, are not shaft-running readings and stay out
   of the operating statistics (RunningState.statistic_spans);
4. a running stretch shorter than min_run_s (default 2 min) is ignored as
   a spike (noise while stopped) and listed;
5. a start or stop lies half-way between the last sample on one side of
   the threshold and the first on the other (the resolution is the
   sampling step); start-up and rundown samples at or above the threshold
   are inside the interval — no settling time, no at-speed filter;
6. every remaining stretch is a running interval of its own: a genuine
   standstill is never inside one. An interval at the first or last sample
   (or at a data gap) is flagged: its start or stop was not recorded.

Review: a detection is a convenience. Until an engineer confirms it, or
overrides the intervals with a reason, it is used provisionally (a Draft
says so) and a Result cannot be finalized. A determination goes stale when
the speed mapping is reviewed again after it; a changed speed signal gives
a new detection. Records are never edited: confirm, override and redetect
add a record and supersede the previous one.
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import median

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from . import datasets as dataset_store
from . import signal_mapping
from .models import DcsRunningDetermination

METHOD = "threshold-debounce"
METHOD_VERSION = 1

MIN_GAP_S = 120.0  # a step between samples longer than max(this, GAP_STEPS × median step) is missing data
GAP_STEPS = 5

# How an interval begins or ends.
CHANGE = "change"  # detected start-up / stop between two samples
RECORDING_START = "recording_start"  # already running at the first sample: start not recorded
RECORDING_END = "recording_end"  # still running at the last sample: stop not recorded
DATA_GAP = "data_gap"  # at missing data: the change is not recorded
ENTERED = "entered"  # set by an engineer (override)

EDGE_LABELS = {
    RECORDING_START: "already running when the recording started",
    RECORDING_END: "still running when the recording ended",
    DATA_GAP: "at a gap in the data",
}

Status = DcsRunningDetermination.Status


@dataclass(frozen=True)
class Settings:
    threshold_rpm: float
    max_dropout_s: float
    min_run_s: float


def default_settings():
    return Settings(
        django_settings.TESTLAB_RUNNING_SPEED_RPM,
        django_settings.TESTLAB_RUNNING_MAX_DROPOUT_S,
        django_settings.TESTLAB_RUNNING_MIN_RUN_S,
    )


def settings_of(determination):
    return Settings(determination.threshold_rpm, determination.max_dropout_s, determination.min_run_s)


# ---- detection (pure) ------------------------------------------------------------------------


@dataclass
class Detection:
    intervals: list = field(default_factory=list)  # [{"start_h", "end_h", "start_at", "end_at"}]
    coverage: list = field(default_factory=list)  # [[start_h, end_h]]: where samples say something
    gaps: list = field(default_factory=list)  # [[start_h, end_h]]: missing data
    dropouts: list = field(default_factory=list)  # bridged dips below the threshold
    spikes: list = field(default_factory=list)  # ignored short runs above it
    gap_limit_s: float = MIN_GAP_S

    def as_json(self):
        return {"intervals": self.intervals, "coverage": self.coverage, "gaps": self.gaps,
                "dropouts": self.dropouts, "spikes": self.spikes}  # fmt: skip


def gap_limit_s(times_h):
    steps = [b - a for a, b in zip(times_h, times_h[1:]) if b > a]
    return max(MIN_GAP_S, median(steps) * 3600 * GAP_STEPS) if steps else MIN_GAP_S


def _pieces(block, threshold):
    """[running, start_h, end_h] of each stretch of samples on one side of the threshold; a change is
    placed half-way between two samples, the block's own edges at its first and last sample."""
    pieces = []
    last = len(block) - 1
    for i, (t, v) in enumerate(block):
        running = v >= threshold
        start = t if i == 0 else (block[i - 1][0] + t) / 2
        end = t if i == last else (t + block[i + 1][0]) / 2
        if pieces and pieces[-1][0] == running:
            pieces[-1][2] = end
        else:
            pieces.append([running, start, end])
    return pieces


def detect(times_h, speeds, settings):
    """Running intervals of one recording (hours on its own axis). NaN samples are ignored."""
    samples = sorted((t, v) for t, v in zip(times_h, speeds) if not (math.isnan(t) or math.isnan(v)))
    found = Detection(gap_limit_s=gap_limit_s([t for t, _ in samples]))
    if not samples:
        return found
    limit_h = found.gap_limit_s / 3600
    blocks = [[samples[0]]]
    for previous, sample in zip(samples, samples[1:]):
        if sample[0] - previous[0] > limit_h:
            found.gaps.append([previous[0], sample[0]])
            blocks.append([sample])
        else:
            blocks[-1].append(sample)
    first_t, last_t = samples[0][0], samples[-1][0]
    for block in blocks:
        found.coverage.append([block[0][0], block[-1][0]])
        pieces = _pieces(block, settings.threshold_rpm)
        # 3. bridge brief dips between two running stretches (never at an edge of the coverage)
        runs = []  # [start, end, [dropouts]]
        for index, (running, start, end) in enumerate(pieces):
            inner = 0 < index < len(pieces) - 1
            if running or (inner and (end - start) * 3600 <= settings.max_dropout_s):
                if not running:
                    runs[-1][2].append([start, end])
                    runs[-1][1] = end
                elif runs and runs[-1][1] == start:
                    runs[-1][1] = end
                else:
                    runs.append([start, end, []])
        # 4. ignore short runs (spikes); 6. the rest are intervals
        for start, end, dropouts in runs:
            if (end - start) * 3600 < settings.min_run_s:
                found.spikes.append([start, end])
                continue
            found.dropouts.extend(dropouts)
            found.intervals.append({
                "start_h": start, "end_h": end,
                "start_at": CHANGE if start != block[0][0] else (RECORDING_START if start == first_t else DATA_GAP),
                "end_at": CHANGE if end != block[-1][0] else (RECORDING_END if end == last_t else DATA_GAP),
            })  # fmt: skip
    return found


def total_hours(intervals):
    return sum(i["end_h"] - i["start_h"] for i in intervals)


def clipped(intervals, coverage):
    """The parts of the intervals inside the coverage (missing data stays unknown)."""
    found = []
    for interval in intervals:
        for a, b in coverage:
            start, end = max(interval["start_h"], a), min(interval["end_h"], b)
            if end > start:
                found.append((start, end))
    return found


def without(spans, holes):
    """Sorted spans [(a, b)] minus the holes [[a, b]] (a sample exactly at a hole's edge stays in)."""
    found = []
    for a, b in spans:
        pieces = [(a, b)]
        for c, d in holes:
            cut = []
            for x, y in pieces:
                if d <= x or c >= y:
                    cut.append((x, y))
                    continue
                if c > x:
                    cut.append((x, c))
                if d < y:
                    cut.append((d, y))
            pieces = cut
        found.extend(pieces)
    return found


# ---- stored determinations -------------------------------------------------------------------


def speed_samples(dataset, column):
    data = dataset_store.load_columns(dataset)
    return list(data[dataset.time_column]), list(data[column])


def current(dataset):
    return dataset.running_determinations.filter(superseded_at__isnull=True).select_related("recorded_by").first()


def history(dataset):
    return list(dataset.running_determinations.select_related("recorded_by").order_by("-recorded_at", "-pk"))


def _new(dataset, column, detection, settings, status, user, now, effective=None, reason=""):
    signal = next((s for s in dataset.signals if s["column"] == column), {"name": "", "unit": ""})
    return DcsRunningDetermination(
        dataset=dataset, dataset_sha256=dataset.sha256,
        speed_column=column, speed_name=signal["name"], speed_unit=signal["unit"],
        mapping_reviewed_at=dataset.mapping_reviewed_at,
        method=METHOD, method_version=METHOD_VERSION,
        threshold_rpm=settings.threshold_rpm, max_dropout_s=settings.max_dropout_s, min_run_s=settings.min_run_s,
        gap_limit_s=detection.gap_limit_s, detected=detection.as_json(),
        effective_intervals=detection.intervals if effective is None else effective,
        status=status, reason=reason, recorded_by=user, recorded_at=now,
    )  # fmt: skip


def _detection(dataset, column, settings):
    return detect(*speed_samples(dataset, column), settings)


@dataclass
class RunningState:
    """The determination that applies to a dataset now, and whether it is provisional."""

    dataset: object
    determination: object  # DcsRunningDetermination, saved or (not determined yet) unsaved; None: no speed
    stale: str = ""  # why a confirmation no longer holds

    @property
    def saved(self):
        return self.determination is not None and self.determination.pk is not None

    @property
    def status(self):
        return self.determination.status if self.determination is not None else ""

    @property
    def provisional(self):
        return self.determination is not None and (
            not self.saved or self.stale or self.status == Status.DETECTED
        )

    @property
    def status_label(self):
        if self.determination is None:
            return "no reviewed speed signal"
        if self.stale:
            return "stale — confirm again"
        if not self.saved:
            return "detected, not saved"
        return {Status.DETECTED: "detected, not confirmed", Status.CONFIRMED: "confirmed",
                Status.OVERRIDDEN: "overridden"}[self.status]  # fmt: skip

    @property
    def intervals(self):
        return self.determination.effective_intervals if self.determination is not None else []

    @property
    def coverage(self):
        return self.determination.detected.get("coverage", []) if self.determination is not None else []

    @property
    def running_h(self):
        return sum(b - a for a, b in clipped(self.intervals, self.coverage))

    @property
    def statistic_spans(self):
        """Where samples count as shaft-running readings: the effective intervals inside the coverage, without
        the bridged dips (running time, but their samples are below the threshold, not running readings)."""
        dropouts = self.determination.detected.get("dropouts", []) if self.determination is not None else []
        return without(clipped(self.intervals, self.coverage), dropouts)

    @property
    def basis(self):
        d = self.determination
        if d is None:
            return ""
        unit = f" [{d.speed_unit}]" if d.speed_unit else ""
        return f"{d.speed_name}{unit} ≥ {d.threshold_rpm:g} rpm"

    @property
    def settings_text(self):
        d = self.determination
        return (f"{d.speed_name} ≥ {d.threshold_rpm:g} rpm; dips ≤ {d.max_dropout_s:g} s bridged; "
                f"runs < {d.min_run_s:g} s ignored; data gaps > {d.gap_limit_s:g} s unknown")  # fmt: skip


def state(dataset):
    """What applies now: the current determination, or a provisional detection not stored yet."""
    column = signal_mapping.mapped_column(dataset, "speed")
    if column is None:
        return RunningState(dataset, None)
    found = current(dataset)
    if found is not None and found.speed_column == column:
        stale = ""
        if found.mapping_reviewed_at != dataset.mapping_reviewed_at:
            stale = (f"the signal mapping was reviewed again "
                     f"({timezone.localtime(dataset.mapping_reviewed_at):%d-%b-%Y %H:%M}) after this determination")
        return RunningState(dataset, found, stale)
    settings = settings_of(found) if found is not None else default_settings()
    transient = _new(dataset, column, _detection(dataset, column, settings), settings, Status.DETECTED, None, None)
    return RunningState(dataset, transient, "the speed signal has changed" if found is not None else "")


class DeterminationError(Exception):
    """The running intervals cannot be recorded; the message says why."""


def _record(dataset, determination, now):
    with transaction.atomic():
        dataset.running_determinations.filter(superseded_at__isnull=True).update(superseded_at=now)
        determination.save()
    return determination


def ensure_current(dataset, user):
    """After a mapping review or an import: detect when there is no determination for the speed signal.

    A determination of the same speed signal is kept (it goes stale when the
    mapping was reviewed again); nothing is detected without a speed signal.
    """
    column = signal_mapping.mapped_column(dataset, "speed")
    if column is None:
        return None
    found = current(dataset)
    if found is not None and found.speed_column == column:
        return found
    settings = settings_of(found) if found is not None else default_settings()
    now = timezone.now()
    return _record(dataset, _new(dataset, column, _detection(dataset, column, settings), settings,
                                 Status.DETECTED, user, now), now)  # fmt: skip


def _shown(dataset, shown_pk):
    """The state the engineer acted on; refuses when it changed meanwhile."""
    found = state(dataset)
    if found.determination is None:
        raise DeterminationError("The dataset has no reviewed speed signal: map and review it first.")
    pk = found.determination.pk or ""
    if str(shown_pk or "") != str(pk):
        raise DeterminationError("The running intervals changed meanwhile; review them again.")
    return found


def _copy(source, status, user, now, effective=None, reason=""):
    copy = DcsRunningDetermination(
        **{f.name: getattr(source, f.name) for f in DcsRunningDetermination._meta.concrete_fields
           if f.name not in ("id", "status", "reason", "recorded_by", "recorded_at", "superseded_at",
                             "effective_intervals", "mapping_reviewed_at")},
    )  # fmt: skip
    copy.mapping_reviewed_at = source.dataset.mapping_reviewed_at
    copy.effective_intervals = source.effective_intervals if effective is None else effective
    copy.status, copy.reason, copy.recorded_by, copy.recorded_at = status, reason, user, now
    return copy


def confirm(dataset, user, shown_pk=None):
    """Accept the intervals shown. A stale override is confirmed as it stands (still overridden)."""
    found = _shown(dataset, shown_pk)
    if not found.provisional:
        raise DeterminationError("The running intervals are already confirmed.")
    source = found.determination
    status = Status.OVERRIDDEN if source.status == Status.OVERRIDDEN else Status.CONFIRMED
    now = timezone.now()
    return _record(dataset, _copy(source, status, user, now, reason=source.reason if status == Status.OVERRIDDEN
                                  else ""), now)  # fmt: skip


def validate_intervals(dataset, intervals):
    """[(start_h, end_h)] entered by an engineer → stored intervals; raises DeterminationError."""
    problems = []
    ordered = sorted(intervals)
    for start, end in ordered:
        if end <= start:
            problems.append(f"An interval must end after it starts ({start:.4f} h → {end:.4f} h).")
        elif start < dataset.time_start_h - 1e-9 or end > dataset.time_end_h + 1e-9:
            problems.append(f"{start:.4f} → {end:.4f} h is outside the recording "
                            f"({dataset.time_start_h:.4f} – {dataset.time_end_h:.4f} h).")  # fmt: skip
    for (a, b), (c, d) in zip(ordered, ordered[1:]):
        if c <= b:
            problems.append("Intervals overlap or touch; enter them as one interval.")
            break
    if problems:
        raise DeterminationError(" ".join(problems))
    return [{"start_h": a, "end_h": b, "start_at": ENTERED, "end_at": ENTERED} for a, b in ordered]


def override(dataset, intervals, reason, user, shown_pk=None):
    """Set the effective intervals; the detected ones stay stored beside them. A reason is required."""
    if not (reason or "").strip():
        raise DeterminationError("Give the reason for changing the running intervals.")
    effective = validate_intervals(dataset, intervals)
    source = _shown(dataset, shown_pk).determination
    now = timezone.now()
    return _record(dataset, _copy(source, Status.OVERRIDDEN, user, now, effective, reason.strip()), now)


def redetect(dataset, settings, user, reason="", shown_pk=None):
    """Detect again, e.g. with other settings; the earlier determinations stay in the history."""
    if settings.threshold_rpm <= 0 or settings.max_dropout_s < 0 or settings.min_run_s < 0:
        raise DeterminationError("The threshold must be above 0; the dropout and spike limits cannot be negative.")
    source = _shown(dataset, shown_pk).determination
    column = source.speed_column
    now = timezone.now()
    return _record(dataset, _new(dataset, column, _detection(dataset, column, settings), settings,
                                 Status.DETECTED, user, now, reason=(reason or "").strip()), now)  # fmt: skip


# ---- presentation helpers --------------------------------------------------------------------


def moment(dataset, hours):
    """The absolute time of an elapsed-hours value, or None without a recording start."""
    if dataset.recording_started_at is None:
        return None
    return dataset.recording_started_at + timedelta(hours=hours)


def edge_notes(interval):
    notes = []
    if interval.get("start_at") in EDGE_LABELS:
        notes.append(EDGE_LABELS[interval["start_at"]].replace("at a gap", "starts at a gap"))
    if interval.get("end_at") in EDGE_LABELS:
        notes.append(EDGE_LABELS[interval["end_at"]].replace("at a gap", "ends at a gap"))
    return notes
