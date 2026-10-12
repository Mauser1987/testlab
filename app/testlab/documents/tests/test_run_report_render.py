"""Test Run Report PDF printed by Chromium (M2C).

Marked `chromium`: skipped when Playwright's Chromium is not installed.
With TESTLAB_PROOF_DIR set, the sample reports are written there for review.
"""

import io
import os
import re
import shutil
from pathlib import Path

import pypdf
import pytest

from testlab.documents import pdf
from testlab.documents.render import ChromiumTemplate, run_report_template
from testlab.documents.report_profiles import present
from testlab.documents.run_report_context import build_run_report_context, report_assets

from .report_data import dcs_running_run, dual_run, single_plug_run

pytestmark = [pytest.mark.chromium, pytest.mark.django_db]

MM = 72 / 25.4
DRAFT_MARK = "DRAFT — preview, not a controlled record"


def render(run, template=None, final=None, profile="engineering", document=None):
    """The report of a profile (Engineering: the complete technical detail, as before M2F-B)."""
    record = build_run_report_context(run, final=final)
    context = present(record, profile, document=document)
    return (template or run_report_template()).render_pdf(context, report_assets(context))


def pages(data):
    return pypdf.PdfReader(io.BytesIO(data)).pages


def texts(data):
    return [page.extract_text() for page in pages(data)]


@pytest.fixture
def dual(user):
    return dual_run(user)


@pytest.fixture
def dual_pdf(dual):
    return render(dual)


def test_a4_portrait_with_header_footer_draft_and_page_x_of_y_on_every_page(dual_pdf):
    document = pages(dual_pdf)
    assert len(document) >= 2
    for number, page in enumerate(document, start=1):
        width, height = (float(value) / MM for value in page.mediabox[2:])
        assert width == pytest.approx(210, abs=0.5) and height == pytest.approx(297, abs=0.5)
        text = page.extract_text()
        assert "Test Run Report" in text and "Project No.: 2026RSD03TL" in text and "Run 001 · TCN001" in text
        assert DRAFT_MARK in text, number
        assert f"Page {number} of {len(document)}" in text


def test_report_text_from_every_source(dual_pdf):
    text = "\n".join(texts(dual_pdf))
    for expected in [
        "Run 001", "ADNOC", "Dual Pressurized", "UHTW 4.750",  # identification
        "Wavy-face qualification on water", "Prepared by", "Maria Geerts",  # Test Program title, engineer
        "Elapsed clock time", "Shaft-running hours", "36.00 h",
        "1. Objective", "Demonstrate the leakage and wear performance", "Run 001: first 24 h",  # Program + run
        "2. Test Description", "Run on water at site conditions.",  # TCN
        "3. Seal Configuration", "C100603033", "Cross section of the new parts", "IB Backing ring",  # configuration
        "4. Test Conditions & Results", "Demi water", "69.5 – 71.5", "Duration, shaft running",  # instructed beside actual
        "5. Leakage Summary", "6.0", "not in the average", "Average dynamic leakage", "Cumulative collected volume",
        "6. Logged DCS Data", "Figure 1.", "Barrier inlet temperature", "Figure 2.",  # saved plots
        "7. Events & Observations", "Cooling-water flow reduced", "Stable for the first 24 h.",
        "8. Pre-Test / Post-Test Measurements", "Face flatness (circular trace)", "ROUNDPAK", "Face wear", "3.33E-6",
        "Dimension: Thickness", "Light fretting marks",  # optional component and its observation
        "9. Seal Face Measurements", "IB Stator — Mahr profile / roughness", "Instrument check result",
        "JRO-003L.TXT",
        "10. Pre-Test / Post-Test Pictures", "Pre-test · IB Rotor", "Post-test · IB Rotor", "Post-test · OB Stator",
        "Post-test · IB Backing ring",
        "11. Acceptance Assessment", "TP-2026-03 rev B P1", "Visual inspection.",
        "12. Test Conclusion", "The wavy faces performed acceptably.",
        "Annex A. Manually Logged Data",
    ]:  # fmt: skip
        assert expected in text, expected
    assert "Recommendation" not in text  # empty: heading omitted


def test_final_report_has_no_draft_marking(dual, user):
    from django.utils import timezone

    issued = {"identity": "2026RSD03TL-Run001-TRR-R0-E", "revision": 0, "status": "Issued", "issued_on": "09-Oct-2026",
              "issued_at": "09-Oct-2026 12:48"}  # fmt: skip
    document = texts(render(dual, final={"by": user, "at": timezone.now()}, document=issued))
    text = "\n".join(document)
    assert "DRAFT" not in text and "PREVIEW" not in text and "Preview generated" not in text
    assert "finalized by Maria Geerts" in " ".join(text.split())
    for number, page in enumerate(document, start=1):
        assert "2026RSD03TL-Run001-TRR-R0-E · Issued" in page and f"Page {number} of {len(document)}" in page


def test_pictures_and_plots_are_embedded_without_distortion(dual_pdf):
    found = [image for page in pages(dual_pdf) for image in page.images]
    # cross section 1600 × 700, 4 pictures, 2 plots 1200 × 600 (pictures: their display copies)
    sizes = sorted(image.image.size for image in found)
    assert len(found) >= 7 and (1600, 700) in sizes and sizes.count((1200, 600)) == 2


def test_only_the_bundled_fonts_are_embedded(dual_pdf):
    fonts = {
        font.get_object()["/BaseFont"].split("+")[-1]
        for page in pages(dual_pdf)
        for font in page["/Resources"]["/Font"].values()
    }
    assert fonts and all(name.startswith("Carlito") for name in fonts), fonts


def test_multi_page_manual_log_repeats_its_header_and_keeps_rows_whole(user):
    run = dual_run(user, readings=90)
    document = texts(render(run))
    annex = [i for i, text in enumerate(document) if "Annex A. Manually Logged Data" in text][0]
    log_pages = document[annex:]
    assert len(log_pages) >= 2
    for text in log_pages:
        assert "Date / time" in text and "Elapsed" in text  # table header on every page
    rows = [line for text in log_pages for line in text.splitlines() if re.match(r"\d\d-\w\w\w-\d{4} \d\d:\d\d", line)]
    assert len(rows) == 91  # every entry once, none split over two pages


def test_single_with_plug_seal_report(user):
    text = "\n".join(texts(render(single_plug_run(user))))
    for expected in ["Single", "Process fluid", "Crude oil", "Plug Seal", "Test Seal", "Post-test · Plug Rotor",
                     "Face wear", "Test Rotor"]:  # fmt: skip
        assert expected in text, expected


def test_partial_result_renders(user):
    from testlab.results import services
    from testlab.results.tests.helpers import make_run

    run = make_run(user, "dual_pressurized")
    services.create_result(run, user)
    text = "\n".join(texts(render(run)))
    assert "Run 001" in text and DRAFT_MARK in text and "Annex A" not in text and "Leakage Summary" not in text


@pytest.fixture
def bundle(settings, tmp_path):
    shutil.copytree(Path(settings.TESTLAB_TEMPLATE_DIR) / "run_report", tmp_path / "run_report")
    settings.TESTLAB_TEMPLATE_DIR = tmp_path
    return tmp_path / "run_report"


@pytest.mark.parametrize("reference", ['<img src="https://example.com/logo.png">', '<link rel="stylesheet" href="file:///etc/x.css">'])
def test_nothing_outside_the_bundle_is_loaded(bundle, dual, reference):
    report = bundle / "report.html"
    report.write_text(report.read_text(encoding="utf-8").replace("<main>", "<main>" + reference, 1), encoding="utf-8")
    with pytest.raises(pdf.PdfConversionError, match="not a file of the document template|could not be loaded"):
        render(dual, ChromiumTemplate.load("run_report", document="report.html"))


def test_dcs_running_report(user):
    text = "\n".join(texts(render(dcs_running_run(user))))
    for expected in ["Recording", "79.00 h", "Shaft running", "76.74 h · 2 intervals", "PROVISIONAL", "† Provisional",
                     "Parameter Unit TCN (Instructed) Actual Source", "DCS · Motor Speed", "DCS · X12 PT Barrier",
                     "29.8 – 31.0", "(n=27626)", "not a steady-state range"]:  # fmt: skip
        assert expected in text, expected


def test_assets_only_under_their_own_directory(dual):
    context = build_run_report_context(dual)
    with pytest.raises(pdf.PdfConversionError, match="not a valid document asset path"):
        run_report_template().render_pdf(context, {"report.css": b"body{}"})


def test_proof_samples(request, user):
    """With TESTLAB_PROOF_DIR, writes the sample reports for visual review."""
    out = os.environ.get("TESTLAB_PROOF_DIR")
    from django.utils import timezone

    dual = dual_run(user)
    samples = {"M2E_dual-complete-DRAFT": (dual, None),
               "M2E_dual-complete-FINAL-look": (dual, {"by": user, "at": timezone.now()}),
               "M2E_single-plug-DRAFT": (single_plug_run(user, project_no="2025RSD02TL"), None),
               "M2E_dcs-running-provisional-DRAFT": (dcs_running_run(user), None),
               "M2E_dcs-running-confirmed-DRAFT": (dcs_running_run(user, confirm=True, project_no="2026RSD08TL"), None)}  # fmt: skip
    for name, (run, final) in samples.items():
        data = render(run, final=final)
        assert data.startswith(b"%PDF-")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / f"{name}.pdf").write_bytes(data)
