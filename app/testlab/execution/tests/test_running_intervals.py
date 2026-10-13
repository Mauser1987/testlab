"""Shaft-running intervals of a DCS recording: detection, review, scope of the statistics (running_intervals.py)."""

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from decimal import Decimal

from django.utils import timezone

from testlab.documents.tests.report_data import png
from testlab.execution import datasets, manual_log, running_intervals, signal_mapping
from testlab.execution.models import DcsRunningDetermination
from testlab.execution.running_intervals import Settings, detect
from testlab.results import evidence, plots, runtime, services
from testlab.results.models import FinalResultError
from testlab.results.tests.helpers import make_run

from .test_labview import HEADER, NAME

pytestmark = pytest.mark.django_db

DEFAULTS = Settings(50, 60, 120)
STEP_S = 5
FIXTURE = Path(__file__).parent / "fixtures" / "run002_speed.tsv.gz"


def profile(*parts, step_s=STEP_S, start_s=0.0):
    """(times [h], speeds) sampled every step_s: parts = (seconds, rpm or f(i)) one after the other."""
    times, speeds = [], []
    t = start_s
    for seconds, speed in parts:
        for i in range(int(round(seconds / step_s))):
            times.append(t / 3600)
            speeds.append(speed(i) if callable(speed) else speed)
            t += step_s
    return times, speeds


def hours(*intervals):
    return [(round(i["start_h"] * 3600, 2), round(i["end_h"] * 3600, 2)) for i in intervals]


def noise(i):
    return [-5.7, 0.1, 3.2, -0.08, 5.9][i % 5]


# --- detection (pure) --------------------------------------------------------------------------


def test_recording_before_start_up_and_after_shutdown_is_not_running():
    """09:00 recording, 09:15 start, run, stop, recording continues: one interval, start and stop half-way."""
    times, speeds = profile((900, 0), (15, lambda i: [45, 2458, 5228][i]), (3000, 3000), (10, lambda i: [1500, 20][i]),
                            (600, 0))  # fmt: skip
    found = detect(times, speeds, DEFAULTS)
    # first sample ≥ 50 rpm at 905 s (2458): start half-way between 900 s (45 rpm) and 905 s; the last at 3915 s
    # (1500 rpm), the next below at 3920 s (20 rpm): stop at 3917.5 s
    assert hours(*found.intervals) == [(902.5, 3917.5)]
    assert found.intervals[0]["start_at"] == found.intervals[0]["end_at"] == running_intervals.CHANGE
    assert found.coverage == [[0.0, times[-1]]] and not (found.gaps or found.dropouts or found.spikes)


def test_noise_while_stopped_is_not_running():
    times, speeds = profile((1800, noise))
    found = detect(times, speeds, DEFAULTS)
    assert found.intervals == [] and found.spikes == []  # below the threshold: not even a spike


def test_an_isolated_spike_is_ignored_and_listed():
    times, speeds = profile((600, noise), (10, 900), (600, noise))
    found = detect(times, speeds, DEFAULTS)
    assert found.intervals == [] and hours(*[{"start_h": a, "end_h": b} for a, b in found.spikes]) == [(597.5, 607.5)]


def test_a_brief_dropout_is_bridged_and_listed():
    times, speeds = profile((600, 0), (1200, 3000), (30, 0), (1200, 3000), (600, 0))
    found = detect(times, speeds, DEFAULTS)
    assert hours(*found.intervals) == [(597.5, 3027.5)]  # one interval across the 30 s dip
    assert len(found.dropouts) == 1 and round((found.dropouts[0][1] - found.dropouts[0][0]) * 3600) == 30


def test_a_genuine_stop_gives_two_intervals_never_one_span_over_the_standstill():
    times, speeds = profile((600, 0), (1200, 3000), (600, 0), (1200, 3000), (600, 0))
    found = detect(times, speeds, DEFAULTS)
    assert hours(*found.intervals) == [(597.5, 1797.5), (2397.5, 3597.5)]
    assert found.dropouts == []


def test_multiple_running_intervals_with_restarts():
    parts = [(300, 0)]
    for _ in range(3):
        parts += [(900, 3000), (300, 0)]
    found = detect(*profile(*parts), DEFAULTS)
    assert len(found.intervals) == 3
    assert all(round((i["end_h"] - i["start_h"]) * 3600) == 900 for i in found.intervals)


def test_recording_beginning_and_ending_while_running_is_flagged():
    times, speeds = profile((1200, 3000))
    (interval,) = detect(times, speeds, DEFAULTS).intervals
    assert interval["start_at"] == running_intervals.RECORDING_START and interval["start_h"] == times[0]
    assert interval["end_at"] == running_intervals.RECORDING_END and interval["end_h"] == times[-1]


def test_missing_data_is_not_a_stopped_shaft_and_splits_the_coverage():
    a_times, a_speeds = profile((1200, 3000))
    b_times, b_speeds = profile((1200, 3000), start_s=1200 + 1800)  # 30 min without samples, still running
    found = detect(a_times + b_times, a_speeds + b_speeds, DEFAULTS)
    assert len(found.gaps) == 1 and found.dropouts == []  # the 60 s bridge applies to samples, never to a gap
    first, second = found.intervals
    assert first["end_at"] == second["start_at"] == running_intervals.DATA_GAP
    assert len(found.coverage) == 2


def test_settings_are_applied_as_given():
    times, speeds = profile((600, 0), (1200, 3000), (90, 0), (1200, 3000), (600, 0))
    assert len(detect(times, speeds, DEFAULTS).intervals) == 2  # 90 s > 60 s: a stop
    assert len(detect(times, speeds, Settings(50, 120, 120)).intervals) == 1
    assert detect(times, speeds, Settings(4000, 60, 120)).intervals == []


def test_run_002_regression():
    """The real export: 5 s sampling, ±6 rpm stopped noise, ramp 0 → 45 → 2458 → 5228 rpm, recording ends running."""
    lines = gzip.open(FIXTURE, "rt", encoding="ascii").read().splitlines()[2:]
    times = [float(line.split("\t")[0]) for line in lines]
    speeds = [float(line.split("\t")[1]) for line in lines]
    found = detect(times, speeds, DEFAULTS)
    (interval,) = found.intervals
    assert interval["start_h"] == pytest.approx(0.2374775) and interval["end_h"] == times[-1]
    assert interval["end_at"] == running_intervals.RECORDING_END
    inside = [v for t, v in zip(times, speeds) if interval["start_h"] <= t <= interval["end_h"]]
    assert (len(inside), min(inside), max(inside)) == (13947, 2457.53, 5625.241)  # 45 rpm is below 50 rpm


# --- stored determinations ---------------------------------------------------------------------

NAMES = "Time\tMotor Speed\t(X12) PT Barrier\tLBI temp\n"
UNITS = "Hrs\tRPM\tbarg\tC\n"


def export(times, speeds, barrier=None):
    """Barrier pressure 10 barg while stopped, 70–71 while running (pre-start values distort a full range)."""
    lines = []
    for i, (t, v) in enumerate(zip(times, speeds)):
        pressure = barrier(i, v) if barrier else (70 + (i % 11) / 10 if v >= 50 else 10)
        lines.append(f"{t:.6f}\t{v:.3f}\t{pressure:.3f}\t{40 + i * 0.01:.2f}\n")
    return (HEADER + NAMES + UNITS + "".join(lines)).encode("ascii")


STANDARD = profile((900, 0), (15, lambda i: [45, 2458, 2700][i]), (3600, lambda i: 2990 + i % 20), (10, 1200), (600, 0))


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


def imported(run, user, content=None):
    return datasets.import_dataset(run, SimpleUploadedFile(NAME, content or export(*STANDARD)), user)


def columns(dataset):
    return {s["name"]: s["column"] for s in dataset.value_signals()}


def review(dataset, user, speed="Motor Speed"):
    c = columns(dataset)
    chosen = {c[speed]: "speed", c["(X12) PT Barrier"]: "seal_support_pressure"}
    signal_mapping.review_mapping(dataset, chosen, set(), user)
    running_intervals.ensure_current(dataset, user)
    dataset.refresh_from_db()
    return dataset


@pytest.fixture
def dataset(run, user):
    return review(imported(run, user), user)


def timeline(run):
    rows = manual_log.log_rows(run)
    return runtime.build(run, rows, evidence.logged_period(run, rows))


def test_reviewing_the_speed_mapping_detects_and_stores_with_its_basis(dataset):
    found = running_intervals.current(dataset)
    assert found.status == "detected" and found.method == "threshold-debounce" and found.method_version == 1
    assert (found.threshold_rpm, found.max_dropout_s, found.min_run_s) == (50, 60, 120)
    assert (found.speed_name, found.speed_unit, found.dataset_sha256) == ("Motor Speed", "RPM", dataset.sha256)
    assert found.mapping_reviewed_at == dataset.mapping_reviewed_at
    assert hours(*found.effective_intervals) == [(902.5, 4522.5)]
    state = running_intervals.state(dataset)
    assert state.provisional and state.basis == "Motor Speed [RPM] ≥ 50 rpm"


def test_changed_defaults_do_not_alter_a_stored_determination(dataset, settings):
    before = running_intervals.current(dataset)
    settings.TESTLAB_RUNNING_SPEED_RPM = 2995
    settings.TESTLAB_RUNNING_MAX_DROPOUT_S = 0
    state = running_intervals.state(dataset)
    assert state.determination.pk == before.pk and state.determination.threshold_rpm == 50
    assert hours(*state.intervals) == [(902.5, 4522.5)]


def test_confirm_keeps_the_detection_and_the_history(dataset, user):
    detected = running_intervals.current(dataset)
    confirmed = running_intervals.confirm(dataset, user, detected.pk)
    detected.refresh_from_db()
    assert confirmed.status == "confirmed" and confirmed.recorded_by == user and confirmed.is_current
    assert detected.superseded_at is not None and detected.status == "detected"  # kept unchanged
    assert confirmed.effective_intervals == detected.effective_intervals
    assert not running_intervals.state(dataset).provisional
    with pytest.raises(running_intervals.DeterminationError, match="already confirmed"):
        running_intervals.confirm(dataset, user, confirmed.pk)


def test_an_override_needs_a_reason_and_keeps_the_detected_intervals(dataset, user):
    shown = running_intervals.current(dataset).pk
    with pytest.raises(running_intervals.DeterminationError, match="reason"):
        running_intervals.override(dataset, [(0.3, 1.0)], "  ", user, shown)
    with pytest.raises(running_intervals.DeterminationError, match="outside the recording"):
        running_intervals.override(dataset, [(0.3, 9.0)], "test", user, shown)
    with pytest.raises(running_intervals.DeterminationError, match="overlap"):
        running_intervals.override(dataset, [(0.3, 0.6), (0.5, 1.0)], "test", user, shown)
    found = running_intervals.override(dataset, [(0.5, 1.0), (0.3, 0.4)], "Run-in at low speed excluded", user, shown)
    assert found.status == "overridden" and found.reason == "Run-in at low speed excluded"
    assert [(i["start_h"], i["end_h"]) for i in found.effective_intervals] == [(0.3, 0.4), (0.5, 1.0)]
    assert hours(*found.detected["intervals"]) == [(902.5, 4522.5)]
    assert not running_intervals.state(dataset).provisional
    assert DcsRunningDetermination.objects.filter(dataset=dataset).count() == 2


def test_a_confirmation_goes_stale_when_the_mapping_is_reviewed_again(dataset, user):
    running_intervals.confirm(dataset, user, running_intervals.current(dataset).pk)
    review(dataset, user)  # same speed signal, reviewed again
    state = running_intervals.state(dataset)
    assert state.saved and state.stale.startswith("the signal mapping was reviewed again") and state.provisional
    running_intervals.confirm(dataset, user, state.determination.pk)
    assert not running_intervals.state(dataset).provisional


def test_a_changed_speed_signal_gives_a_new_detection(run, user):
    # LBI temp mapped as speed would be wrong; mapping another signal as speed redetects on that signal
    content = export(*STANDARD)
    dataset = review(imported(run, user, content), user)
    first = running_intervals.current(dataset)
    c = columns(dataset)
    signal_mapping.review_mapping(dataset, {c["(X12) PT Barrier"]: "speed"}, {c["(X12) PT Barrier"]}, user)
    running_intervals.ensure_current(dataset, user)
    dataset.refresh_from_db()
    second = running_intervals.current(dataset)
    assert second.pk != first.pk and second.speed_name == "(X12) PT Barrier" and second.status == "detected"
    first.refresh_from_db()
    assert first.superseded_at is not None


def test_redetect_with_other_settings_keeps_the_earlier_determination(dataset, user):
    earlier = running_intervals.current(dataset)
    found = running_intervals.redetect(dataset, Settings(2500, 60, 120), user, "ramp excluded", earlier.pk)
    assert found.threshold_rpm == 2500 and found.reason == "ramp excluded" and found.status == "detected"
    assert hours(*found.effective_intervals) == [(907.5, 4512.5)]  # 45 rpm and 1200 rpm samples outside
    assert len(running_intervals.history(dataset)) == 2
    with pytest.raises(running_intervals.DeterminationError, match="changed meanwhile"):
        running_intervals.confirm(dataset, user, earlier.pk)


def test_a_dataset_imported_in_a_reviewed_format_is_detected_on_import(run, user, dataset):
    again = imported(run, user)
    assert again.mapping_reviewed and running_intervals.current(again).status == "detected"


# --- timeline and statistics -------------------------------------------------------------------


def test_running_hours_come_from_the_effective_intervals(run, dataset, user):
    found = timeline(run)
    assert found.running_h == pytest.approx((4522.5 - 902.5) / 3600)
    assert found.unknown_h == pytest.approx(0) and found.provisional == [dataset]
    assert "provisional" in found.sources[0]
    running_intervals.confirm(dataset, user, running_intervals.current(dataset).pk)
    found = timeline(run)
    assert found.provisional == [] and "confirmed" in found.sources[0]


def test_a_data_gap_stays_unknown_on_the_run_timeline(run, user):
    a = profile((300, 0), (1200, 3000))
    b = profile((1200, 3000), (300, 0), start_s=1500 + 1800)  # 30 min without samples
    dataset = review(imported(run, user, export(a[0] + b[0], a[1] + b[1])), user)
    found = timeline(run)
    assert found.unknown_h == pytest.approx((3300 - 1495) / 3600)  # last sample before the gap → first after it
    assert found.running_h == pytest.approx((1495 - 297.5 + 4497.5 - 3300) / 3600)
    assert [i["end_at"] for i in running_intervals.current(dataset).effective_intervals] == ["data_gap", "change"]


def test_full_recording_versus_running_intervals_statistics(run, dataset):
    found = timeline(run)
    c = columns(dataset)
    full = evidence.dcs_statistics(dataset, c["Motor Speed"], evidence.Scope.FULL_RECORDING, found)
    running = evidence.dcs_statistics(dataset, c["Motor Speed"], evidence.Scope.RUNNING_INTERVALS, found)
    assert (full.minimum, full.maximum, full.scope) == (0, 3009, "full_recording")
    # transients at or above 50 rpm included (2458, 1200), the 45 rpm sample and the standstill not
    assert (running.minimum, running.maximum, running.scope, running.provisional) == (1200, 3009, "running_intervals", True)
    assert running.count == 2 + 720 + 2 and full.count == len(STANDARD[0])
    with pytest.raises(ValueError, match="not implemented"):
        evidence.dcs_statistics(dataset, c["Motor Speed"], "steady_state", found)


def test_a_bridged_dip_is_running_time_but_its_samples_are_not_running_readings(run, user):
    times, speeds = profile((300, 0), (1200, 3000), (30, 0), (1200, 3000), (300, 0))
    dataset = review(imported(run, user, export(times, speeds)), user)
    found = timeline(run)
    assert found.running_h == pytest.approx((2727.5 - 297.5) / 3600)  # the 30 s dip is running time
    speed = evidence.dcs_statistics(dataset, columns(dataset)["Motor Speed"], evidence.Scope.RUNNING_INTERVALS, found)
    assert (speed.minimum, speed.count) == (3000, 480)  # the six 0 rpm samples of the dip are not running readings


def test_the_same_scope_applies_to_a_non_speed_parameter(run, dataset):
    found = timeline(run)
    ranges = evidence.actual_ranges(run, manual_log.log_rows(run), manual_log.log_columns(run), found)
    (barrier,) = [r for r in ranges if r.measurement.code == "seal_support_pressure"]
    assert (barrier.minimum, barrier.maximum) == (70, 71)  # the 10 barg before start-up and after the stop: not in it
    assert barrier.full.minimum == 10 and barrier.scope == "running_intervals"
    assert barrier.source_label == "DCS · X12 PT Barrier" and barrier.source == f"DCS {NAME} › (X12) PT Barrier [barg]"
    assert barrier.provisional


def test_saved_plots_keep_their_own_time_range(run, dataset, user):
    result = services.create_result(run, user)
    definition = json.dumps({"signals": [{"column": 1, "axis": "y"}], "time_range": [0.0, 0.2], "caption": "Pre-start"})
    plot = plots.add_plot(result, dataset, definition, png(), user)
    stored = (plot.time_start_h, plot.time_end_h, plot.image.name)
    running_intervals.confirm(dataset, user, running_intervals.current(dataset).pk)
    plot.refresh_from_db()
    assert (plot.time_start_h, plot.time_end_h, plot.image.name) == stored == (0.0, 0.2, stored[2])


def test_manual_evidence_that_contradicts_the_dcs_is_listed(run, dataset, user):
    start = dataset.recording_started_at
    columns_ = manual_log.log_columns(run)
    blank = {"note": "", "category": "", "leakage_hours": None}
    manual_log.save_entry(run, {**blank, "observed_at": start + timedelta(minutes=40), "category": "stop"}, columns_, user)
    manual_log.save_entry(run, {**blank, "observed_at": start + timedelta(minutes=50), "speed": Decimal(0)}, columns_, user)
    manual_log.save_entry(run, {**blank, "observed_at": start + timedelta(minutes=3), "speed": Decimal(2980)}, columns_, user)
    manual_log.save_entry(run, {**blank, "observed_at": start + timedelta(minutes=23), "category": "stop"}, columns_, user)
    found = evidence.collect(run, None)["discrepancies"]
    messages = [d.message for d in found]
    assert len(messages) == 3, messages  # the Stop 8 min after the DCS start is within the margin: not listed
    assert "the DCS shows the shaft stopped" in messages[0]  # 12 min before the DCS start
    assert messages[1].startswith("Manual Stop event at") and "inside a DCS running interval" in messages[1]
    assert messages[2].startswith("Manual speed reading 0 rpm") and "below 50 rpm" in messages[2]


# --- viewer and lifecycle ----------------------------------------------------------------------


def test_viewer_shows_recording_running_and_actions(client, dataset, user):
    client.force_login(user)
    url = reverse("execution:dcs_detail", args=[dataset.pk])
    page = client.get(url).content.decode()
    assert "Running intervals" in page and "provisional" in page and "Motor Speed [RPM] ≥ 50 rpm" in page
    assert "Full recording" in page and 'id="dcs-running"' in page
    target = reverse("execution:dcs_running", args=[dataset.pk])
    shown = running_intervals.current(dataset).pk
    refused = client.post(target, {"action": "override", "determination": shown, "start_0": "0.3", "end_0": "0.9",
                                   "reason": ""})  # fmt: skip
    assert refused.status_code == 302 and running_intervals.current(dataset).pk == shown
    response = client.post(target, {"action": "confirm", "determination": shown})
    assert response.status_code == 302 and response["Location"].endswith("#running")
    assert running_intervals.current(dataset).status == "confirmed"
    page = client.get(url).content.decode()
    assert "History (1 earlier determination)" in page


def test_editing_through_the_viewer_keeps_unchanged_times_exact(client, dataset, user):
    client.force_login(user)
    page_context = client.get(reverse("execution:dcs_detail", args=[dataset.pk])).context
    (row, *_) = page_context["running_edit_rows"]
    shown = running_intervals.current(dataset).pk
    start = dataset.recording_started_at
    client.post(reverse("execution:dcs_running", args=[dataset.pk]), {
        "action": "override", "determination": shown, "reason": "Stop logged at 10:00 by the operator",
        "start_0": row["start"], "shown_start_0": row["start"], "start_h_0": row["start_h"],
        "end_0": timezone.localtime(start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "shown_end_0": row["end"], "end_h_0": row["end_h"],
        "start_1": "", "end_1": "",
    })  # fmt: skip
    found = running_intervals.current(dataset)
    assert found.status == "overridden", [str(m) for m in page_context["messages"]]
    (interval,) = found.effective_intervals
    assert interval["start_h"] == row["start_h"]  # unchanged: the stored value, not the display to the second
    assert interval["end_h"] == pytest.approx(1.0)


def test_redetect_through_the_viewer(client, dataset, user):
    client.force_login(user)
    client.post(reverse("execution:dcs_running", args=[dataset.pk]), {
        "action": "redetect", "determination": running_intervals.current(dataset).pk,
        "threshold_rpm": "100", "max_dropout_s": "30", "min_run_s": "300",
    })  # fmt: skip
    found = running_intervals.current(dataset)
    assert (found.threshold_rpm, found.max_dropout_s, found.min_run_s) == (100, 30, 300)


def test_finalization_waits_for_confirmed_running_intervals_and_freezes_them(user, file_storage):
    from testlab.results import finalization
    from testlab.results.tests.test_finalization import complete_result

    run, result = complete_result(user)
    dataset = review(imported(run, user), user)
    issues, _, _ = finalization.check(result, user)
    (issue,) = [i for i in issues if i.message.startswith("Running intervals of")]
    assert "detected only" in issue.message and issue.url.endswith(f"/dcs/{dataset.pk}/#running")
    with pytest.raises(finalization.FinalizationError, match="Running intervals"):
        finalization.finalize(result, user)
    running_intervals.confirm(dataset, user, running_intervals.current(dataset).pk)
    assert finalization.check(result, user)[0] == []
    final = finalization.finalize(result, user)
    from testlab.results import records

    record = records.read_record(final.revisions.get())
    (frozen,) = record["running"]["determinations"]
    assert frozen["status"] == "confirmed" and frozen["threshold_rpm"] == 50 and frozen["provisional"] is False
    assert frozen["speed_signal"]["name"] == "Motor Speed" and frozen["dataset_sha256"] == dataset.sha256
    assert [[round(a * 3600, 2), round(b * 3600, 2)] for a, b in frozen["effective_intervals"]] == [[902.5, 4522.5]]
    assert record["running"]["manual_threshold_rpm"] == 50
    assert record["identification"]["manual_threshold_rpm"] == "50"
    with pytest.raises(FinalResultError):
        running_intervals.redetect(dataset, DEFAULTS, user, "", running_intervals.current(dataset).pk)
    assert running_intervals.current(dataset).status == "confirmed"
