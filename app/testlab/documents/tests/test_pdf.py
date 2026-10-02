"""DOCX → PDF conversion of the docx renderer (transitional, TESTLAB_TCN_RENDERER=docx)."""

import os
import stat

import pytest

from testlab.documents import checks, pdf, pdf_word
from testlab.documents.render import render_docx, template_path
from testlab.documents.tcn_context import build_tcn_context
from testlab.tcn.services import create_tcn
from testlab.tcn.tests.factories import make_project

from .pdf_text import is_real_pdf, pdf_lines

REAL_DOCX_TO_PDF = pdf.docx_to_pdf  # before conftest replaces it with the stand-in

posix_only = pytest.mark.skipif(os.name != "posix", reason="uses a shell script as a fake soffice")


@pytest.fixture(autouse=True)
def libreoffice_backend(settings):
    """The LibreOffice tests below do not depend on TESTLAB_PDF_CONVERTER of the environment."""
    settings.TESTLAB_TCN_RENDERER = "docx"
    settings.TESTLAB_PDF_CONVERTER = "libreoffice"


def fake_soffice(tmp_path, script):
    path = tmp_path / "soffice"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_configured_soffice_path_is_used(settings):
    settings.TESTLAB_SOFFICE = "/opt/custom/soffice"
    assert pdf.soffice_path() == "/opt/custom/soffice"


def test_missing_soffice_fails_clearly(settings, tmp_path):
    settings.TESTLAB_SOFFICE = str(tmp_path / "no-such-soffice")
    assert not pdf.soffice_available()
    with pytest.raises(pdf.PdfConversionError, match="could not be started"):
        REAL_DOCX_TO_PDF(b"docx")


@posix_only
def test_failing_conversion_reports_the_error(settings, tmp_path):
    settings.TESTLAB_SOFFICE = fake_soffice(tmp_path, "echo 'Error: source file could not be loaded'\nexit 1\n")
    with pytest.raises(pdf.PdfConversionError, match="exit code 1.*could not be loaded"):
        REAL_DOCX_TO_PDF(b"docx")


@posix_only
def test_output_that_is_not_a_pdf_is_refused(settings, tmp_path):
    # Writes <outdir>/document.pdf with non-PDF content ($8 = outdir, $9 = source).
    settings.TESTLAB_SOFFICE = fake_soffice(tmp_path, 'mkdir -p "$8"; echo "not a pdf" > "$8/document.pdf"\n')
    with pytest.raises(pdf.PdfConversionError, match="did not produce a PDF"):
        REAL_DOCX_TO_PDF(b"docx")


@posix_only
def test_conversion_timeout_kills_libreoffice(settings, tmp_path):
    marker = tmp_path / "still-running"
    settings.TESTLAB_SOFFICE = fake_soffice(tmp_path, f"sleep 30 &\nwait\ntouch {marker}\n")
    settings.TESTLAB_PDF_TIMEOUT = 1
    with pytest.raises(pdf.PdfConversionError, match="did not finish within 1 seconds"):
        REAL_DOCX_TO_PDF(b"docx")
    assert not marker.exists()


# --- Backend selection (TESTLAB_PDF_CONVERTER) -------------------------------------------------


def converters_present(monkeypatch, libreoffice, word):
    monkeypatch.setattr(pdf, "soffice_available", lambda: libreoffice)
    monkeypatch.setattr(pdf_word, "word_available", lambda: word)


def record_backends(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf, "_libreoffice_docx_to_pdf", lambda docx: calls.append("libreoffice") or b"%PDF-lo")
    monkeypatch.setattr(pdf_word, "word_docx_to_pdf", lambda docx, timeout: calls.append(("word", timeout)) or b"%PDF-w")
    return calls


@pytest.mark.parametrize(
    "setting, libreoffice, word, expected",
    [
        ("libreoffice", False, True, "libreoffice"),  # explicit choice, even when only Word is present
        ("word", True, False, "word"),
        ("auto", True, True, "libreoffice"),  # LibreOffice preferred
        ("auto", False, True, "word"),
        ("auto", False, False, None),
    ],
)
def test_converter_selection(settings, monkeypatch, setting, libreoffice, word, expected):
    settings.TESTLAB_PDF_CONVERTER = setting
    converters_present(monkeypatch, libreoffice, word)
    assert pdf.selected_converter() == expected


def test_conversion_goes_through_the_selected_backend(settings, monkeypatch):
    calls = record_backends(monkeypatch)
    settings.TESTLAB_PDF_TIMEOUT = 45
    settings.TESTLAB_PDF_CONVERTER = "word"
    assert REAL_DOCX_TO_PDF(b"docx") == b"%PDF-w"
    settings.TESTLAB_PDF_CONVERTER = "libreoffice"
    assert REAL_DOCX_TO_PDF(b"docx") == b"%PDF-lo"
    assert calls == [("word", 45), "libreoffice"]


def test_auto_without_any_converter_fails_clearly(settings, monkeypatch):
    calls = record_backends(monkeypatch)
    settings.TESTLAB_PDF_CONVERTER = "auto"
    converters_present(monkeypatch, False, False)
    with pytest.raises(pdf.PdfConversionError, match="No PDF converter was found"):
        REAL_DOCX_TO_PDF(b"docx")
    assert calls == []


def test_unknown_converter_is_refused(settings):
    settings.TESTLAB_PDF_CONVERTER = "acrobat"
    with pytest.raises(pdf.PdfConversionError, match="Unknown TESTLAB_PDF_CONVERTER 'acrobat'"):
        REAL_DOCX_TO_PDF(b"docx")


def test_word_is_never_available_outside_windows(monkeypatch):
    monkeypatch.setattr(pdf_word.os, "name", "posix")
    assert not pdf_word.word_available()


# --- System check ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setting, libreoffice, word, hint",
    [
        ("libreoffice", False, True, "TESTLAB_SOFFICE"),
        ("word", True, False, "pywin32"),
        ("auto", False, False, "Microsoft Word"),
    ],
)
def test_system_check_warns_without_the_configured_converter(settings, monkeypatch, setting, libreoffice, word, hint):
    settings.TESTLAB_PDF_CONVERTER = setting
    converters_present(monkeypatch, libreoffice, word)
    (warning,) = checks.pdf_converter_check(None)
    assert warning.id == "testlab.W001" and hint in warning.hint
    converters_present(monkeypatch, True, True)
    assert checks.pdf_converter_check(None) == []


@pytest.mark.parametrize("backend", [pytest.param("libreoffice", marks=pytest.mark.libreoffice),
                                     pytest.param("word", marks=pytest.mark.word)])  # fmt: skip
@pytest.mark.django_db
def test_real_conversion_of_a_tcn(user, settings, backend):
    settings.TESTLAB_PDF_CONVERTER = backend
    project = make_project(user, project_no="2099RSD01TL", description="TEST UHTW 4.750")
    tcn = create_tcn(project, 1, user)
    tcn.setup.speed = "2980"
    tcn.setup.run_description = "• Start Test Unit"
    tcn.setup.save()
    data = REAL_DOCX_TO_PDF(render_docx(template_path("tcn.docx"), build_tcn_context(tcn)))
    assert is_real_pdf(data)
    text = " ".join(pdf_lines(data))
    for key in ["Test Change Notice", "Project No.: 2099RSD01TL", "Run/TCN No.: 001", "DRAFT — not issued",
                "TEST UHTW 4.750", "• Start Test Unit", "Speed: 2980 rpm", "Prepared by: MG"]:  # fmt: skip
        assert key in text, key


def test_pdf_lines_rejects_non_pdf():
    with pytest.raises(AssertionError):
        pdf_lines(b"PK\x03\x04 a docx")

