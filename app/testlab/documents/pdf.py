"""DOCX → PDF conversion (stabilization decision S1).

The controlled TCN document is a PDF. Layout stays in the Word template
(render.py renders it with docxtpl); this module turns the rendered DOCX
into the PDF that is previewed, stored at issue and downloaded. The DOCX
only exists in a temporary directory during the conversion.

The backend is chosen with TESTLAB_PDF_CONVERTER:

- `libreoffice` (default, the Linux server): LibreOffice headless, below.
- `word`: Microsoft Word through COM automation (pdf_word.py), optional for
  Windows workstations where LibreOffice cannot be installed.
- `auto`: LibreOffice when found, otherwise Word.

Every backend is reached through docx_to_pdf and reports any failure as
PdfConversionError.

LibreOffice runs as a separate process per conversion with its own
temporary user profile, so concurrent conversions and a desktop LibreOffice
of the same account do not interfere.

Configuration: TESTLAB_PDF_CONVERTER, TESTLAB_SOFFICE (path of the soffice
executable; found on PATH or in the usual install locations when not set)
and TESTLAB_PDF_TIMEOUT (seconds, every backend).
"""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from . import pdf_word

PDF_CONTENT_TYPE = "application/pdf"

CONVERTERS = ("libreoffice", "word", "auto")

# Usual install locations when soffice is not on PATH.
_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/opt/libreoffice/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


class PdfConversionError(Exception):
    """The PDF could not be generated."""


def soffice_path():
    """The soffice executable to use, or None when LibreOffice is not found."""
    configured = settings.TESTLAB_SOFFICE
    if configured:
        return configured
    # On Windows soffice.com is the console variant: it waits and reports errors.
    for name in ("soffice.com", "soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return next((path for path in _CANDIDATES if Path(path).is_file()), None)


def soffice_available():
    """True when the configured or found soffice exists (for checks; conversion reports its own errors)."""
    path = soffice_path()
    return bool(path) and (Path(path).is_file() or shutil.which(path) is not None)


def selected_converter():
    """The backend of the next conversion (`libreoffice` or `word`); None when `auto` finds neither."""
    converter = settings.TESTLAB_PDF_CONVERTER
    if converter not in CONVERTERS:
        raise PdfConversionError(
            f"Unknown TESTLAB_PDF_CONVERTER {converter!r}; use one of: {', '.join(CONVERTERS)}."
        )
    if converter != "auto":
        return converter
    if soffice_available():
        return "libreoffice"
    if pdf_word.word_available():
        return "word"
    return None


def converter_available():
    """True when the configured backend can be used (for checks; conversion reports its own errors)."""
    converter = selected_converter()
    if converter == "word":
        return pdf_word.word_available()
    return converter == "libreoffice" and soffice_available()


def docx_to_pdf(docx):
    """Convert DOCX bytes to PDF bytes with the configured backend; raises PdfConversionError on any failure."""
    converter = selected_converter()
    if converter == "word":
        return pdf_word.word_docx_to_pdf(docx, settings.TESTLAB_PDF_TIMEOUT)
    if converter is None:
        raise PdfConversionError(
            "No PDF converter was found: install LibreOffice, or Microsoft Word with pywin32 on Windows."
        )
    return _libreoffice_docx_to_pdf(docx)


def _libreoffice_docx_to_pdf(docx):
    soffice = soffice_path()
    if not soffice:
        raise PdfConversionError("LibreOffice (soffice) was not found; set TESTLAB_SOFFICE to its path.")
    with tempfile.TemporaryDirectory(prefix="testlab-pdf-") as work:
        work = Path(work)
        source = work / "document.docx"
        source.write_bytes(docx)
        command = [
            soffice,
            f"-env:UserInstallation={(work / 'profile').as_uri()}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(work / "out"),
            str(source),
        ]
        returncode, output = _run(command, settings.TESTLAB_PDF_TIMEOUT)
        target = work / "out" / "document.pdf"
        if returncode != 0 or not target.is_file():
            detail = output.decode(errors="replace").strip()
            raise PdfConversionError(
                f"LibreOffice could not convert the document (exit code {returncode})"
                + (f": {detail[-500:]}" if detail else ".")
            )
        pdf = target.read_bytes()
    if not pdf.startswith(b"%PDF-"):
        raise PdfConversionError("LibreOffice did not produce a PDF file.")
    return pdf


def _run(command, timeout):
    """Run soffice in its own process group; on timeout the whole group is killed."""
    if os.name == "posix":
        group = {"start_new_session": True}
    else:
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group)
    except OSError as error:
        raise PdfConversionError(f"LibreOffice could not be started ({command[0]}): {error}") from error
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _kill_tree(process)
        process.communicate()
        raise PdfConversionError(f"LibreOffice did not finish within {timeout} seconds.") from error
    return process.returncode, output


def _kill_tree(process):
    # soffice starts soffice.bin as a child; killing only the parent would leave it running.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    process.kill()
