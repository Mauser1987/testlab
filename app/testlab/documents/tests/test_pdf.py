"""DOCX → PDF conversion (stabilization decision S1)."""

import os
import stat

import pytest

from testlab.documents import checks, pdf
from testlab.documents.render import render_docx, template_path
from testlab.documents.tcn_context import build_tcn_context
from testlab.tcn.services import create_tcn
from testlab.tcn.tests.factories import make_project

from .pdf_text import is_real_pdf, pdf_lines

REAL_DOCX_TO_PDF = pdf.docx_to_pdf  # before conftest replaces it with the stand-in

posix_only = pytest.mark.skipif(os.name != "posix", reason="uses a shell script as a fake soffice")


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


def test_system_check_warns_without_libreoffice(monkeypatch):
    monkeypatch.setattr(checks, "soffice_available", lambda: False)
    (warning,) = checks.libreoffice_check(None)
    assert warning.id == "testlab.W001" and "TESTLAB_SOFFICE" in warning.hint
    monkeypatch.setattr(checks, "soffice_available", lambda: True)
    assert checks.libreoffice_check(None) == []


@pytest.mark.libreoffice
@pytest.mark.django_db
def test_real_conversion_of_a_tcn(user):
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

