"""Drag and drop of instrument files on "Add measurement" (M2F-a), in Chromium.

The page script only fills the ordinary file fields; the server checks the
files as for a chosen file. Marked `chromium`: skipped when Playwright's
Chromium is not installed.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import sync_playwright

from testlab.results import services
from testlab.results.models import FaceMeasurement

from .facemeasure_variants import MAHR_LEFT, MAHR_RIGHT, ROUNDPAK_CSV, fixture_text
from .helpers import make_run

pytestmark = [pytest.mark.chromium, pytest.mark.django_db(transaction=True)]

DROP = """([selector, files]) => {
  const dt = new DataTransfer();
  for (const f of files) dt.items.add(new File([f.text], f.name, {type: 'text/plain'}));
  const target = document.querySelector(selector);
  for (const type of ['dragover', 'drop']) target.dispatchEvent(new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
}"""
CHOSEN = "name => { const i = document.querySelector(`input[name=\"${name}\"]`); return i.files.length ? i.files[0].name : null; }"


def file(name, text=None):
    return {"name": name, "text": fixture_text(name) if text is None else text}


@pytest.fixture
def stator(user):
    result = services.create_result(make_run(user, "dual_pressurized"), user)
    return next(c for c in result.components.all() if c.label == "IB Stator")


@pytest.fixture
def page(live_server, client, user, monkeypatch):
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")  # ORM checks while Playwright's loop runs (test only)
    client.force_login(user)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.add_cookies([{"name": "sessionid", "value": client.cookies["sessionid"].value, "url": live_server.url}])
        yield context.new_page()
        browser.close()


def open_add(page, live_server, stator, kind):
    url = reverse("results:measurement_add", args=[stator.pk])
    page.goto(f"{live_server.url}{url}?kind={kind}&stage=pre")
    page.wait_for_selector(".file-drop:not([hidden])")


def test_both_mahr_files_dropped_at_once_go_to_their_side_and_upload(page, live_server, stator):
    open_add(page, live_server, stator, "mahr")
    page.evaluate(DROP, [".file-drop", [file(MAHR_RIGHT), file(MAHR_LEFT)]])  # right first: placed by name
    assert page.evaluate(CHOSEN, "left_file") == MAHR_LEFT and page.evaluate(CHOSEN, "right_file") == MAHR_RIGHT
    assert MAHR_LEFT in page.text_content(".file-drop-status")
    page.fill('input[name="od"]', "5.034")
    page.fill('input[name="id"]', "4.634")
    page.click("text=Upload and calculate")
    page.wait_for_url("**/measurements/**")
    m = FaceMeasurement.objects.get()
    assert {f.role: f.original_name for f in m.files.all()} == {"mahr_left": MAHR_LEFT, "mahr_right": MAHR_RIGHT}


def test_names_without_a_side_letter_keep_their_order_and_a_field_takes_its_own_file(page, live_server, stator):
    open_add(page, live_server, stator, "mahr")
    page.evaluate(DROP, [".file-drop", [file("scan-a.txt", "x"), file("scan-b.txt", "y")]])
    assert (page.evaluate(CHOSEN, "left_file"), page.evaluate(CHOSEN, "right_file")) == ("scan-a.txt", "scan-b.txt")
    page.evaluate(DROP, ['.field:has(input[name="right_file"])', [file(MAHR_LEFT)]])  # the field decides, not the name
    assert page.evaluate(CHOSEN, "right_file") == MAHR_LEFT and page.evaluate(CHOSEN, "left_file") == "scan-a.txt"


def test_wrong_file_type_or_too_many_files_place_nothing(page, live_server, stator):
    open_add(page, live_server, stator, "mahr")
    page.evaluate(DROP, [".file-drop", [file(ROUNDPAK_CSV), file(MAHR_LEFT)]])
    assert "not a .TXT file. Nothing was placed." in page.text_content(".file-drop-status")
    page.evaluate(DROP, [".file-drop", [file("a.txt", "1"), file("b.txt", "2"), file("c.txt", "3")]])
    assert "at most 2 files" in page.text_content(".file-drop-status")
    assert page.evaluate(CHOSEN, "left_file") is None and page.evaluate(CHOSEN, "right_file") is None


def test_choose_both_files_in_one_dialog(page, live_server, stator):
    open_add(page, live_server, stator, "mahr")
    page.set_input_files(".file-drop-picker", files=[
        {"name": MAHR_RIGHT, "mimeType": "text/plain", "buffer": b"r"},
        {"name": MAHR_LEFT, "mimeType": "text/plain", "buffer": b"l"},
    ])  # fmt: skip
    assert page.evaluate(CHOSEN, "left_file") == MAHR_LEFT and page.evaluate(CHOSEN, "right_file") == MAHR_RIGHT


def test_roundpak_csv_dropped_and_uploaded(page, live_server, stator):
    open_add(page, live_server, stator, "roundpak")
    page.evaluate(DROP, [".file-drop", [file(ROUNDPAK_CSV)]])
    assert page.evaluate(CHOSEN, "file") == ROUNDPAK_CSV
    page.click("text=Upload and calculate")
    page.wait_for_url("**/measurements/**")
    assert FaceMeasurement.objects.get().files.get().original_name == ROUNDPAK_CSV
