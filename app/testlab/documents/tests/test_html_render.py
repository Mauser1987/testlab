"""HTML document template → PDF with WeasyPrint (the default TCN renderer).

Layout text regressions (AT-2, AT-3, AT-16) are in test_tcn_document.py;
these tests cover the PDF itself and the template bundle.
"""

import hashlib
import io
import shutil
import sys

import pypdf
import pytest

from testlab.documents import checks, pdf
from testlab.documents.render import HtmlTemplate, WordTemplate, tcn_template
from testlab.documents.tcn_context import build_tcn_context
from testlab.tcn.services import create_tcn
from testlab.tcn.tests import data_2026rsd03tl
from testlab.tcn.tests.factories import make_project
from testlab.tcn.tests.test_at5_copy_chain import load_defaults

from .pdf_text import pdf_lines

A4 = (595.28, 841.89)  # points


@pytest.fixture
def tcn001(db, user):
    """2026RSD03TL TCN001 (AT-2 data)."""
    row = data_2026rsd03tl.ROWS[1]
    project = make_project(user, project_no="2026RSD03TL", description=row["ProjName"])
    load_defaults(project, 1)
    return create_tcn(project, 1, user)


@pytest.fixture
def bundle(settings, tmp_path):
    """A copy of the TCN template bundle that a test may change."""
    shutil.copytree(settings.TESTLAB_TEMPLATE_DIR / "tcn", tmp_path / "tcn")
    settings.TESTLAB_TEMPLATE_DIR = tmp_path
    return tmp_path / "tcn"


def issued_context(tcn):
    return dict(build_tcn_context(tcn), is_draft=False)


def reader(data):
    return pypdf.PdfReader(io.BytesIO(data))


# --- The PDF ----------------------------------------------------------------------------------


def test_tcn001_pdf_is_a4_with_header_footer_and_page_number(tcn001):
    data = HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))
    pages = reader(data).pages
    assert len(pages) == 1
    assert [round(float(value), 2) for value in pages[0].mediabox[2:]] == list(A4)
    text = " ".join(pdf_lines(data))
    for key in ["Test Change Notice", "Project No.: 2026RSD03TL", "Run/TCN No.: 001", "Page 1 of 1",
                "Prepared by: MG", "Inboard Seal", "C100603035 (SL WAVY)", "Inlet Temperature:", "60°C"]:  # fmt: skip
        assert key in text, key
    assert "DRAFT" not in text
    assert reader(data).metadata.title == "Test Change Notice"


def test_long_tcn_repeats_header_and_numbers_every_page(tcn001):
    tcn001.setup.run_description = "\n".join(f"• Step {n}" for n in range(1, 50))
    tcn001.setup.save()
    data = HtmlTemplate.load("tcn").render_pdf(build_tcn_context(tcn001))  # draft
    pages = reader(data).pages
    assert len(pages) == 2
    for number, page in enumerate(pages, start=1):
        text = page.extract_text()
        assert "Run/TCN No.: 001" in text and "DRAFT — not issued" in text and "Prepared by: MG" in text
        assert f"Page {number} of 2" in text


def test_only_the_bundled_fonts_are_embedded(tcn001):
    data = HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))
    fonts = set()
    for page in reader(data).pages:
        for font in page["/Resources"]["/Font"].values():
            fonts.add(font.get_object()["/BaseFont"].split("+")[-1])
    assert fonts == {"Carlito", "Carlito-Bold"}


def test_logo_is_embedded(tcn001):
    data = HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))
    (image,) = reader(data).pages[0].images
    assert image.image.size == (495, 188)


def test_output_is_deterministic(tcn001):
    context = issued_context(tcn001)
    first = HtmlTemplate.load("tcn").render_pdf(context)
    assert HtmlTemplate.load("tcn").render_pdf(context) == first
    assert b"/CreationDate" not in first and b"/ModDate" not in first


# --- The template bundle ----------------------------------------------------------------------


def test_bundle_hash_covers_every_file(bundle):
    original = HtmlTemplate.load("tcn")
    manifest = "".join(
        f"{path}\0{hashlib.sha256(data).hexdigest()}\n" for path, data in sorted(original.files.items())
    )
    assert original.sha256 == hashlib.sha256(manifest.encode()).hexdigest()
    assert {"tcn.html", "tcn.css", "logo.jpg", "fonts/Carlito-Regular.ttf"} <= set(original.files)

    for name in ["tcn.css", "fonts/Carlito-Bold.ttf"]:
        path = bundle / name
        saved = path.read_bytes()
        path.write_bytes(saved + b"\n")
        assert HtmlTemplate.load("tcn").sha256 != original.sha256, name
        path.write_bytes(saved)
    assert HtmlTemplate.load("tcn").sha256 == original.sha256


def test_pdf_is_rendered_from_the_loaded_bytes(bundle, tcn001):
    """The hash stored at issue describes what was rendered, even if the files change meanwhile."""
    context = issued_context(tcn001)
    template = HtmlTemplate.load("tcn")
    expected = template.render_pdf(context)
    (bundle / "tcn.css").write_text("html { font-size: 30pt; }")
    (bundle / "logo.jpg").unlink()
    assert template.render_pdf(context) == expected


def test_missing_bundle_file_stops_the_rendering(bundle, tcn001):
    (bundle / "logo.jpg").unlink()
    with pytest.raises(pdf.PdfConversionError, match="logo.jpg"):
        HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))


@pytest.mark.parametrize("url", ["file:///etc/hostname", "https://example.com/logo.png", "../tcn.docx"])
def test_nothing_outside_the_bundle_is_loaded(bundle, tcn001, url):
    html = bundle / "tcn.html"
    html.write_text(html.read_text().replace('src="logo.jpg"', f'src="{url}"'))
    with pytest.raises(pdf.PdfConversionError, match="not a file of the document template"):
        HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))


def test_template_cannot_use_the_application_page_templates(bundle, tcn001):
    html = bundle / "tcn.html"
    html.write_text(html.read_text().replace("<main>", '<main>{% include "base.html" %}'))
    with pytest.raises(pdf.PdfConversionError, match="base.html"):
        HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))


def test_missing_template_fails_clearly(settings, tmp_path):
    settings.TESTLAB_TEMPLATE_DIR = tmp_path
    with pytest.raises(pdf.PdfConversionError, match="tcn.html was not found"):
        HtmlTemplate.load("tcn")


def test_weasyprint_not_loadable_fails_clearly(monkeypatch, tcn001):
    monkeypatch.setitem(sys.modules, "weasyprint", None)  # import raises ImportError
    with pytest.raises(pdf.PdfConversionError, match="WeasyPrint could not be loaded"):
        HtmlTemplate.load("tcn").render_pdf(issued_context(tcn001))


# --- Renderer selection (TESTLAB_TCN_RENDERER) and checks -----------------------------------


def test_html_renderer_uses_the_html_bundle():
    assert isinstance(tcn_template(), HtmlTemplate)


def test_docx_renderer_is_still_available(settings, tcn001):
    settings.TESTLAB_TCN_RENDERER = "docx"
    template = tcn_template()
    assert isinstance(template, WordTemplate)
    assert template.sha256 == hashlib.sha256((settings.TESTLAB_TEMPLATE_DIR / "tcn.docx").read_bytes()).hexdigest()
    assert "Run/TCN No.: 001" in " ".join(pdf_lines(template.render_pdf(build_tcn_context(tcn001))))  # stand-in


def test_system_checks_follow_the_renderer(settings, monkeypatch):
    monkeypatch.setattr(checks, "converter_available", lambda: False)
    assert checks.pdf_converter_check(None) == []  # html: LibreOffice/Word not needed
    assert checks.weasyprint_check(None) == []
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    (warning,) = checks.weasyprint_check(None)
    assert warning.id == "testlab.W002" and "Pango" in warning.hint

    settings.TESTLAB_TCN_RENDERER = "docx"
    assert checks.weasyprint_check(None) == []
    (warning,) = checks.pdf_converter_check(None)
    assert warning.id == "testlab.W001"
