"""Seal-face measurement pages (M2D): + Add measurement, review page, actions, files."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from testlab.results import services
from testlab.results.models import FaceMeasurement

from .facemeasure_variants import MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CSV, fixture_text
from .helpers import make_run

pytestmark = pytest.mark.django_db


def upload(name):
    return SimpleUploadedFile(name, fixture_text(name).encode("utf-8"))


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


@pytest.fixture
def result(run, user):
    return services.create_result(run, user)


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def component(result, label):
    return next(c for c in result.components.all() if c.label == label)


def add_mahr(client, stator, **extra):
    data = {"kind": "mahr", "stage": "pre", "od": "5,034", "id": "4.634", "units": "in",
            "left_file": upload(MAHR_LEFT), "right_file": upload(MAHR_RIGHT), **extra}  # fmt: skip
    return client.post(reverse("results:measurement_add", args=[stator.pk]), data)


def test_add_offers_only_the_applicable_kinds_of_the_component(logged_in, result):
    rotor = component(result, "IB Rotor")
    rotor.dimensional_applicability = "not_applicable"
    rotor.save()
    page = logged_in.get(reverse("results:measurement_add", args=[rotor.pk])).content.decode()
    assert "Mahr profile / roughness" in page and "ROUNDPAK flatness" in page
    assert 'value="dimensional"' not in page
    step2 = logged_in.get(reverse("results:measurement_add", args=[rotor.pk]), {"kind": "roundpak", "stage": "post"})
    assert "ROUNDPAK CSV" in step2.content.decode() and "Post-test" in step2.content.decode()


def test_mahr_upload_calculates_a_draft_and_remembers_the_face_dimensions(logged_in, result):
    stator = component(result, "IB Stator")
    response = add_mahr(logged_in, stator)
    m = FaceMeasurement.objects.get()
    assert response.status_code == 302 and response["Location"] == reverse("results:measurement", args=[m.pk])
    stator.refresh_from_db()
    assert (stator.face_od, stator.face_id) == (Decimal("5.034"), Decimal("4.634"))  # entered once, reused
    page = logged_in.get(response["Location"]).content.decode()
    assert "Draft: calculated from the files" in page and "−0.0186 µm" in page and "Flat" in page
    assert page.count("<svg") == 3 and "Taper in helium light bands" in page and "Provisional" not in page
    assert "Review and report" in page and "JRO-003L.TXT" in page
    result_page = logged_in.get(reverse("results:result", args=[result.test_run.pk])).content.decode()
    assert "in review" in result_page


def test_mahr_upload_needs_the_face_width(logged_in, result):
    response = add_mahr(logged_in, component(result, "IB Stator"), od="", id="")
    assert response.status_code == 200 and "the taper needs the radial face width" in response.content.decode()
    assert not FaceMeasurement.objects.exists()


def test_unreadable_file_is_shown_on_the_form(logged_in, result):
    stator = component(result, "IB Stator")
    response = logged_in.post(reverse("results:measurement_add", args=[stator.pk]), {
        "kind": "roundpak", "stage": "pre", "units": "in", "file": SimpleUploadedFile("x.csv", b"Title,x\n"),
    })  # fmt: skip
    assert response.status_code == 200 and "x.csv could not be read: No ROUNDPAK measurement tables found." in (
        response.content.decode())


def test_settings_recalculate_then_review_reports_it(logged_in, result, run):
    add_mahr(logged_in, component(result, "IB Stator"))
    m = FaceMeasurement.objects.get()
    url = reverse("results:measurement", args=[m.pk])
    data = {"od": "5.034", "id": "4.634", "units": "in", "light_band_um": "0.29", "left_direction": "in",
            "left_start": "1", "left_end": "8", "right_direction": "out", "right_start": "1", "right_end": "8",
            "pv_view": "raw", "skip_points": "0", "flat_limit_hlb": "0,25"}  # fmt: skip
    assert logged_in.post(url, data).status_code == 302
    m.refresh_from_db()
    assert (m.mahr.left_start_mm, m.mahr.pv_view, m.mahr.skip_points, m.mahr.flat_limit_hlb) == (1.0, "raw", 0, 0.25)
    response = logged_in.post(url, {**data, "left_end": "12"})
    assert response.status_code == 200 and "Choose an interval within 0–9 mm" in response.content.decode()
    logged_in.post(reverse("results:measurement_action", args=[m.pk, "review"]))
    m.refresh_from_db()
    assert m.is_reviewed and m.reported and m.figures.count() == 3
    page = logged_in.get(url).content.decode()
    assert "kept at review" in page and "Reopen" in page and 'name="left_start"' not in page
    summary = logged_in.get(reverse("results:result", args=[run.pk])).content.decode()
    assert "−0.0528" in summary  # the reviewed taper (intervals 1–8 mm) is in the Pre/Post summary


def test_remark_report_selection_links_and_original_file_download(logged_in, result):
    stator = component(result, "IB Stator")
    logged_in.post(reverse("results:measurement_add", args=[stator.pk]),
                   {"kind": "roundpak", "stage": "post", "units": "in", "file": upload(ROUNDPAK_CSV)})  # fmt: skip
    m = FaceMeasurement.objects.get()
    logged_in.post(reverse("results:measurement_options", args=[m.pk]), {"remark": " ok "})
    m.refresh_from_db()
    assert m.remark == "ok"
    page = logged_in.get(reverse("results:measurement", args=[m.pk])).content.decode()
    assert "Reviewed is not the same as published" in page  # what a report shows is chosen per profile
    assert f"report/profile/customer/#slot-{stator.pk}-roundpak" in page
    download = logged_in.get(reverse("results:measurement_file", args=[m.pk, "roundpak"]))
    assert b"".join(download.streaming_content) == fixture_text(ROUNDPAK_CSV).encode("utf-8")
    assert "ROUNDPAK-SIC30-post.csv" in download["Content-Disposition"]


def test_delete_asks_first_and_returns_to_the_component(logged_in, result, django_capture_on_commit_callbacks):
    stator = component(result, "IB Stator")
    add_mahr(logged_in, stator)
    m = FaceMeasurement.objects.get()
    url = reverse("results:measurement_delete", args=[m.pk])
    assert "Delete IB Stator Mahr profile / roughness Pre-test?" in logged_in.get(url).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        response = logged_in.post(url)
    assert response["Location"].endswith(f"#component-{stator.pk}") and not FaceMeasurement.objects.exists()


def test_measurement_plan_hides_not_applicable_rows(logged_in, result, run):
    logged_in.post(reverse("results:measurement_plan", args=[run.pk]), {
        "dimensional_applicability": "not_applicable", "mahr_applicability": "not_applicable",
        "roundpak_applicability": "required",
    })  # fmt: skip
    result.refresh_from_db()
    assert result.mahr_applicability == "not_applicable"
    page = logged_in.get(reverse("results:result", args=[run.pk]))
    rows = [row.quantity.code for group in page.context["measurement_summary"] for row in group.rows]
    assert set(rows) == {"face_flatness", "face_taper_roundpak"} and len(rows) == 8


def test_changes_are_refused_until_the_tcn_is_issued_in_production(logged_in, result, settings):
    settings.TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN = True
    response = add_mahr(logged_in, component(result, "IB Stator"))
    assert response.status_code == 302 and not FaceMeasurement.objects.exists()
