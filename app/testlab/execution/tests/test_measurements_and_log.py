"""Measurement catalogue and manual log calculations (M2A)."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from testlab.execution import manual_log
from testlab.execution.measurements import measurement, run_measurements
from testlab.execution.models import ManualLogEntry
from testlab.projects.arrangements import Arrangement
from testlab.tcn.services import create_tcn
from testlab.tcn.tests.factories import make_project

AMS = ZoneInfo("Europe/Amsterdam")


def codes(arrangement, plug, instructed=()):
    return [m.code for m in run_measurements(arrangement, plug, instructed)]


def test_dual_pressurized_without_plug_seal():
    assert codes(Arrangement.DUAL_PRESSURIZED, False) == [
        "speed", "torque",
        "seal_support_pressure", "seal_support_inlet_temp", "seal_support_outlet_temp", "seal_support_flow",
        "inboard_face_temp", "inboard_leakage", "outboard_face_temp", "outboard_leakage",
    ]  # fmt: skip
    assert measurement("seal_support_pressure", Arrangement.DUAL_PRESSURIZED).full_label == "Barrier pressure [barg]"


def test_single_has_process_conditions_flush_plug_and_test_seal():
    found = codes(Arrangement.SINGLE, True, ["seal_support_diff_pressure"])
    assert found[:2] == ["speed", "torque"] and "seal_support_diff_pressure" not in found  # dual only
    assert [c for c in found if c.startswith("process_")] == [
        "process_pressure", "process_inlet_temp", "process_outlet_temp", "process_flow",
    ]  # fmt: skip
    assert "plug_leakage" in found and "test_leakage" in found and "inboard_leakage" not in found
    assert measurement("seal_support_flow", Arrangement.SINGLE).group == "Flush"
    assert measurement("plug_face_temp", Arrangement.SINGLE).full_label == "Plug Seal face temp. [°C]"


def test_process_conditions_only_with_the_plug_seal():
    assert not any(c.startswith("process_") for c in codes(Arrangement.DUAL_UNPRESSURIZED, False))
    found = codes(Arrangement.DUAL_UNPRESSURIZED, True)
    assert "process_pressure" in found and "plug_face_temp" in found
    assert measurement("seal_support_pressure", Arrangement.DUAL_UNPRESSURIZED).group == "Buffer"


@pytest.mark.parametrize("arrangement", [Arrangement.DUAL_PRESSURIZED, Arrangement.DUAL_UNPRESSURIZED])
def test_diff_seal_pressure_only_when_the_tcn_ticks_it(arrangement):
    assert "seal_support_diff_pressure" not in codes(arrangement, False)
    found = codes(arrangement, False, ["seal_support_diff_pressure"])
    assert found.index("seal_support_diff_pressure") == found.index("seal_support_flow") + 1


def test_diff_seal_pressure_is_the_pumping_head_in_bar():
    dp = measurement("seal_support_diff_pressure", Arrangement.DUAL_UNPRESSURIZED)
    assert dp.unit == "bar" and "pumping device" in dp.description
    assert dp.full_label == "Buffer diff. seal pressure [bar]"


def test_static_leakage_is_taken_as_logged():
    """No speed filter: leakage while the shaft stands still has a rate like any other."""
    assert manual_log.leakage_for(Decimal("3"), None, 2.0).rate == 1.5


def test_leakage_is_a_volume_with_a_calculated_rate():
    leak = measurement("outboard_leakage", Arrangement.DUAL_PRESSURIZED)
    assert leak.is_leakage and leak.unit == "ml"


# --- leakage rate --------------------------------------------------------------------


def test_rate_over_time_since_previous_reading():
    leak = manual_log.leakage_for(Decimal("420"), None, 16.3)
    assert leak.rate == pytest.approx(25.7668, rel=1e-4)  # legacy TCN001 row 16 (overnight)
    assert leak.period_source == "since previous reading"


def test_entered_period_replaces_time_since_previous():
    leak = manual_log.leakage_for(Decimal("30"), Decimal("0.5"), 16.3)
    assert leak.rate == 60 and leak.hours == 0.5 and leak.period_source == "entered"


def test_no_rate_without_period_or_with_zero_period():
    first = manual_log.leakage_for(Decimal("5"), None, None)
    assert first.rate is None and "first reading" in first.note
    zero = manual_log.leakage_for(Decimal("5"), None, 0.0)
    assert zero.rate is None and "zero" in zero.note


def test_no_rate_without_volume():
    assert manual_log.leakage_for(None, None, 1.0).rate is None


# --- log rows ------------------------------------------------------------------------


@pytest.fixture
def run(user):
    project = make_project(user, project_no="2026RSD03TL")
    return create_tcn(project, 1, user).test_run


def add(run, user, when, **values):
    columns = manual_log.log_columns(run)
    cleaned = {"observed_at": when, "note": values.pop("note", ""), "leakage_hours": values.pop("leakage_hours", None)}
    cleaned.update({k: Decimal(str(v)) for k, v in values.items()})
    return manual_log.save_entry(run, cleaned, columns, user)


@pytest.mark.django_db
def test_provisional_elapsed_hours_and_leakage_across_midnight(run, user):
    start = datetime(2026, 6, 29, 15, 30, tzinfo=AMS)
    add(run, user, start, outboard_leakage=35, speed=2985)
    add(run, user, start + timedelta(hours=16, minutes=18), outboard_leakage=420)  # next morning
    add(run, user, start + timedelta(hours=17, minutes=26), outboard_leakage=31, leakage_hours=Decimal("0.5"))
    rows = manual_log.log_rows(run)
    assert [round(r.elapsed_h, 2) for r in rows] == [0, 16.3, 17.43]
    assert rows[0].leakage["outboard_leakage"].rate is None  # first reading
    assert rows[1].leakage["outboard_leakage"].rate == pytest.approx(420 / 16.3)
    assert rows[2].leakage["outboard_leakage"].rate == 62  # entered period
    assert "inboard_leakage" not in rows[1].leakage  # nothing entered, nothing calculated


@pytest.mark.django_db
def test_entries_are_ordered_by_observation_time_not_entry_order(run, user):
    start = datetime(2026, 6, 29, 9, 0, tzinfo=AMS)
    add(run, user, start + timedelta(hours=2), outboard_leakage=20)
    add(run, user, start, speed=2983)  # entered afterwards, observed earlier
    rows = manual_log.log_rows(run)
    assert [r.entry.observed_at for r in rows] == [start, start + timedelta(hours=2)]
    assert rows[1].leakage["outboard_leakage"].rate == 10


@pytest.mark.django_db
def test_save_updates_and_clears_values(run, user):
    when = datetime(2026, 6, 29, 9, 0, tzinfo=AMS)
    entry = add(run, user, when, speed=2983, torque="6.97")
    columns = manual_log.log_columns(run)
    cleaned = {"observed_at": when, "note": "heater on", "leakage_hours": None, "speed": Decimal("2984")}
    manual_log.save_entry(run, cleaned, columns, user, entry=entry)
    entry = ManualLogEntry.objects.get(pk=entry.pk)
    assert {v.code: v.value for v in entry.measurements.all()} == {"speed": Decimal("2984")}
    assert entry.note == "heater on" and entry.entered_by == user


@pytest.mark.django_db
def test_values_of_codes_that_no_longer_apply_stay_visible(run, user):
    when = datetime(2026, 6, 29, 9, 0, tzinfo=AMS)
    entry = add(run, user, when, speed=1)
    entry.measurements.create(code="plug_face_temp", value=Decimal("55"), unit="°C")
    assert "plug_face_temp" in [c.code for c in manual_log.log_columns(run, [entry])]
