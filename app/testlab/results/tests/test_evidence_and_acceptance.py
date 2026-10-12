"""Leakage, running hours and wear derived from execution evidence, and acceptance assessment (M2B, M2E)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from testlab.execution import manual_log
from testlab.execution.models import DcsDataset
from testlab.results import acceptance, evidence, runtime, services
from testlab.results.forms import AcceptanceItemForm
from testlab.results.models import AcceptanceItem, Assessment

from .helpers import START, face_length, log, make_run

pytestmark = pytest.mark.django_db

RUN = 2980  # rpm: shaft running
STOP = 0


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


def found(run):
    rows = manual_log.log_rows(run)
    period = evidence.logged_period(run, rows)
    timeline = runtime.build(run, rows, period)
    return rows, period, timeline


def timeline_of(run):
    return found(run)[2]


def seal(run, position):
    return next(s for s in evidence.leakage_summary(run) if s.position == position)


# --- running hours (runtime.py) ----------------------------------------------------------------


def test_elapsed_clock_time_and_running_hours_are_separate(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 10, speed=RUN)
    log(run, user, 12, category="stop", speed=RUN)  # last reading before the stop
    log(run, user, 20, category="start", speed=STOP)  # restarted after 8 h standstill
    log(run, user, 30, speed=RUN)
    timeline = timeline_of(run)
    assert timeline.elapsed_h == pytest.approx(30)
    assert timeline.running_h == pytest.approx(22) and timeline.stopped_h == pytest.approx(8)
    assert timeline.unknown_h == pytest.approx(0)


def test_an_untimed_change_of_state_is_unknown_never_running(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 5, speed=STOP)  # stopped some time between the readings: not timed
    log(run, user, 9, speed=STOP)
    log(run, user, 11, torque=7)  # no speed, no event: says nothing
    log(run, user, 12, speed=RUN)
    timeline = timeline_of(run)
    assert timeline.running_h == pytest.approx(0)
    assert timeline.stopped_h == pytest.approx(4)
    assert timeline.unknown_h == pytest.approx(8)  # 0→5 and 9→12


def test_no_running_evidence_gives_no_running_hours(run, user):
    log(run, user, 0, inboard_leakage=0)
    log(run, user, 5, inboard_leakage=3)
    timeline = timeline_of(run)
    assert timeline.running_h == 0 and timeline.unknown_h == pytest.approx(5)
    assert timeline.sources == []


# --- leakage (evidence.py) ---------------------------------------------------------------------


def test_average_dynamic_leakage_is_dynamic_volume_over_their_running_hours(run, user):
    log(run, user, 0, speed=RUN, inboard_leakage=5)  # first reading: collection period unknown
    log(run, user, 1, speed=RUN, inboard_leakage=10)  # 10 ml in 1 h → 10 ml/h
    log(run, user, 11, speed=RUN, inboard_leakage=50)  # 50 ml in 10 h → 5 ml/h
    ib = seal(run, "inboard")
    assert ib.total_volume == Decimal(65)  # every measured volume
    assert ib.dynamic_volume == Decimal(60) and ib.dynamic_hours == pytest.approx(11)
    assert ib.average == pytest.approx(60 / 11)  # 5.45 ml/h
    assert ib.average != pytest.approx((10 + 5) / 2)  # not the unweighted mean of interval rates
    (first,) = ib.excluded
    assert first.kind == evidence.NO_PERIOD and first.volume == Decimal(5)


def test_blank_is_not_measured_and_zero_is_a_measured_zero(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 2, speed=RUN, inboard_leakage=0, outboard_leakage=4)  # IB measured 0
    log(run, user, 4, speed=RUN, outboard_leakage=6)  # IB blank: not measured
    log(run, user, 6, speed=RUN, inboard_leakage=2, outboard_leakage=2)
    ib = seal(run, "inboard")
    assert [c.kind for c in ib.collections] == [evidence.DYNAMIC, evidence.NOT_MEASURED, evidence.DYNAMIC]
    # 0 ml over 2 h and 2 ml over 2 h; the unmeasured 2 h are in neither numerator nor denominator
    assert ib.dynamic_volume == Decimal(2) and ib.dynamic_hours == pytest.approx(4)
    assert ib.average == pytest.approx(0.5)
    assert ib.uncovered_running_h == pytest.approx(2)  # of 6 running hours
    zero_only = seal(run, "inboard").collections[0]
    assert zero_only.volume == Decimal(0) and zero_only.rate == 0


def test_partial_collections_are_not_divided_by_the_whole_runtime(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 1, speed=RUN, outboard_leakage=3)  # the only collection: 3 ml in 1 h
    log(run, user, 100, speed=RUN)  # 99 h more running, nothing collected
    ob = seal(run, "outboard")
    assert ob.average == pytest.approx(3)  # not 3 ml / 100 h
    assert ob.uncovered_running_h == pytest.approx(99)


def test_mixed_period_collection_is_reported_with_its_own_rate_never_as_dynamic(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 2, speed=RUN, category="stop", outboard_leakage=4)  # 0→2 running: dynamic
    log(run, user, 3, speed=STOP, category="start", outboard_leakage=0)  # 2→3 stopped: static
    log(run, user, 5, speed=RUN, outboard_leakage=9)  # 3→5 running: dynamic
    log(run, user, 6, speed=RUN, category="stop", outboard_leakage=2)  # 5→6 running: dynamic
    log(run, user, 8, speed=STOP, outboard_leakage=1)  # 6→8 stopped: static
    log(run, user, 9, speed=RUN, category="start", outboard_leakage=0)  # 8→9 stopped: static
    log(run, user, 9.5, speed=RUN, leakage_hours=Decimal("3"), outboard_leakage=6)  # 6.5→9.5: both
    ob = seal(run, "outboard")
    D, S, M = evidence.DYNAMIC, evidence.STATIC, evidence.MIXED
    assert [c.kind for c in ob.collections] == [D, S, D, D, S, S, M]
    assert ob.average == pytest.approx((4 + 9 + 2) / 5)  # dynamic collections only
    assert ob.static_average == pytest.approx(1 / 4)  # 1 ml over 4 h stopped
    (mixed,) = ob.mixed
    assert mixed.rate == pytest.approx(2)  # 6 ml / 3 h collection period, labelled mixed
    assert mixed.split.running == pytest.approx(0.5) and mixed.split.stopped == pytest.approx(2.5)


def test_collection_with_unknown_running_state_is_not_used(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 4, inboard_leakage=8)  # no speed at the reading: 0→4 unknown
    ib = seal(run, "inboard")
    assert [c.kind for c in ib.collections] == [evidence.UNCLASSIFIED]
    assert ib.average is None and "running throughout" in ib.reason


def test_unknown_collection_period_or_zero_denominator_gives_no_rate(run, user):
    log(run, user, 0, speed=RUN)
    ib = seal(run, "inboard")
    assert ib.total_volume is None and ib.average is None and ib.reason == "no leakage measured"
    log(run, user, 0, speed=RUN, inboard_leakage=2)  # same time as the previous reading: period zero
    ib = seal(run, "inboard")
    assert ib.total_volume == Decimal(2) and ib.average is None
    assert [c.kind for c in ib.collections] == [evidence.ZERO_PERIOD]


def test_entered_collection_period_is_used(run, user):
    log(run, user, 0, speed=RUN, outboard_leakage=1)
    log(run, user, 4, speed=RUN, outboard_leakage=6, leakage_hours=Decimal("0.5"))
    ob = seal(run, "outboard")
    assert ob.dynamic_hours == pytest.approx(0.5) and ob.average == pytest.approx(12)


def test_single_with_plug_seal_reports_test_and_plug_leakage(user):
    run = make_run(user, "single", plug_seal=True)
    log(run, user, 0, speed=RUN, test_leakage=0, plug_leakage=0)
    log(run, user, 2, speed=RUN, test_leakage=4, plug_leakage=10)
    summary = {s.label: s.average for s in evidence.leakage_summary(run)}
    assert summary == {"Plug Seal": pytest.approx(5), "Test Seal": pytest.approx(2)}


# --- logged period, actual ranges, events ------------------------------------------------------


def dataset(run, user, started_at, end_h):
    return DcsDataset.objects.create(
        test_run=run, raw_file="x", original_name="TCN001 export", size=1, sha256="0" * 64, imported_by=user,
        encoding="ascii", delimiter="\t", time_column=0, sample_count=2, time_start_h=0, time_end_h=end_h,
        recording_started_at=started_at,
    )


def test_logged_period_is_provisional_without_labview_and_spans_the_evidence(run, user):
    log(run, user, 0, speed=2950)
    log(run, user, 10, speed=2950)
    period = evidence.logged_period(run)
    assert period.provisional and period.hours == pytest.approx(10)
    dataset(run, user, START - timedelta(hours=1), end_h=24)
    period = evidence.logged_period(run)
    assert not period.provisional and period.start == START - timedelta(hours=1)
    assert period.hours == pytest.approx(24) and period.end_source == "end of TCN001 export"


def ranges_of(run):
    rows, period, timeline = found(run)
    columns = manual_log.log_columns(run)
    return {r.measurement.code: r for r in evidence.actual_ranges(run, rows, columns, timeline)}


def test_actual_ranges_default_to_shaft_running_readings(run, user):
    setup = run.current_revision().setup
    setup.seal_support_pressure = "70"
    setup.save()
    log(run, user, 0, speed=RUN, seal_support_pressure="69.5", seal_support_flow="13.2")
    log(run, user, 1, speed=RUN, seal_support_pressure="70.4", seal_support_flow="12.2")
    log(run, user, 2, speed=STOP, seal_support_pressure="80.5")  # stopped: kept, not in the running range
    ranges = ranges_of(run)
    pressure = ranges["seal_support_pressure"]
    assert (pressure.minimum, pressure.maximum, pressure.count) == (Decimal("69.5"), Decimal("70.4"), 2)
    assert pressure.stopped.count == 1 and pressure.stopped.maximum == Decimal("80.5")
    assert pressure.instructed == "70 barg" and pressure.source == "manual log"
    assert ranges["seal_support_flow"].instructed == "" and ranges["seal_support_flow"].count == 2


def test_static_test_has_only_a_stopped_summary(run, user):
    log(run, user, 0, speed=STOP, seal_support_pressure="70.1")
    log(run, user, 5, speed=STOP, seal_support_pressure="70.3")
    pressure = ranges_of(run)["seal_support_pressure"]
    assert pressure.running is None and pressure.count == 0
    assert (pressure.stopped.minimum, pressure.stopped.maximum) == (Decimal("70.1"), Decimal("70.3"))


def test_events_are_log_entries_with_a_category_or_note(run, user):
    log(run, user, 0, speed=2950)
    log(run, user, 24, category="adjustment", note="Cooling water flow reduced")
    log(run, user, 30, category="stop")
    log(run, user, 31, note="Abnormal noise at OB")
    events = evidence.events(manual_log.log_rows(run))
    assert [(r.entry.category, r.entry.note) for r in events] == [
        ("adjustment", "Cooling water flow reduced"), ("stop", ""), ("", "Abnormal noise at OB"),
    ]  # fmt: skip
    assert events[0].elapsed_h == pytest.approx(24)  # on the run timeline: ready for plot markers


# --- wear -----------------------------------------------------------------------------------


def legacy_ob_stator(run, user):
    """Legacy report: OB face length 1.25037 → 1.25025 in, OB run time 22.5 h, wear 5.3E-6 in/h."""
    result = services.create_result(run, user)
    stator = face_length(result, user, "OB Stator", "1.25037", "1.25025")
    log(run, user, 0, speed=RUN, outboard_leakage=0)
    log(run, user, 22.5, speed=RUN, outboard_leakage=2703)
    return result, stator


def wear_of(result, run):
    return evidence.component_wear(services.sorted_components(result), timeline_of(run))


def test_wear_rate_is_material_loss_over_running_hours(run, user):
    result, stator = legacy_ob_stator(run, user)
    (wear,) = wear_of(result, run)
    assert wear.component == stator
    assert wear.delta == Decimal("-0.00012")  # Post − Pre, signed, as measured
    assert wear.loss == Decimal("0.00012")  # Pre − Post: material removed
    assert "Pre − Post" in wear.direction
    assert wear.hours == pytest.approx(22.5)
    assert wear.rate == pytest.approx(5.33e-6, rel=1e-3)
    assert seal(run, "outboard").average == pytest.approx(120.13, rel=1e-3)  # 2703 ml / 22.5 h


def test_wear_rate_uses_running_hours_not_elapsed_time(run, user):
    result = services.create_result(run, user)
    face_length(result, user, "IB Rotor", "1.00010", "1.00000")
    log(run, user, 0, speed=RUN)
    log(run, user, 10, speed=RUN, category="stop")
    log(run, user, 30, speed=STOP, category="start")
    log(run, user, 40, speed=RUN)
    (wear,) = wear_of(result, run)
    assert wear.hours == pytest.approx(20) and wear.rate == pytest.approx(0.0001 / 20)


def test_wear_rate_is_unavailable_while_running_state_is_unknown(run, user):
    result = services.create_result(run, user)
    face_length(result, user, "IB Rotor", "1.00010", "1.00000")
    log(run, user, 0, speed=RUN)
    log(run, user, 10, torque=5)  # no speed: 0→10 unknown
    (wear,) = wear_of(result, run)
    assert wear.rate is None and "unknown" in wear.reason


def test_a_longer_face_is_negative_loss_not_hidden(run, user):
    result = services.create_result(run, user)
    face_length(result, user, "IB Rotor", "1.00000", "1.00002")
    log(run, user, 0, speed=RUN)
    log(run, user, 10, speed=RUN)
    (wear,) = wear_of(result, run)
    assert wear.delta == Decimal("0.00002") and wear.loss == Decimal("-0.00002")


def test_taper_and_roughness_changes_are_never_wear(run, user):
    from testlab.results import inspection

    assert inspection.wear("face_taper", Decimal(1), Decimal(2)) is None
    assert inspection.wear("roughness_ra", Decimal(1), Decimal(2)) is None
    assert inspection.wear("face_flatness", Decimal(1), Decimal(2)) is None
    assert inspection.wear("face_length", Decimal("1.0002"), Decimal("1.0000")) == Decimal("0.0002")


# --- acceptance -----------------------------------------------------------------------------


def item(result, user, **fields):
    values = {"criterion": "x", "basis": "manual", "updated_by": user, "result": result}
    values.update(fields)
    return AcceptanceItem.objects.create(**values)


def evaluate(result, run, it):
    rows, period, timeline = found(run)
    leakage = evidence.leakage_summary(run, rows, None, timeline)
    wear = evidence.component_wear(services.sorted_components(result), timeline)
    return acceptance.evaluate(it, acceptance.Evidence(leakage, wear, period, timeline))


def test_leakage_limit_is_assessed_from_the_dynamic_average(run, user):
    result, _ = legacy_ob_stator(run, user)
    passing = item(result, user, criterion="OB leakage", basis="leakage_rate", position="outboard",
                   comparison="<=", limit=Decimal("150"), unit="ml/h")
    e = evaluate(result, run, passing)
    assert e.actual == pytest.approx(120.13, rel=1e-3) and e.actual_text == "120.1 ml/h"
    assert (e.derived, e.effective, e.by) == (Assessment.PASS, Assessment.PASS, "calculated")
    failing = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("15"),
                   unit="ml/h")
    assert evaluate(result, run, failing).effective == Assessment.FAIL


def test_equivalent_units_are_converted_and_mass_rates_are_not(run, user):
    result, _ = legacy_ob_stator(run, user)
    cc = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("2"),
              unit="cc/min")  # 120 ml/h ≤ 2 cc/min = 120 cc/h?  120.13 > 120: Fail
    assert evaluate(result, run, cc).effective == Assessment.FAIL
    mass = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("150"),
                unit="g/h")
    e = evaluate(result, run, mass)
    assert e.missing and "not comparable" in e.note


def test_wear_rate_limit_from_the_legacy_report_fails(run, user):
    result, stator = legacy_ob_stator(run, user)
    it = item(result, user, criterion="OB Stator wear", basis="wear_rate", component=stator, comparison="<=",
              limit=Decimal("0.0000025"), unit="in/h")
    e = evaluate(result, run, it)
    assert e.effective == Assessment.FAIL and e.actual_text == "5.33E-6 in/h"
    assert e.requirement == "≤ 2.5E-6 in/h"
    in_mm = item(result, user, basis="wear_rate", component=stator, comparison="<=", limit=Decimal("0.0002"),
                 unit="mm/h")  # 5.33E-6 in/h = 1.35E-4 mm/h
    assert evaluate(result, run, in_mm).effective == Assessment.PASS


def test_engineer_assessment_overrides_and_is_kept_apart_from_the_calculation(run, user):
    result, _ = legacy_ob_stator(run, user)
    it = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("15"),
              unit="ml/h", assessment="not_applicable", remark="Run-in test, leakage not assessed")
    e = evaluate(result, run, it)
    assert (e.effective, e.by, e.derived) == (Assessment.NOT_APPLICABLE, "engineer", Assessment.FAIL)


def test_missing_assessment_is_not_an_explicit_not_evaluated(run, user):
    result = services.create_result(run, user)
    no_data = item(result, user, basis="leakage_rate", position="inboard", comparison="<=", limit=Decimal("15"),
                   unit="ml/h")
    e = evaluate(result, run, no_data)
    assert e.actual is None and e.missing and e.effective_label == "Not assessed"
    assert e.source == "no leakage measured"
    visual = item(result, user, criterion="Face condition", requirement_text="No damage", actual_text="No damage")
    assert evaluate(result, run, visual).missing
    visual.assessment = Assessment.NOT_EVALUATED
    e = evaluate(result, run, visual)
    assert not e.missing and e.effective == Assessment.NOT_EVALUATED and e.by == "engineer"


def test_test_duration_is_assessed_on_running_hours(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 60, speed=RUN, category="stop")
    log(run, user, 74, speed=STOP, category="start")
    log(run, user, 90, speed=RUN)
    result = services.create_result(run, user)
    running = item(result, user, criterion="Duration", basis="running_hours", comparison=">=", limit=Decimal("72"),
                   unit="h")
    e = evaluate(result, run, running)
    assert e.actual == pytest.approx(76) and e.effective == Assessment.PASS
    elapsed = item(result, user, criterion="Elapsed", basis="logged_hours", comparison=">=", limit=Decimal("100"),
                   unit="h")  # explicitly elapsed: 90 h of clock time
    e = evaluate(result, run, elapsed)
    assert e.actual == pytest.approx(90) and e.effective == Assessment.FAIL


def test_running_hours_shortfall_with_unknown_periods_is_not_a_fail(run, user):
    log(run, user, 0, speed=RUN)
    log(run, user, 60, speed=RUN)
    log(run, user, 80, torque=5)  # 60→80 unknown: may have been running
    result = services.create_result(run, user)
    it = item(result, user, basis="running_hours", comparison=">=", limit=Decimal("72"), unit="h")
    e = evaluate(result, run, it)
    assert e.actual == pytest.approx(60) and e.missing and "could change the result" in e.note
    enough = item(result, user, basis="running_hours", comparison=">=", limit=Decimal("50"), unit="h")
    assert evaluate(result, run, enough).effective == Assessment.PASS  # known hours alone suffice


def form(result, **data):
    values = {"criterion": "OB leakage", "basis": "leakage_rate", "position": "outboard", "comparison": "<=",
              "limit": "15", "unit": "", "requirement_text": "", "actual_text": "", "assessment": "", "remark": ""}
    values.update(data)
    instance = AcceptanceItem(result=result, updated_by=result.created_by)
    return AcceptanceItemForm(values, instance=instance, result=result, positions=["inboard", "outboard"])


def test_form_defaults_the_unit_of_a_calculated_actual_and_requires_its_subject(run, user):
    result = services.create_result(run, user)
    f = form(result)
    assert f.is_valid(), f.errors
    saved = f.save()
    assert saved.unit == "ml/h" and saved.limit == Decimal("15")
    assert form(result, unit="cc/h").is_valid()  # converted when assessed
    assert "position" in form(result, position="").errors
    assert "component" in form(result, basis="wear_rate", position="").errors
    assert "actual_text" in form(result, actual_text="12 ml/h").errors  # calculated, not typed


def test_form_accepts_scientific_limits_and_requires_a_requirement(run, user):
    result = services.create_result(run, user)
    stator = next(c for c in result.components.all() if c.label == "OB Stator")
    f = form(result, basis="wear_rate", position="", component=str(stator.pk), limit="2,5E-6")
    assert f.is_valid(), f.errors
    assert f.cleaned_data["limit"] == Decimal("0.0000025")
    bare = form(result, basis="manual", position="", comparison="", limit="")
    assert "requirement_text" in bare.errors
    assert "comparison" in form(result, comparison="").errors  # a limit needs ≤ or ≥
