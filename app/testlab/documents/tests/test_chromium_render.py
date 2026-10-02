"""HTML document template → PDF with Playwright/Chromium (TESTLAB_TCN_RENDERER=chromium, M1 spec §19).

The automated proof of the Chromium renderer on the comparison samples:
AT-2 (2026RSD03TL TCN001), a multi-page TCN, AT-3 (Single + Plug Seal) and
AT-16 (Plug / Inboard / Outboard). Text regressions of the template itself
are in test_tcn_document.py (also run for chromium).

Marked `chromium`: skipped when Playwright's Chromium is not installed.
With TESTLAB_PROOF_DIR set, the sample PDFs and render timings are written
there for visual comparison.
"""

import hashlib
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pypdf
import pytest

from testlab.documents import checks, chromium, pdf
from testlab.documents.render import ChromiumTemplate, tcn_template
from testlab.documents.tcn_context import build_tcn_context
from testlab.tcn.models import TcnRevision
from testlab.tcn.services import create_tcn, issue_tcn

from .test_html_render import tcn001  # noqa: F401  (fixture)
from .test_tcn_document import single_plug_project

pytestmark = [pytest.mark.chromium, pytest.mark.django_db]

MM = 72 / 25.4  # points per millimetre
A4_MM = (210, 297)
MARGIN_MM = {"top": 28, "top_draft": 35, "right": 20, "bottom": 22, "left": 20}
DRAFT_MARK = "DRAFT — not issued"
RENDER_SECONDS_LIMIT = 10  # generous: one render is well under a second on a developer machine


def render(tcn, is_draft=False, **overrides):
    context = dict(build_tcn_context(tcn), is_draft=is_draft, **overrides)
    return ChromiumTemplate.load("tcn_chromium").render_pdf(context)


def reader(data):
    return pypdf.PdfReader(io.BytesIO(data))


def page_texts(data):
    return [page.extract_text() for page in reader(data).pages]


def text_runs(page):
    """(text, x, y) of every text run of a page, positions in points rounded to 0.01."""
    runs = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
            y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
            runs.append((text.strip(), round(x, 2), round(y, 2)))

    page.extract_text(visitor_text=visit)
    return runs


def embedded_fonts(data):
    return {
        font.get_object()["/BaseFont"].split("+")[-1]
        for page in reader(data).pages
        for font in page["/Resources"]["/Font"].values()
    }


def page_images(page):
    return [(image.image.size, hashlib.sha256(image.data).hexdigest()) for image in page.images]


def long_tcn(tcn):
    """TCN001 with a run description long enough for two pages."""
    tcn.setup.run_description = "\n".join(f"• Step {n}" for n in range(1, 50))
    tcn.setup.save()
    return tcn


def three_column_tcn(user):
    """AT-16 data: dual pressurized + Plug Seal: Plug / Inboard / Outboard seal columns."""
    from testlab.tcn.tests.factories import make_project

    project = make_project(user)
    setup = project.default_setup
    setup.plug_seal_present = True
    setup.speed = "2980"
    values = {"process": ("Crude oil", "40", "80", "12"), "seal_support": ("ISO VG 32", "70", "60", "8")}
    for circuit, (medium, pressure, temperature, flow) in values.items():
        setattr(setup, f"{circuit}_medium", medium)
        setattr(setup, f"{circuit}_pressure", pressure)
        setattr(setup, f"{circuit}_inlet_temperature", temperature)
        setattr(setup, f"{circuit}_flow", flow)
    setup.save()
    setup.positions.create(role="plug", seal_type_size="DHTW 4.750", springs="668818NL (18)")
    setup.positions.filter(role__in=["inboard", "outboard"]).update(seal_type_size="UHTW 4.750")
    return create_tcn(project, 1, user)


@pytest.fixture
def bundle(settings, tmp_path):
    """A copy of the Chromium template bundle that a test may change."""
    shutil.copytree(settings.TESTLAB_TEMPLATE_DIR / "tcn_chromium", tmp_path / "tcn_chromium")
    settings.TESTLAB_TEMPLATE_DIR = tmp_path
    return tmp_path / "tcn_chromium"


# --- Page size, margins, header and footer --------------------------------------------------


def test_tcn001_pdf_is_a4_with_header_footer_and_page_number(tcn001):
    data = render(tcn001)
    document = reader(data)
    assert len(document.pages) == 1
    # Chromium sets the paper size in steps of 1/75 in: the CSS 210 × 297 mm comes out as
    # 209.89 × 297.01 mm (format="A4" would give 210.23 × 297.35 mm).
    width, height = (float(value) / MM for value in document.pages[0].mediabox[2:])
    assert width == pytest.approx(A4_MM[0], abs=0.5) and height == pytest.approx(A4_MM[1], abs=0.5)
    text = document.pages[0].extract_text()
    for key in ["Test Change Notice", "Project No.: 2026RSD03TL", "Run/TCN No.: 001", "Page 1 of 1",
                "Prepared by: MG", "Inboard Seal", "C100603035 (SL WAVY)", "Inlet Temperature:", "60°C"]:  # fmt: skip
        assert key in text, key
    assert "DRAFT" not in text
    assert document.metadata.title == "Test Change Notice"


@pytest.mark.parametrize("is_draft", [False, True])
def test_body_stays_inside_the_margins_and_header_footer_in_them(tcn001, is_draft):
    page = reader(render(long_tcn(tcn001), is_draft=is_draft)).pages[0]
    height = float(page.mediabox[3])
    top = height - MARGIN_MM["top_draft" if is_draft else "top"] * MM
    bottom = MARGIN_MM["bottom"] * MM
    runs = text_runs(page)
    header = [run for run in runs if run[2] > top]
    footer = [run for run in runs if run[2] < bottom]
    body = [run for run in runs if bottom <= run[2] <= top]
    assert {"Test Change Notice", "Run/TCN No.: 001"} <= {text for text, _, _ in header}
    assert (DRAFT_MARK in {text for text, _, _ in header}) == is_draft
    assert any(text.startswith("Prepared by: MG") for text, _, _ in footer)
    assert body and body[0][0] == "Project Description:"
    assert min(x for _, x, _ in body) == pytest.approx(MARGIN_MM["left"] * MM, abs=1)
    assert min(x for _, x, _ in header + footer) == pytest.approx(MARGIN_MM["left"] * MM, abs=1)


def test_multi_page_tcn_repeats_header_footer_and_keeps_tables_whole(tcn001):
    data = render(long_tcn(tcn001), is_draft=True)
    texts = page_texts(data)
    assert len(texts) == 2
    for number, text in enumerate(texts, start=1):
        assert "Test Change Notice" in text and "Run/TCN No.: 001" in text and DRAFT_MARK in text
        assert "Prepared by: MG" in text and f"Page {number} of 2" in text
    # Page break: the run description continues on page 2; no table is split across pages.
    assert "• Step 1\n" in texts[0] and "• Step 49" in texts[1]
    for first, last in [("Seal Type and Size:", "Spring(s):"), ("Test Medium:", "Flow:")]:
        assert [first in text for text in texts] == [last in text for text in texts], first
    # The logo is in the header of every page.
    assert all(len(page.images) == 1 for page in reader(data).pages)


def test_only_the_bundled_fonts_are_embedded(tcn001):
    assert embedded_fonts(render(tcn001, is_draft=True)) == {"Carlito-Regular", "Carlito-Bold"}


def test_logo_is_embedded(tcn001):
    ((size, _),) = page_images(reader(render(tcn001)).pages[0])
    assert size == (495, 188)


def test_text_has_no_ligatures(tcn001):
    """"ti" of "Notice", "fl" of "Fluid" … are extracted as characters (ligatures are switched off)."""
    text = page_texts(render(tcn001))[0]
    assert "Test Change Notice" in text and "Barrier Fluid" in text and "Profile measurement" in text


# --- Comparison samples AT-3 and AT-16 -------------------------------------------------------


def test_at3_single_with_plug_seal(user):
    (text,) = page_texts(render(create_tcn(single_plug_project(user), 1, user)))
    for line in ["Plug Seal Test Seal", "Seal Type and Size: DHTW 4.750 DHTW 4.750",
                 "Spring(s): 668818NL (18) 668818NL (16)", "Process Fluid", "Test Medium: Water",
                 "Pressure: 80 barg", "Inlet Temperature: 40°C", "Flow: TBD l/min",
                 "Duration: 50 hours", "Speed: 1100 rpm"]:  # fmt: skip
        assert line in text, line
    assert "40°C°C" not in text and "Flush" not in text


def test_at16_plug_inboard_outboard_three_columns(user):
    data = render(three_column_tcn(user))
    (text,) = page_texts(data)
    for line in ["Plug Seal Inboard Seal Outboard Seal", "Seal Type and Size: DHTW 4.750 UHTW 4.750 UHTW 4.750",
                 "Process Fluid Barrier Fluid", "Test Medium: Crude oil ISO VG 32", "Pressure: 40 barg 70 barg",
                 "Inlet Temperature: 80°C 60°C", "Flow: 12 l/min 8 l/min", "Speed: 2980 rpm"]:  # fmt: skip
        assert line in text, line
    # The three seal columns share the text width: each heading starts right of the previous one.
    runs = text_runs(reader(data).pages[0])
    x = {text: x for text, x, _ in runs}
    assert x["Plug Seal"] < x["Inboard Seal"] < x["Outboard Seal"]
    assert max(x for _, x, _ in runs) < float(reader(data).pages[0].mediabox[2]) - MARGIN_MM["right"] * MM


# --- Determinism of content and layout (not of the bytes) -------------------------------------


def layout(data):
    """Everything that must not change between renders: per page the positioned text runs,
    the images (size and pixels) and the fonts. Chromium's CreationDate/ModDate differ."""
    pages = reader(data).pages
    return {
        "pages": [{"runs": text_runs(page), "images": page_images(page)} for page in pages],
        "fonts": embedded_fonts(data),
    }


@pytest.mark.parametrize("sample", ["tcn001", "tcn001-draft", "multi-page", "three-column"])
def test_content_and_layout_are_deterministic(request, user, sample):
    if sample == "three-column":
        tcn, is_draft = three_column_tcn(user), False
    else:
        tcn = request.getfixturevalue("tcn001")
        tcn, is_draft = (long_tcn(tcn), True) if sample == "multi-page" else (tcn, sample.endswith("draft"))
    first, second = render(tcn, is_draft), render(tcn, is_draft)
    assert layout(first) == layout(second)
    assert reader(first).metadata.title == reader(second).metadata.title == "Test Change Notice"


# --- Issue through the services ----------------------------------------------------------------


def test_issue_stores_the_chromium_pdf_with_its_hashes(settings, tcn001, user):
    settings.TESTLAB_TCN_RENDERER = "chromium"
    tcn = TcnRevision.objects.get(pk=tcn001.pk)
    issued = issue_tcn(tcn, tcn.row_version, user)
    with issued.issued_document.storage.open(issued.issued_document.name, "rb") as f:
        stored = f.read()
    assert issued.issued_document_sha256 == hashlib.sha256(stored).hexdigest()
    assert issued.template_sha256 == ChromiumTemplate.load("tcn_chromium").sha256
    text = page_texts(stored)[0]
    assert "Run/TCN No.: 001" in text and "DRAFT" not in text


def test_chromium_renderer_uses_the_chromium_bundle(settings):
    settings.TESTLAB_TCN_RENDERER = "chromium"
    template = tcn_template()
    assert isinstance(template, ChromiumTemplate) and template.name == "tcn_chromium"


# --- The template bundle -----------------------------------------------------------------------


def test_bundle_hash_covers_every_file(bundle):
    original = ChromiumTemplate.load("tcn_chromium")
    manifest = "".join(f"{path}\0{hashlib.sha256(data).hexdigest()}\n" for path, data in sorted(original.files.items()))
    assert original.sha256 == hashlib.sha256(manifest.encode()).hexdigest()
    assert {"tcn.html", "header.html", "footer.html", "tcn.css", "logo.jpg", "fonts/Carlito-Bold.ttf"} <= set(
        original.files
    )
    for name in ["header.html", "footer.html", "tcn.css", "fonts/Carlito-Regular.ttf"]:
        path = bundle / name
        saved = path.read_bytes()
        path.write_bytes(saved + b"\n")
        assert ChromiumTemplate.load("tcn_chromium").sha256 != original.sha256, name
        path.write_bytes(saved)


def test_pdf_is_rendered_from_the_loaded_bytes(bundle, tcn001):
    """The hash stored at issue describes what was rendered, even if the files change meanwhile."""
    template = ChromiumTemplate.load("tcn_chromium")
    context = dict(build_tcn_context(tcn001), is_draft=False)
    expected = layout(template.render_pdf(context))
    (bundle / "tcn.css").write_text("html { font-size: 30pt; }")
    (bundle / "logo.jpg").unlink()
    assert layout(template.render_pdf(context)) == expected


@pytest.mark.parametrize("part", ["tcn.html", "header.html", "footer.html"])
def test_missing_part_fails_clearly(bundle, part):
    (bundle / part).unlink()
    with pytest.raises(pdf.PdfConversionError, match=f"{part} was not found"):
        ChromiumTemplate.load("tcn_chromium")


@pytest.mark.parametrize("name", ["logo.jpg", "fonts/Carlito-Bold.ttf"])
def test_missing_bundle_file_stops_the_rendering(bundle, tcn001, name):
    (bundle / name).unlink()
    with pytest.raises(pdf.PdfConversionError, match=f"{name} is not a file of the document template"):
        render(tcn001)


@pytest.mark.parametrize(
    "replace",
    [
        ('href="tcn.css"', 'href="https://example.com/tcn.css"'),  # a stylesheet from the network
        ('href="tcn.css"', 'href="missing.css"'),  # a file the bundle does not have
        ('href="tcn.css"', 'href="file:///etc/hostname"'),  # a local file
        ("<main>", '<main><img src="https://example.com/logo.png" alt="">'),
        ("<main>", '<main><iframe src="http://192.0.2.1/"></iframe>'),
    ],
)
def test_nothing_outside_the_bundle_is_loaded(bundle, tcn001, replace):
    html = bundle / "tcn.html"
    html.write_text(html.read_text().replace(*replace))
    with pytest.raises(pdf.PdfConversionError, match="Chromium could not print the PDF: .*(not a file of the document template|Not allowed to load local resource|has been blocked)"):
        render(tcn001)


@pytest.mark.parametrize("part", ["header.html", "footer.html"])
def test_header_and_footer_cannot_load_files(bundle, tcn001, part):
    """Chromium's header/footer templates load nothing; a file reference is refused, not silently left out."""
    path = bundle / part
    path.write_text(path.read_text() + '<img src="https://example.com/logo.png">')
    with pytest.raises(pdf.PdfConversionError, match="may only use bundle files inlined"):
        render(tcn001)


def test_template_cannot_use_the_application_page_templates(bundle, tcn001):
    html = bundle / "tcn.html"
    html.write_text(html.read_text().replace("<main>", '<main>{% include "base.html" %}'))
    with pytest.raises(pdf.PdfConversionError, match="base.html"):
        render(tcn001)


# --- Failures are explicit and actionable ------------------------------------------------------


def fake_worker(tmp_path, monkeypatch, code):
    worker = tmp_path / "worker.py"
    worker.write_text(f"import sys, time\n{code}\n")
    monkeypatch.setattr(chromium, "WORKER", worker)


def test_timeout_ends_the_worker(settings, tmp_path, monkeypatch, tcn001):
    settings.TESTLAB_PDF_TIMEOUT = 1
    fake_worker(tmp_path, monkeypatch, "time.sleep(30)")
    started = time.monotonic()
    with pytest.raises(pdf.PdfConversionError, match="did not finish the PDF within 1 seconds"):
        render(tcn001)
    assert time.monotonic() - started < 10


def test_chromium_not_installed_says_how_to_install(tmp_path, monkeypatch, tcn001):
    fake_worker(tmp_path, monkeypatch, "print('Chromium for Playwright is not installed.', file=sys.stderr); sys.exit(3)")
    with pytest.raises(pdf.PdfConversionError, match="not installed. .*-m playwright install chromium"):
        render(tcn001)


def test_missing_linux_libraries_are_explained(tmp_path, monkeypatch, tcn001):
    fake_worker(tmp_path, monkeypatch, "print('Host system is missing dependencies to run browsers.', file=sys.stderr); sys.exit(2)")
    with pytest.raises(pdf.PdfConversionError, match="system libraries are missing.*install-deps"):
        render(tcn001)


def test_worker_failure_is_reported(tmp_path, monkeypatch, tcn001):
    fake_worker(tmp_path, monkeypatch, "sys.stdout.write('not a pdf')")
    with pytest.raises(pdf.PdfConversionError, match="did not produce a PDF"):
        render(tcn001)


def test_system_check_warns_when_chromium_is_missing(settings, monkeypatch):
    settings.TESTLAB_TCN_RENDERER = "chromium"
    assert checks.chromium_check(None) == []
    monkeypatch.setattr(checks, "chromium_available", lambda: "Chromium for Playwright is not installed (x).")
    (warning,) = checks.chromium_check(None)
    assert warning.id == "testlab.W003" and "playwright install chromium" in warning.hint
    settings.TESTLAB_TCN_RENDERER = "html"
    assert checks.chromium_check(None) == []


# --- Proof samples and timings -----------------------------------------------------------------


def test_proof_samples_and_timings(request, user):
    """Renders the comparison samples, checks the render time and, with TESTLAB_PROOF_DIR, writes them."""
    tcn = request.getfixturevalue("tcn001")
    samples = {
        "AT-2_2026RSD03TL-TCN001": (tcn, False),
        "AT-2_2026RSD03TL-TCN001-DRAFT": (tcn, True),
        "AT-3_2025RSD02TL-TCN001_single-plug": (create_tcn(single_plug_project(user), 1, user), False),
        "AT-16_plug-inboard-outboard": (three_column_tcn(user), False),
    }
    out = os.environ.get("TESTLAB_PROOF_DIR")
    timings = {}
    for name, (sample, is_draft) in list(samples.items()) + [("multi-page-DRAFT", (None, True))]:
        if sample is None:
            sample = long_tcn(tcn)
        started = time.perf_counter()
        data = render(sample, is_draft)
        seconds = time.perf_counter() - started
        timings[name] = {"seconds": round(seconds, 3), "pages": len(reader(data).pages), "bytes": len(data)}
        assert seconds < RENDER_SECONDS_LIMIT, name
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / f"{name}.pdf").write_bytes(data)
    if out:
        from importlib.metadata import version

        info = {"python": sys.version.split()[0], "platform": sys.platform, "playwright": version("playwright")}
        info["renders"] = timings
        (Path(out) / "timings.json").write_text(json.dumps(info, indent=2))
