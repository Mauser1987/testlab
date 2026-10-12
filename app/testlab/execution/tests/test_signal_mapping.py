"""DCS signals mapped to TestLab/TCN parameters, reviewed and reused per export format (M2E)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from testlab.execution import datasets, manual_log, signal_mapping
from testlab.execution.models import DcsSignalMap
from testlab.results import evidence, runtime
from testlab.results.tests.helpers import make_run

from .test_labview import HEADER, NAME

pytestmark = pytest.mark.django_db

NAMES = "Time\tMotor Speed\tPT Barrier\tLBI temp\n"
UNITS = "Hrs\tRPM\tbar\tC\n"
STEP_H = 0.05


def export(names=NAMES, units=UNITS, samples=40, stop_at_h=1.0):
    """Running at 3000 rpm until stop_at_h, then stopped; barrier pressure 70 running, 75 stopped."""
    lines = []
    for i in range(samples):
        t = i * STEP_H
        running = t < stop_at_h
        lines.append(f"{t:.4f}\t{3000 if running else 0}\t{70 + i * 0.01 if running else 75:.2f}\t{40 + i * 0.1:.1f}\n")
    return (HEADER + names + units + "".join(lines)).encode("ascii")


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


def imported(run, user, content=None):
    return datasets.import_dataset(run, SimpleUploadedFile(NAME, content or export()), user)


def columns(dataset):
    return {s["name"]: s["column"] for s in dataset.value_signals()}


def review(dataset, user, confirm=True):
    c = columns(dataset)
    chosen = {c["Motor Speed"]: "speed", c["PT Barrier"]: "seal_support_pressure", c["LBI temp"]: ""}
    return signal_mapping.review_mapping(dataset, chosen, {c["PT Barrier"]} if confirm else set(), user)


def test_a_new_format_is_not_used_until_reviewed(run, user):
    dataset = imported(run, user)
    assert not dataset.mapping_reviewed and signal_mapping.mapped_column(dataset, "speed") is None


def test_a_differing_unit_needs_an_explicit_confirmation(run, user):
    dataset = imported(run, user)
    with pytest.raises(signal_mapping.MappingError, match=r"PT Barrier is in \[bar\].*\[barg\]: confirm"):
        review(dataset, user, confirm=False)
    dataset.refresh_from_db()
    assert not dataset.mapping_reviewed
    review(dataset, user)
    dataset.refresh_from_db()
    assert dataset.mapping_reviewed and dataset.mapping_reviewed_by == user
    speed = str(columns(dataset)["Motor Speed"])
    assert dataset.mapping[speed] == {"code": "speed", "unit_confirmed": False}  # RPM = rpm: nothing to confirm
    assert signal_mapping.describe(dataset, "seal_support_pressure") == f"{NAME} › PT Barrier [bar]"


def test_one_parameter_per_signal_and_only_parameters_of_the_run(run, user):
    dataset = imported(run, user)
    c = columns(dataset)
    with pytest.raises(signal_mapping.MappingError, match="chosen for two signals"):
        signal_mapping.review_mapping(dataset, {c["Motor Speed"]: "speed", c["LBI temp"]: "speed"}, set(), user)
    with pytest.raises(signal_mapping.MappingError, match="not a parameter of this run"):
        signal_mapping.review_mapping(dataset, {c["LBI temp"]: "plug_face_temp"}, set(), user)  # no Plug Seal


def test_a_reviewed_mapping_is_reused_for_the_same_format_only(run, user):
    review(imported(run, user), user)
    assert DcsSignalMap.objects.count() == 1
    again = imported(run, user, export(samples=30))  # same signals and units, other data
    assert again.mapping_reviewed and again.mapping_from is not None
    assert signal_mapping.mapped_column(again, "speed") == columns(again)["Motor Speed"]
    other = imported(run, user, export(units="Hrs\tRPM\tbarg\tC\n"))  # a unit differs: review again
    assert not other.mapping_reviewed
    assert signal_mapping.suggestions(other) == {columns(other)["Motor Speed"]: "speed"}  # prefilled only


def test_running_hours_and_running_actuals_from_the_dcs_speed_signal(run, user):
    dataset = imported(run, user)
    review(dataset, user)
    dataset.refresh_from_db()
    start = dataset.recording_started_at
    entry = {"note": "", "category": "", "leakage_hours": None}
    for hours in (0, 1.95):  # manual readings without speed: the DCS decides
        manual_log.save_entry(run, {**entry, "observed_at": start + timedelta(hours=hours)},
                              manual_log.log_columns(run), user)  # fmt: skip
    rows = manual_log.log_rows(run)
    period = evidence.logged_period(run, rows)
    timeline = runtime.build(run, rows, period)
    # samples every 0.05 h; the stop between the samples at 0.95 h and 1.00 h is placed half-way
    assert timeline.running_h == pytest.approx(0.975) and timeline.stopped_h == pytest.approx(0.975)
    assert timeline.unknown_h == pytest.approx(0, abs=1e-9)
    assert timeline.sources[0].startswith(f"{NAME} › Motor Speed [RPM]")
    (pressure,) = [r for r in evidence.actual_ranges(run, rows, manual_log.log_columns(run), timeline)
                   if r.measurement.code == "seal_support_pressure"]  # fmt: skip
    assert pressure.source == f"DCS {NAME} › PT Barrier [bar]"
    assert (float(pressure.minimum), float(pressure.maximum), pressure.count) == (70.0, 70.19, 20)
    assert pressure.stopped.count == 20 and float(pressure.stopped.minimum) == 75.0  # kept, not in the running range


def test_unreviewed_dcs_data_is_not_used_for_running_hours(run, user):
    dataset = imported(run, user)
    start = dataset.recording_started_at
    manual_log.save_entry(run, {"note": "", "category": "", "leakage_hours": None, "observed_at": start},
                          manual_log.log_columns(run), user)  # fmt: skip
    rows = manual_log.log_rows(run)
    timeline = runtime.build(run, rows, evidence.logged_period(run, rows))
    assert timeline.running_h == 0 and timeline.unknown_h == pytest.approx(timeline.elapsed_h)
    assert "no reviewed speed signal" in timeline.notes[0]


def test_mapping_is_reviewed_on_the_dataset_page(client, run, user):
    dataset = imported(run, user)
    client.force_login(user)
    url = reverse("execution:dcs_detail", args=[dataset.pk])
    page = client.get(url).content.decode()
    assert "Signal mapping" in page and "not reviewed" in page
    c = columns(dataset)
    data = {f"mapping_{c['Motor Speed']}": "speed", f"mapping_{c['PT Barrier']}": "seal_support_pressure"}
    refused = client.post(url, data)
    assert refused.status_code == 200 and "confirm that the values are in barg" in refused.content.decode()
    response = client.post(url, {**data, f"unit_{c['PT Barrier']}": "1"})
    assert response.status_code == 302 and response["Location"].endswith("#mapping")
    dataset.refresh_from_db()
    assert dataset.mapping_reviewed
