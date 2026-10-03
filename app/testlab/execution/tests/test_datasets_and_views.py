"""DCS dataset storage and plot data; manual log and DCS pages (M2A)."""

import hashlib
import math
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from testlab.execution import datasets
from testlab.execution.models import DcsDataset, ManualLogEntry
from testlab.tcn.models import TcnRevision
from testlab.tcn.services import TcnRuleError, create_tcn, delete_draft
from testlab.tcn.tests.factories import make_project

from .test_labview import NAME, export

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(user):
    project = make_project(user, project_no="2026RSD03TL", description="ADNOC BAB")
    return create_tcn(project, 1, user).test_run


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def upload(content=None, name=NAME):
    return SimpleUploadedFile(name, export() if content is None else content, content_type="application/octet-stream")


# --- storage ---------------------------------------------------------------------------


def test_import_keeps_the_file_unchanged(run, user):
    content = export()
    dataset = datasets.import_dataset(run, upload(content), user)
    with dataset.raw_file.open("rb") as stored:
        assert stored.read() == content
    assert dataset.sha256 == hashlib.sha256(content).hexdigest() and dataset.size == len(content)
    assert dataset.raw_file.name.startswith("projects/2026RSD03TL/runs/001/dcs/")
    assert dataset.original_name == NAME and dataset.imported_by == user
    assert dataset.sample_count == 20 and [s["name"] for s in dataset.value_signals()][0] == "(T04) LBI"
    assert dataset.recording_started_at is not None


def test_columns_file_is_rebuilt_when_missing(run, user):
    dataset = datasets.import_dataset(run, upload(), user)
    first = datasets.load_columns(dataset)
    dataset.raw_file.storage.delete(dataset.columns_file)
    assert datasets.load_columns(dataset) == first
    assert dataset.raw_file.storage.exists(dataset.columns_file)


def test_unreadable_file_imports_nothing(run, user, file_storage):
    with pytest.raises(datasets.DatasetImportError, match="could not be read"):
        datasets.import_dataset(run, upload(b"no numbers here\n"), user)
    assert not DcsDataset.objects.exists() and not any(file_storage.rglob("*.columns"))


def big_export(samples):
    rows = "".join(f"{i * 5 / 3600:.6f}\t{40 + math.sin(i / 500):.3f}\t30.000\t5600.000\n" for i in range(samples))
    spike = samples // 2
    rows = rows.replace(f"{spike * 5 / 3600:.6f}\t", f"{spike * 5 / 3600:.6f}\t99.0#", 1).replace("99.0#", "99.0\t9")
    return ("Time\t(T04) LBI\t(X22) Process Syst Press\tMotor Speed\nHrs\tT [C]\tBarG\tRPM\n" + rows).encode()


def test_full_resolution_when_it_fits(run, user):
    dataset = datasets.import_dataset(run, upload(), user)
    data = datasets.plot_data(dataset, {1})
    assert not data["decimated"] and len(data["traces"][0]["x"]) == 20


def test_large_dataset_is_decimated_for_display_keeping_extremes(run, user):
    content = (
        "Time\t(T04) LBI\tSpeed\nHrs\tT [C]\tRPM\n"
        + "".join(f"{i * 5 / 3600:.6f}\t{99.0 if i == 123_457 else 40 + (i % 7) * 0.1:.3f}\t5600\n" for i in range(200_000))
    ).encode()
    started = time.perf_counter()
    dataset = datasets.import_dataset(run, upload(content, "long run"), user)
    data = datasets.plot_data(dataset, {1}, points=4000)
    elapsed = time.perf_counter() - started
    trace = data["traces"][0]
    assert data["decimated"] and data["samples_in_window"] == 200_000
    assert len(trace["y"]) <= 4000
    assert max(trace["y"]) == 99.0 and min(trace["y"]) == 40.0  # the spike survives decimation
    assert dataset.sample_count == 200_000  # nothing discarded
    assert elapsed < 20


def test_time_window(run, user):
    dataset = datasets.import_dataset(run, upload(), user)
    data = datasets.plot_data(dataset, {1}, start_h=10 * 5 / 3600, end_h=14 * 5 / 3600)
    assert data["samples_in_window"] == 5


# --- pages -----------------------------------------------------------------------------


def log_url(run):
    return reverse("execution:log", args=[run.pk])


def test_log_page_shows_fields_of_the_configuration(logged_in, run):
    content = logged_in.get(log_url(run)).content.decode()
    assert "Add reading" in content and "Barrier" in content and "Inboard Seal" in content
    assert 'name="outboard_leakage"' in content and 'name="process_pressure"' not in content  # no Plug Seal
    assert "Entered as MG" in content and "Maria Geerts" not in content.split("<main")[1].split("Entered as")[0]


def test_add_reading_with_decimal_comma(logged_in, run, user):
    response = logged_in.post(
        log_url(run),
        {"observed_at": "2026-06-29T09:17", "speed": "2983", "torque": "6,97", "outboard_leakage": "40,5", "note": ""},
    )
    assert response.status_code == 302
    entry = ManualLogEntry.objects.get()
    assert entry.entered_by == user and entry.test_run == run
    assert {v.code: str(v.value) for v in entry.measurements.all()} == {
        "speed": "2983.0000", "torque": "6.9700", "outboard_leakage": "40.5000",
    }  # fmt: skip
    content = logged_in.get(log_url(run)).content.decode()
    assert "6.97" in content and "40.5" in content and "29-Jun-2026 09:17" in content
    assert ">MG</td>" in content  # who: the logged-in user's initials
    assert "provisional" in content  # no LabVIEW recording yet


def test_empty_reading_is_refused(logged_in, run):
    response = logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:17"})
    assert response.status_code == 200 and "Enter at least one reading, an event or a note." in response.content.decode()
    assert not ManualLogEntry.objects.exists()


def test_note_only_entry_is_an_event(logged_in, run):
    logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:05", "note": "Start recording LabVIEW"})
    assert ManualLogEntry.objects.get().note == "Start recording LabVIEW"


def test_edit_and_delete(logged_in, run):
    logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:17", "speed": "2983"})
    entry = ManualLogEntry.objects.get()
    url = reverse("execution:entry_edit", args=[entry.pk])
    assert 'value="2983"' in logged_in.get(url).content.decode()
    logged_in.post(url, {"observed_at": "2026-06-29T09:18", "speed": "2984"})
    assert ManualLogEntry.objects.get().measurements.get().value == 2984
    logged_in.post(reverse("execution:entry_delete", args=[entry.pk]))
    assert not ManualLogEntry.objects.exists()


def test_dcs_upload_without_extension_and_plot(logged_in, run):
    response = logged_in.post(reverse("execution:dcs", args=[run.pk]), {"file": upload()})
    dataset = DcsDataset.objects.get()
    assert response.url == reverse("execution:dcs_detail", args=[dataset.pk])
    page = logged_in.get(response.url).content.decode()
    assert "(T04) LBI [T [C]]" in page and "vendor/plotly/plotly-basic" in page
    assert "cdn" not in page.lower()  # no runtime Internet dependency
    data = logged_in.get(reverse("execution:dcs_data", args=[dataset.pk]), {"columns": "1,3"}).json()
    assert [t["column"] for t in data["traces"]] == [1, 3]
    raw = logged_in.get(reverse("execution:dcs_raw", args=[dataset.pk]))
    assert b"".join(raw.streaming_content) == export()


def test_dcs_upload_error_is_shown(logged_in, run):
    response = logged_in.post(reverse("execution:dcs", args=[run.pk]), {"file": upload(b"\x00binary")})
    assert "binary file" in response.content.decode() and not DcsDataset.objects.exists()


def test_register_links_to_the_run_log(logged_in, run):
    content = logged_in.get(reverse("projects:detail", args=[run.project.pk])).content.decode()
    assert log_url(run) in content


def test_pages_require_login(client, run):
    assert client.get(log_url(run)).status_code == 302


def test_draft_whose_run_has_evidence_cannot_be_deleted(logged_in, run, user):
    logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:17", "note": "start"})
    draft = TcnRevision.objects.get(test_run=run)
    with pytest.raises(TcnRuleError, match="manual log readings or DCS data"):
        delete_draft(draft, draft.row_version, user)
    assert ManualLogEntry.objects.exists()


def test_elapsed_hours_from_the_labview_recording_start(logged_in, run, user):
    datasets.import_dataset(run, upload(), user)  # recording started 01-Oct-2026 11:43:01
    logged_in.post(log_url(run), {"observed_at": "2026-10-01T11:13", "note": "static leakage check"})
    logged_in.post(log_url(run), {"observed_at": "2026-10-01T13:43", "speed": "2980"})
    content = logged_in.get(log_url(run)).content.decode()
    assert "t = 0: start of the LabVIEW recording, 01-Oct-2026 11:43:01" in content
    assert ">-0.50</td>" in content and ">2.00</td>" in content and "provisional" not in content


def test_dataset_without_known_start_does_not_set_t0(run, user):
    from testlab.execution.manual_log import timeline_origin

    datasets.import_dataset(run, upload(name="export"), user)  # ambiguous date, no start
    assert timeline_origin(run).provisional


def test_production_requires_an_issued_tcn(logged_in, run, settings):
    settings.TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN = True
    page = logged_in.get(log_url(run)).content.decode()
    assert "has not been issued yet" in page and "Add reading" not in page
    logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:17", "speed": "1"})
    logged_in.post(reverse("execution:dcs", args=[run.pk]), {"file": upload()})
    assert not ManualLogEntry.objects.exists() and not DcsDataset.objects.exists()


def test_drafts_allowed_while_testing(logged_in, run):
    assert not TcnRevision.objects.filter(test_run=run).exclude(status="draft").exists()
    logged_in.post(log_url(run), {"observed_at": "2026-06-29T09:17", "speed": "1"})
    assert ManualLogEntry.objects.exists()


def test_log_offers_diff_seal_pressure_only_when_instructed(logged_in, run):
    assert 'name="seal_support_diff_pressure"' not in logged_in.get(log_url(run)).content.decode()
    setup = run.current_revision().setup
    setup.monitored_parameters = ["seal_support_diff_pressure"]
    setup.save()
    content = logged_in.get(log_url(run)).content.decode()
    assert 'name="seal_support_diff_pressure"' in content and "Head generated by the pumping device" in content
