"""HTML → PDF with headless Chromium through Playwright (M1 spec §19), the only PDF renderer.

Each PDF is printed by a separate worker process (chromium_print.py) that
starts its own Chromium and ends with it. The process is ended when it does
not finish within TESTLAB_PDF_TIMEOUT: page.pdf() has no timeout of its own,
and the Playwright sync API cannot be interrupted from another thread. The
worker also keeps Chromium out of the Django process.

Chromium is the browser build that Playwright downloads (`python -m
playwright install chromium`), not an installed desktop browser. It only
loads the files of the document template, served from memory; any other
request is refused and stops the printing. Every failure is reported as
PdfConversionError with what to do about it.
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from . import chromium_print
from .pdf import PdfConversionError

WORKER = Path(chromium_print.__file__)

_INSTALL_HINT = (
    f'Install it in the TestLab virtualenv with: "{sys.executable}" -m playwright install chromium '
    "(behind a corporate proxy with HTTPS inspection the download may need the company root certificate)."
)
_LINUX_LIBRARIES_HINT = (
    "Chromium is installed but cannot start: system libraries are missing. On Debian/Ubuntu run "
    f'"{sys.executable}" -m playwright install-deps chromium; on other distributions install the libraries '
    "listed in the message."
)


def print_pdf(files, document, header, footer, base_url):
    """Print `document` (a path in `files`) to PDF; returns the PDF bytes.

    files: {bundle-relative path: bytes}, the only resources the page can load
    (from `base_url`). header/footer: HTML of Chromium's header and footer
    templates (self-contained: they cannot load files). Raises
    PdfConversionError on any failure.
    """
    timeout = settings.TESTLAB_PDF_TIMEOUT
    job = {
        "base_url": base_url,
        "document": document,
        "files": {path: base64.b64encode(data).decode("ascii") for path, data in files.items()},
        "header": header,
        "footer": footer,
        "timeout_ms": timeout * 1000,
    }
    try:
        result = subprocess.run(
            [sys.executable, str(WORKER)],
            input=json.dumps(job).encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise PdfConversionError(
            f"Chromium did not finish the PDF within {timeout} seconds (TESTLAB_PDF_TIMEOUT)."
        ) from error
    except OSError as error:
        raise PdfConversionError(f"The Chromium PDF worker could not be started: {error}") from error

    message = result.stderr.decode("utf-8", "replace").strip()
    if result.returncode == chromium_print.EXIT_NOT_INSTALLED:
        raise PdfConversionError(f"{message} {_INSTALL_HINT}")
    if result.returncode != 0:
        if "missing dependencies" in message or "error while loading shared libraries" in message:
            raise PdfConversionError(f"{_LINUX_LIBRARIES_HINT} ({_first_lines(message)})")
        raise PdfConversionError(f"Chromium could not print the PDF: {_first_lines(message) or 'no reason given'}")
    if not result.stdout.startswith(b"%PDF-"):
        raise PdfConversionError("Chromium did not produce a PDF.")
    return result.stdout


def chromium_available():
    """None when Playwright and its Chromium are installed, else the reason (for checks; Chromium is not started)."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return 'Playwright is not installed (pip install -e . in the TestLab virtualenv).'
    try:
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
    except Error as error:
        return f"Playwright could not be started: {_first_lines(str(error))}"
    if not executable.is_file():
        return f"Chromium for Playwright is not installed ({executable} is missing)."
    return None


def _first_lines(message):
    """The message on one line, without Playwright's box drawing, shortened."""
    lines = (line.strip(" ║╔╚═╗╝") for line in message.splitlines())
    return " ".join(line for line in lines if line)[:600]
