"""Result pictures and the Result tab (M2B)."""

import hashlib
import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from testlab.results import images, services
from testlab.results.models import AcceptanceItem, InspectionMeasurement, ResultImage, TestResult

from .helpers import log, make_run

pytestmark = pytest.mark.django_db


def picture(name="ib-rotor.jpg", size=(2400, 1200), fmt="JPEG", color="steelblue"):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


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


# --- pictures ---------------------------------------------------------------------------


def test_original_is_kept_byte_for_byte_with_metadata(result, user):
    upload = picture()
    content = upload.read()
    upload.seek(0)
    rotor = component(result, "IB Rotor")
    image = images.add_image(result, upload, user, ResultImage.Category.POST_TEST, rotor, "  Light wear marks ")
    with image.file.open("rb") as stored:
        assert stored.read() == content
    assert image.sha256 == hashlib.sha256(content).hexdigest() and image.size == len(content)
    assert (image.width, image.height, image.image_format) == (2400, 1200, "JPEG")
    assert image.file.name.startswith("projects/2026RSD03TL/runs/001/result/images/")
    assert (image.result, image.category, image.component, image.caption) == (result, "post_test", rotor, "Light wear marks")
    assert image.uploaded_by == user and image.uploaded_at is not None
    with image.file.storage.open(image.preview_file, "rb") as preview:
        assert max(Image.open(preview).size) == images.PREVIEW_MAX_PX


def test_cross_section_needs_no_component(result, user):
    image = images.add_image(result, picture("section.png", fmt="PNG"), user, ResultImage.Category.CROSS_SECTION)
    assert image.component is None and image.image_format == "PNG"


def test_preview_is_rebuilt_when_missing(result, user):
    image = images.add_image(result, picture(), user, ResultImage.Category.OTHER)
    image.file.storage.delete(image.preview_file)
    name = images.preview_name(image)
    assert image.file.storage.exists(name)


def test_not_a_picture_is_refused_and_nothing_is_stored(result, user, file_storage):
    with pytest.raises(images.ImageUploadError, match="not a picture"):
        images.add_image(result, SimpleUploadedFile("notes.jpg", b"plain text"), user, ResultImage.Category.OTHER)
    assert not ResultImage.objects.exists() and not any(p.is_file() for p in file_storage.rglob("*"))


def test_order_is_per_group_and_can_be_changed(result, user):
    rotor = component(result, "IB Rotor")
    first, second, third = (
        images.add_image(result, picture(f"{n}.jpg"), user, ResultImage.Category.PRE_TEST, rotor) for n in "abc"
    )
    other_group = images.add_image(result, picture("d.jpg"), user, ResultImage.Category.POST_TEST, rotor)
    assert [first.order, second.order, third.order, other_group.order] == [0, 1, 2, 0]
    images.move(third, -1)
    ordered = list(result.images.filter(category="pre_test").order_by("order", "pk"))
    assert [i.original_name for i in ordered] == ["a.jpg", "c.jpg", "b.jpg"]
    images.move(ordered[0], -1)  # already first: nothing changes
    assert list(result.images.filter(category="pre_test").order_by("order", "pk")) == ordered


# --- access -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, args",
    [("results:result", "run"), ("results:compare", "run_component"), ("results:image_original", "image"),
     ("results:image_preview", "image"), ("results:image_edit", "image"), ("results:acceptance_edit", "item")],
)  # fmt: skip
def test_every_result_page_requires_login(client, result, user, name, args):
    image = images.add_image(result, picture(), user, ResultImage.Category.OTHER)
    it = AcceptanceItem.objects.create(result=result, criterion="x", requirement_text="y", updated_by=user)
    values = {"run": [result.test_run.pk], "run_component": [result.test_run.pk, result.components.first().pk],
              "image": [image.pk], "item": [it.pk]}[args]  # fmt: skip
    response = client.get(reverse(name, args=values))
    assert response.status_code == 302 and response["Location"].startswith(reverse("login"))
    response = client.post(reverse("results:start", args=[result.test_run.pk]))
    assert response.status_code == 302 and response["Location"].startswith(reverse("login"))


# --- the Result tab -------------------------------------------------------------------------


def test_run_without_result_offers_to_start_one(logged_in, run):
    url = reverse("results:result", args=[run.pk])
    page = logged_in.get(url).content.decode()
    assert "No Result yet" in page and 'aria-current="page">Result<' in page
    response = logged_in.post(reverse("results:start", args=[run.pk]))
    assert response.status_code == 302 and TestResult.objects.filter(test_run=run).exists()


def test_result_page_shows_all_sections_and_derived_summary(logged_in, run, result, user):
    log(run, user, 0, outboard_leakage=0, speed=2950)
    log(run, user, 22.5, outboard_leakage=2703, category="adjustment", note="Cooling water flow reduced")
    page = logged_in.get(reverse("results:result", args=[run.pk])).content.decode()
    for section in ("summary", "measurements", "pictures", "acceptance", "conclusion"):
        assert f'id="{section}"' in page
    assert "120.1" in page  # 2703 ml / 22.5 h, derived
    assert "Cooling water flow reduced" in page and "Adjustment" in page
    assert "IB Stator" in page and "OB Rotor" in page


def test_measurements_are_saved_from_the_grid(logged_in, run, result):
    stator = component(result, "OB Stator")
    form = logged_in.get(reverse("results:result", args=[run.pk])).context["measurements_form"]
    data = {name: "" for name in form.fields}
    data[f"m{stator.pk}_face_length_pre"] = "1,25037"
    data[f"m{stator.pk}_face_length_post"] = "1.25025"
    response = logged_in.post(reverse("results:measurements", args=[run.pk]), data)
    assert response.status_code == 302 and response["Location"].endswith("#measurements")
    stored = InspectionMeasurement.objects.get(component=stator, quantity="face_length")
    assert str(stored.pre_value.normalize()) == "1.25037" and stored.unit == "in"
    page = logged_in.get(reverse("results:result", args=[run.pk])).content.decode()
    assert "−0.00012" in page  # Δ
    data[f"m{stator.pk}_face_length_pre"] = "abc"
    response = logged_in.post(reverse("results:measurements", args=[run.pk]), data)
    assert response.status_code == 200 and "Enter a number." in response.content.decode()


def test_pictures_upload_and_pre_post_side_by_side(logged_in, run, result):
    rotor = component(result, "IB Rotor")
    url = reverse("results:image_upload", args=[run.pk])
    logged_in.post(url, {"files": [picture("pre1.jpg"), picture("pre2.jpg")], "category": "pre_test",
                         "component": str(rotor.pk), "caption": ""})  # fmt: skip
    logged_in.post(url, {"files": [picture("post.jpg")], "category": "post_test", "component": str(rotor.pk),
                         "caption": "After 144 h"})  # fmt: skip
    assert result.images.count() == 3
    response = logged_in.get(reverse("results:result", args=[run.pk]))
    comparison = response.context["pictures"]["comparisons"][0]
    assert comparison["component"] == rotor
    assert [p.original_name for p in comparison["pre"]] == ["pre1.jpg", "pre2.jpg"]
    assert [p.original_name for p in comparison["post"]] == ["post.jpg"]
    compare = logged_in.get(reverse("results:compare", args=[run.pk, rotor.pk]))
    assert compare.status_code == 200 and "After 144 h" in compare.content.decode()
    image = result.images.get(original_name="post.jpg")
    original = logged_in.get(reverse("results:image_original", args=[image.pk]))
    assert b"".join(original.streaming_content) == image.file.open("rb").read()


def test_picture_can_be_moved_to_another_component_and_deleted(
    logged_in, run, result, user, django_capture_on_commit_callbacks
):
    image = images.add_image(result, picture(), user, ResultImage.Category.PRE_TEST, component(result, "IB Rotor"))
    stator = component(result, "IB Stator")
    logged_in.post(reverse("results:image_edit", args=[image.pk]),
                   {"category": "post_test", "component": str(stator.pk), "caption": "OB side"})  # fmt: skip
    image.refresh_from_db()
    assert (image.category, image.component, image.caption) == ("post_test", stator, "OB side")
    names = [image.file.name, image.preview_file]
    with django_capture_on_commit_callbacks(execute=True):  # files go once the deletion is committed
        response = logged_in.post(reverse("results:image_delete", args=[image.pk]))
    assert response.status_code == 302 and not ResultImage.objects.exists()
    assert not any(image.file.storage.exists(n) for n in names)


def test_acceptance_criterion_is_added_and_assessed(logged_in, run, result, user):
    log(run, user, 0, outboard_leakage=0)
    log(run, user, 10, outboard_leakage=100)
    data = {"criterion": "OB leakage", "basis": "leakage_rate", "position": "outboard", "comparison": "<=",
            "limit": "15", "unit": "", "requirement_text": "", "actual_text": "", "assessment": "", "remark": ""}
    response = logged_in.post(reverse("results:acceptance_add", args=[run.pk]), data)
    assert response.status_code == 302
    page = logged_in.get(reverse("results:result", args=[run.pk]))
    evaluation = page.context["evaluations"][0]
    assert evaluation.effective == "pass" and evaluation.actual_text == "10.0 ml/h"
    item = AcceptanceItem.objects.get()
    logged_in.post(reverse("results:acceptance_edit", args=[item.pk]), {**data, "assessment": "fail",
                                                                         "remark": "Leakage unstable"})  # fmt: skip
    item.refresh_from_db()
    assert item.assessment == "fail" and item.remark == "Leakage unstable"
    logged_in.post(reverse("results:acceptance_edit", args=[item.pk]), {"delete": "1"})
    assert not AcceptanceItem.objects.exists()


def test_conclusion_is_engineer_text_and_records_who_changed_it(logged_in, run, result, other_user, client):
    client.force_login(other_user)
    client.post(reverse("results:narrative", args=[run.pk]),
                {"observations": "Leakage steady.", "conclusion": "Acceptable seal faces combination.",
                 "recommendation": ""})  # fmt: skip
    result.refresh_from_db()
    assert result.conclusion == "Acceptable seal faces combination." and result.updated_by == other_user


def test_production_policy_refuses_result_changes_until_the_tcn_is_issued(logged_in, run, result, settings):
    settings.TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN = True
    response = logged_in.post(reverse("results:narrative", args=[run.pk]), {"conclusion": "x"}, follow=True)
    assert "has not been issued yet" in response.content.decode()
    result.refresh_from_db()
    assert result.conclusion == ""
    page = logged_in.get(reverse("results:result", args=[run.pk])).content.decode()
    assert "Save measurements" not in page and not re.search(r'action="[^"]*/pictures/"', page)


def test_component_is_added_and_empty_one_removed_from_the_page(logged_in, run, result):
    response = logged_in.post(reverse("results:component_add", args=[run.pk]), {"component": ":sleeve"})
    assert response.status_code == 302 and result.components.filter(component="sleeve").exists()
    sleeve = result.components.get(component="sleeve")
    logged_in.post(reverse("results:component_remove", args=[sleeve.pk]))
    assert not result.components.filter(component="sleeve").exists()
    logged_in.post(reverse("results:component_add", args=[run.pk]), {"component": "plug:rotor"})  # no Plug Seal
    assert not result.components.filter(position="plug").exists()


def test_components_identity_is_saved(logged_in, run, result):
    form = logged_in.get(reverse("results:result", args=[run.pk])).context["identity_formset"]
    data = {key: value for key, value in form.management_form.initial.items()}
    data = {f"form-{k}": v for k, v in data.items()}
    for i, sub in enumerate(form.forms):
        data[f"form-{i}-id"] = sub.instance.pk
        data[f"form-{i}-part_no"] = f"C06187{i}SL"
        data[f"form-{i}-material"] = "Silicon Carbide (SL)"
        data[f"form-{i}-condition"] = "New"
    response = logged_in.post(reverse("results:components", args=[run.pk]), data)
    assert response.status_code == 302
    assert set(result.components.values_list("condition", flat=True)) == {"New"}


def test_manual_log_records_an_event_category(logged_in, run):
    response = logged_in.post(reverse("execution:log", args=[run.pk]),
                              {"observed_at": "2026-06-29T10:00", "category": "stop", "note": ""})  # fmt: skip
    assert response.status_code == 302
    assert run.manual_log_entries.get().get_category_display() == "Stop"
