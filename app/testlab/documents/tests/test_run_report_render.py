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
from testlab.documents.run_report_context import build_run_report_context, report_assets

from .report_data import dual_run, single_plug_run

pytestmark = [pytest.mark.chromium, pytest.mark.django_db]

MM = 72 / 25.4
DRAFT_MARK = "DRAFT — preview, not a controlled record"


def render(run, template=None):
    context = build_run_report_context(run)
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
        "1. Test Description", "Run on water at site conditions.",  # TCN
        "2. Seal Configuration", "C100603033", "Cross section of the new parts",  # configuration
        "3. Test Conditions & Results", "Demi water", "69.5 – 71.5",  # instructed beside actual
        "4. Leakage Summary", "6.0", "not in the average",  # leakage
        "5. Logged DCS Data", "Figure 1.", "Barrier inlet temperature", "Figure 2.",  # saved plots
        "6. Events & Observations", "Cooling-water flow reduced", "Stable for the first 24 h.",
        "7. Pre-Test / Post-Test Measurements", "+0.066", "Face wear", "4.8E-6",
        "8. Pre-Test / Post-Test Pictures", "Pre-test · IB Rotor", "Post-test · IB Rotor", "Post-test · OB Stator",
        "9. Acceptance Assessment", "Not evaluated", "Visual inspection.",
        "10. Test Conclusion", "The wavy faces performed acceptably.",
        "Annex A. Manually Logged Data",
    ]:  # fmt: skip
        assert expected in text, expected
    assert "Recommendation" not in text  # empty: heading omitted


def test_pictures_and_plots_are_embedded_without_distortion(dual_pdf):
    found = [image for page in pages(dual_pdf) for image in page.images]
    # cross section 1600 × 700, 3 pictures, 2 plots 1200 × 600 (pictures: their display copies)
    sizes = sorted(image.image.size for image in found)
    assert len(found) >= 6 and (1600, 700) in sizes and sizes.count((1200, 600)) == 2


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


def test_assets_only_under_their_own_directory(dual):
    context = build_run_report_context(dual)
    with pytest.raises(pdf.PdfConversionError, match="not a valid document asset path"):
        run_report_template().render_pdf(context, {"report.css": b"body{}"})


def test_proof_samples(request, user):
    """With TESTLAB_PROOF_DIR, writes the sample reports for visual review."""
    out = os.environ.get("TESTLAB_PROOF_DIR")
    samples = {"M2C_dual-complete-DRAFT": dual_run(user),
               "M2C_single-plug-DRAFT": single_plug_run(user, project_no="2025RSD02TL")}  # fmt: skip
    for name, run in samples.items():
        data = render(run)
        assert data.startswith(b"%PDF-")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / f"{name}.pdf").write_bytes(data)
