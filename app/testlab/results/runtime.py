"""When the shaft was running (M2E): the run's timeline from its execution evidence.

Elapsed clock time and shaft-running hours are different quantities and
are always shown separately. Running hours are derived only from evidence
that says whether the shaft turned; a period nothing tells about is
unknown, never counted as running:

* DCS data — the running intervals of a recording with a reviewed speed
  signal and a known recording start (execution.running_intervals: a
  stored determination, detected and then confirmed or overridden by an
  engineer; until then used provisionally). Inside the recording's
  coverage the shaft runs in an effective interval and is stopped outside
  them; missing data (a sampling gap) is unknown, never stopped.
* Manual log — outside DCS coverage. Between two consecutive entries the
  state is known when both ends agree: running after a reading at or above
  the threshold (TESTLAB_RUNNING_SPEED_RPM, default 50 rpm) or a
  Start/restart event and, at the next entry, a reading at or above it or a
  Stop event; stopped the other way round. When the ends disagree (the
  change was not timed) or an end says nothing (no speed reading, no
  start/stop event) the interval is unknown.

Where both exist, DCS data decides; disagreements are listed for review
(evidence.discrepancies), never resolved silently. The timeline spans the
logged period (evidence.logged_period): t = 0 of the run, or the first
reading, to the last evidence. Before the first manual entry and outside
DCS coverage the state is unknown.
"""

import bisect
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings

from testlab.execution import running_intervals, signal_mapping
from testlab.execution.models import ManualLogEntry

RUNNING = "running"
STOPPED = "stopped"
UNKNOWN = "unknown"

STATE_LABELS = {RUNNING: "running", STOPPED: "stopped", UNKNOWN: "unknown"}

Category = ManualLogEntry.Category


def threshold_rpm():
    """Shaft running in the manual log: a speed reading at or above this [rpm]."""
    return settings.TESTLAB_RUNNING_SPEED_RPM


def _hours(delta):
    return delta.total_seconds() / 3600


@dataclass
class Segment:
    start: object  # datetime
    end: object
    state: str
    source: str  # "DCS …" / "manual log" / "" (unknown)

    @property
    def hours(self):
        return _hours(self.end - self.start)


@dataclass
class Split:
    running: float = 0.0
    stopped: float = 0.0
    unknown: float = 0.0

    @property
    def total(self):
        return self.running + self.stopped + self.unknown


@dataclass
class RunTimeline:
    start: object  # datetime or None (no evidence)
    end: object
    segments: list = field(default_factory=list)  # contiguous, start → end
    sources: list = field(default_factory=list)  # what the states come from
    notes: list = field(default_factory=list)  # why some evidence is not used
    dcs: dict = field(default_factory=dict)  # dataset pk → running_intervals.RunningState used
    manual_threshold_rpm: float | None = None  # the manual-log threshold applied

    @property
    def provisional(self):
        """Datasets whose running intervals are not confirmed or overridden (yet)."""
        return [s.dataset for s in self.dcs.values() if s.provisional]

    @property
    def known(self):
        return self.start is not None and self.end is not None

    def split(self, start=None, end=None):
        """Hours running / stopped / unknown between start and end (clipped to the timeline)."""
        found = Split()
        if not self.known:
            return found
        start = max(start or self.start, self.start)
        end = min(end or self.end, self.end)
        for segment in self.segments:
            a, b = max(segment.start, start), min(segment.end, end)
            if b > a:
                setattr(found, segment.state, getattr(found, segment.state) + _hours(b - a))
        if start < self.start:
            found.unknown += _hours(self.start - start)
        return found

    @property
    def totals(self):
        return self.split()

    @property
    def elapsed_h(self):
        return _hours(self.end - self.start) if self.known else None

    @property
    def running_h(self):
        return self.totals.running if self.known else None

    @property
    def stopped_h(self):
        return self.totals.stopped if self.known else None

    @property
    def unknown_h(self):
        return self.totals.unknown if self.known else None

    def state_at(self, moment):
        """State at a moment; at a boundary the segment that starts there."""
        if not self.known or moment < self.start or moment > self.end:
            return UNKNOWN
        starts = [segment.start for segment in self.segments]
        index = bisect.bisect_right(starts, moment) - 1
        return self.segments[index].state if index >= 0 else UNKNOWN

    def running_segments(self):
        return [s for s in self.segments if s.state == RUNNING]

    def running_spans(self):
        """Running periods of the run, whatever the source: [(start, end)], contiguous ones joined."""
        spans = []
        for segment in self.running_segments():
            if spans and spans[-1][1] == segment.start:
                spans[-1] = (spans[-1][0], segment.end)
            else:
                spans.append((segment.start, segment.end))
        return spans


def _paint(segments, start, end, state, source):
    """Overlay [start, end) with a state on a contiguous segment list."""
    if end <= start:
        return segments
    painted = []
    for segment in segments:
        if segment.end <= start or segment.start >= end:
            painted.append(segment)
            continue
        if segment.start < start:
            painted.append(Segment(segment.start, start, segment.state, segment.source))
        if segment.end > end:
            painted.append(Segment(end, segment.end, segment.state, segment.source))
    painted.append(Segment(start, end, state, source))
    painted.sort(key=lambda s: s.start)
    return painted


def _merged(segments):
    merged = []
    for segment in segments:
        if merged and merged[-1].state == segment.state and merged[-1].source == segment.source \
                and merged[-1].end == segment.start:  # fmt: skip
            merged[-1] = Segment(merged[-1].start, segment.end, segment.state, segment.source)
        else:
            merged.append(segment)
    return merged


# ---- manual log ------------------------------------------------------------------------------


def _speed(row):
    value = row.values.get("speed")
    return None if value is None else float(value.value)


def state_after(row):
    """What an entry says about the period after it, or None."""
    if row.entry.category == Category.STOP:
        return STOPPED
    if row.entry.category == Category.START:
        return RUNNING
    speed = _speed(row)
    if speed is None:
        return None
    return RUNNING if speed >= threshold_rpm() else STOPPED


def state_before(row):
    """What an entry says about the period before it, or None."""
    if row.entry.category == Category.STOP:
        return RUNNING
    if row.entry.category == Category.START:
        return STOPPED
    speed = _speed(row)
    if speed is None:
        return None
    return RUNNING if speed >= threshold_rpm() else STOPPED


def manual_segments(rows):
    found = []
    for a, b in zip(rows, rows[1:]):
        after, before = state_after(a), state_before(b)
        state = after if after is not None and after == before else UNKNOWN
        found.append(Segment(a.entry.observed_at, b.entry.observed_at, state, "manual log" if state != UNKNOWN else ""))
    return found


# ---- DCS -------------------------------------------------------------------------------------


def dcs_segments(dataset, found):
    """Segments of one recording from its running intervals (running_intervals.RunningState)."""
    start = dataset.recording_started_at
    source = f"DCS {dataset.original_name}"

    def at(hours):
        return start + timedelta(hours=hours)

    segments = []
    for a, b in found.coverage:
        segments.append(Segment(at(a), at(b), STOPPED, source))
    for a, b in running_intervals.clipped(found.intervals, found.coverage):
        segments = _paint(segments, at(a), at(b), RUNNING, source)
    return [s for s in segments if s.end > s.start]


# ---- timeline --------------------------------------------------------------------------------


def build(test_run, rows, period, datasets=None):
    """The run's timeline over the logged period (evidence.logged_period)."""
    timeline = RunTimeline(period.start, period.end, manual_threshold_rpm=threshold_rpm())
    if not timeline.known or period.end <= period.start:
        return RunTimeline(None, None, manual_threshold_rpm=threshold_rpm())
    segments = [Segment(period.start, period.end, UNKNOWN, "")]
    manual = manual_segments(rows)
    if manual:
        for segment in manual:
            segments = _paint(segments, segment.start, segment.end, segment.state, segment.source)
    sources = {}  # segment source → description, kept when the source decides some period in the end
    if any(s.state != UNKNOWN for s in manual):
        sources["manual log"] = (f"manual log (speed ≥ {threshold_rpm():g} rpm or start/stop events at both ends "
                                 "of an interval)")  # fmt: skip
    datasets = list(test_run.dcs_datasets.all()) if datasets is None else datasets
    for dataset in sorted(datasets, key=lambda d: d.recording_started_at or period.start):
        if not dataset.mapping_reviewed or signal_mapping.mapped_column(dataset, "speed") is None:
            timeline.notes.append(f"{dataset.original_name}: no reviewed speed signal, not used for running hours")
            continue
        if dataset.recording_started_at is None:
            timeline.notes.append(f"{dataset.original_name}: recording start unknown, not used for running hours")
            continue
        found = running_intervals.state(dataset)
        timeline.dcs[dataset.pk] = found
        painted = dcs_segments(dataset, found)
        for segment in painted:
            segments = _paint(segments, max(segment.start, period.start), min(segment.end, period.end),
                              segment.state, segment.source)  # fmt: skip
        if painted:
            label = "provisional" if found.provisional else found.status_label
            sources[painted[0].source] = (f"{signal_mapping.describe(dataset, 'speed')} (running intervals, "
                                          f"≥ {found.determination.threshold_rpm:g} rpm, {label})")  # fmt: skip
    timeline.segments = _merged([s for s in segments if s.end > s.start])
    deciding = {s.source for s in timeline.segments if s.state != UNKNOWN}
    timeline.sources = [text for key, text in sources.items() if key in deciding]
    return timeline


def describe_split(split):
    parts = [f"{split.running:.2f} h running"]
    if split.stopped:
        parts.append(f"{split.stopped:.2f} h stopped")
    if split.unknown:
        parts.append(f"{split.unknown:.2f} h unknown")
    return ", ".join(parts)
