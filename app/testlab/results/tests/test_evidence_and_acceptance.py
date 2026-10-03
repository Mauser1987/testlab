"""Leakage/wear derived from execution evidence, and acceptance assessment (M2B)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from testlab.execution.models import DcsDataset
from testlab.results import acceptance, evidence, services
from testlab.results.forms import AcceptanceItemForm
from testlab.results.models import AcceptanceItem, Assessment

from .helpers import START, log, make_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


def seal(run, position):
    return next(s for s in evidence.leakage_summary(run) if s.position == position)


# --- leakage -----------------------------------------------------------------------------


def test_overall_average_is_total_volume_over_total_hours_not_mean_of_rates(run, user):
    log(run, user, 0, inboard_leakage=5)  # first reading: collection period unknown
    log(run, user, 1, inboard_leakage=10)  # 10 ml in 1 h  → 10 ml/h
    log(run, user, 11, inboard_leakage=50)  # 50 ml in 10 h → 5 ml/h
    ib = seal(run, "inboard")
    assert ib.total_volume == Decimal(65)  # everything logged
    assert ib.rated_volume == Decimal(60) and ib.hours == pytest.approx(11) and ib.intervals == 2
    assert ib.average == pytest.approx(60 / 11)  # 5.45 ml/h
    assert ib.average != pytest.approx((10 + 5) / 2)  # not the unweighted 7.5 ml/h
    assert ib.unrated_volume == Decimal(5) and "collection period unknown" in ib.unrated_notes[0]


def test_entered_collection_period_is_used(run, user):
    log(run, user, 0, outboard_leakage=1)
    log(run, user, 4, outboard_leakage=6, leakage_hours=Decimal("0.5"))
    ob = seal(run, "outboard")
    assert ob.hours == pytest.approx(0.5) and ob.average == pytest.approx(12)


def test_no_leakage_logged_gives_no_value(run, user):
    log(run, user, 0, speed=2950)
    ib = seal(run, "inboard")
    assert ib.total_volume is None and ib.average is None and ib.reason == "no leakage logged"
    log(run, user, 0, inboard_leakage=2)  # same time as the previous reading: period zero
    ib = seal(run, "inboard")
    assert ib.total_volume == Decimal(2) and ib.average is None and ib.unrated_volume == Decimal(2)


def test_single_with_plug_seal_reports_test_and_plug_leakage(user):
    run = make_run(user, "single", plug_seal=True)
    log(run, user, 0, test_leakage=0, plug_leakage=0)
    log(run, user, 2, test_leakage=4, plug_leakage=10)
    summary = {s.label: s.average for s in evidence.leakage_summary(run)}
    assert summary == {"Plug Seal": pytest.approx(5), "Test Seal": pytest.approx(2)}


# --- logged period, ranges, events ---------------------------------------------------------


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


def test_logged_ranges_show_min_max_beside_the_tcn_value(run, user):
    setup = run.current_revision().setup
    setup.seal_support_pressure = "70"
    setup.save()
    log(run, user, 0, seal_support_pressure="69.5", seal_support_flow="13.2")
    log(run, user, 1, seal_support_pressure="70.4", seal_support_flow="12.2")
    from testlab.execution import manual_log

    columns = manual_log.log_columns(run)
    ranges = {r.measurement.code: r for r in evidence.logged_ranges(run, manual_log.log_rows(run, columns), columns)}
    assert (ranges["seal_support_pressure"].minimum, ranges["seal_support_pressure"].maximum) == (
        Decimal("69.5"), Decimal("70.4"),
    )  # fmt: skip
    assert ranges["seal_support_pressure"].instructed == "70 barg"
    assert ranges["seal_support_flow"].instructed == "" and ranges["seal_support_flow"].count == 2


def test_events_are_log_entries_with_a_category_or_note(run, user):
    from testlab.execution import manual_log

    log(run, user, 0, speed=2950)
    log(run, user, 24, category="adjustment", note="Cooling water flow reduced")
    log(run, user, 30, category="stop")
    log(run, user, 31, note="Abnormal noise at OB")
    found = evidence.events(manual_log.log_rows(run))
    assert [(r.entry.category, r.entry.note) for r in found] == [
        ("adjustment", "Cooling water flow reduced"), ("stop", ""), ("", "Abnormal noise at OB"),
    ]  # fmt: skip
    assert found[0].elapsed_h == pytest.approx(24)  # on the run timeline: ready for plot markers


# --- wear -----------------------------------------------------------------------------------


def legacy_ob_stator(run, user):
    """Legacy report: OB face length 1.25037 → 1.25025 in, OB run time 22.5 h, wear 5.3E-6 in/h."""
    result = services.create_result(run, user)
    stator = next(c for c in result.components.all() if c.label == "OB Stator")
    services.save_measurements(result, {(stator.pk, "face_length"): (Decimal("1.25037"), Decimal("1.25025"))}, user)
    log(run, user, 0, outboard_leakage=0)
    log(run, user, 22.5, outboard_leakage=2703)
    return result, stator


def test_wear_rate_is_wear_over_the_seal_collection_period(run, user):
    result, stator = legacy_ob_stator(run, user)
    wear = evidence.component_wear(services.sorted_components(result), evidence.leakage_summary(run))
    assert len(wear) == 1 and wear[0].component == stator
    assert wear[0].wear == Decimal("0.00012") and wear[0].hours == pytest.approx(22.5)
    assert wear[0].rate == pytest.approx(5.33e-6, rel=1e-3)
    assert seal(run, "outboard").average == pytest.approx(120.13, rel=1e-3)  # 2703 ml / 22.5 h


# --- acceptance -----------------------------------------------------------------------------


def item(result, user, **fields):
    values = {"criterion": "x", "basis": "manual", "updated_by": user, "result": result}
    values.update(fields)
    return AcceptanceItem.objects.create(**values)


def evaluate(result, run, it):
    leakage = evidence.leakage_summary(run)
    found = acceptance.Evidence(
        leakage, evidence.component_wear(services.sorted_components(result), leakage), evidence.logged_period(run)
    )
    return acceptance.evaluate(it, found)


def test_leakage_limit_is_assessed_from_the_calculated_average(run, user):
    result, _ = legacy_ob_stator(run, user)
    passing = item(result, user, criterion="OB leakage", basis="leakage_rate", position="outboard",
                   comparison="<=", limit=Decimal("150"), unit="ml/h")
    e = evaluate(result, run, passing)
    assert e.actual == pytest.approx(120.13, rel=1e-3) and e.actual_text == "120.1 ml/h"
    assert (e.derived, e.effective, e.by) == (Assessment.PASS, Assessment.PASS, "calculated")
    failing = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("15"),
                   unit="ml/h")
    assert evaluate(result, run, failing).effective == Assessment.FAIL


def test_wear_rate_limit_from_the_legacy_report_fails(run, user):
    result, stator = legacy_ob_stator(run, user)
    it = item(result, user, criterion="OB Stator wear", basis="wear_rate", component=stator, comparison="<=",
              limit=Decimal("0.0000025"), unit="in/h")
    e = evaluate(result, run, it)
    assert e.effective == Assessment.FAIL and e.actual_text == "5.33E-6 in/h"
    assert e.requirement == "≤ 2.5E-6 in/h"


def test_engineer_assessment_overrides_and_is_kept_apart_from_the_calculation(run, user):
    result, _ = legacy_ob_stator(run, user)
    it = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("15"),
              unit="ml/h", assessment="not_applicable", remark="Run-in test, leakage not assessed")
    e = evaluate(result, run, it)
    assert (e.effective, e.by, e.derived) == (Assessment.NOT_APPLICABLE, "engineer", Assessment.FAIL)


def test_without_evidence_or_numeric_limit_the_engineer_must_assess(run, user):
    result = services.create_result(run, user)
    no_data = item(result, user, basis="leakage_rate", position="inboard", comparison="<=", limit=Decimal("15"),
                   unit="ml/h")
    e = evaluate(result, run, no_data)
    assert e.actual is None and e.effective == Assessment.NOT_EVALUATED and e.source == "no leakage logged"
    visual = item(result, user, criterion="Face condition", requirement_text="No damage", actual_text="No damage")
    assert evaluate(result, run, visual).effective == Assessment.NOT_EVALUATED
    visual.assessment = Assessment.PASS
    assert evaluate(result, run, visual).effective == Assessment.PASS


def test_logged_hours_are_shown_but_never_assessed_automatically(run, user):
    log(run, user, 0, speed=2950)
    log(run, user, 74, speed=2950)
    result = services.create_result(run, user)
    runtime = item(result, user, criterion="Runtime", basis="logged_hours", comparison=">=", limit=Decimal("72"),
                   unit="h")
    e = evaluate(result, run, runtime)
    assert e.actual == pytest.approx(74) and e.effective == Assessment.NOT_EVALUATED


def test_unit_mismatch_is_not_compared(run, user):
    result, _ = legacy_ob_stator(run, user)
    it = item(result, user, basis="leakage_rate", position="outboard", comparison="<=", limit=Decimal("150"),
              unit="l/h")
    assert evaluate(result, run, it).effective == Assessment.NOT_EVALUATED


def form(result, **data):
    values = {"criterion": "OB leakage", "basis": "leakage_rate", "position": "outboard", "comparison": "<=",
              "limit": "15", "unit": "", "requirement_text": "", "actual_text": "", "assessment": "", "remark": ""}
    values.update(data)
    instance = AcceptanceItem(result=result, updated_by=result.created_by)
    return AcceptanceItemForm(values, instance=instance, result=result, positions=["inboard", "outboard"])


def test_form_fixes_the_unit_of_a_calculated_actual_and_requires_its_subject(run, user):
    result = services.create_result(run, user)
    f = form(result, unit="l/h")
    assert f.is_valid(), f.errors
    saved = f.save()
    assert saved.unit == "ml/h" and saved.limit == Decimal("15")
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
