"""DOCX → PDF conversion with LibreOffice headless (stabilization decision S1).

The controlled TCN document is a PDF. Layout stays in the Word template
(render.py renders it with docxtpl); this module turns the rendered DOCX
into the PDF that is previewed, stored at issue and downloaded. The DOCX
only exists in a temporary directory during the conversion.

LibreOffice runs as a separate process per conversion with its own
temporary user profile, so concurrent conversions and a desktop LibreOffice
of the same account do not interfere. No Microsoft Office is involved.

Configuration: TESTLAB_SOFFICE (path of the soffice executable; found on
PATH or in the usual install locations when not set) and
TESTLAB_PDF_TIMEOUT (seconds).
"""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

PDF_CONTENT_TYPE = "application/pdf"

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


def docx_to_pdf(docx):
    """Convert DOCX bytes to PDF bytes; raises PdfConversionError on any failure."""
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
