"""PDF test helpers.

Tests not marked `chromium` replace Chromium's printing with
`fake_print_pdf` (conftest.py): a fast stand-in whose output starts like a
PDF and carries the rendered HTML (header, document, footer), so the
printed text can still be checked. Tests marked `chromium` print real PDFs.
"""

import io

import pypdf

from .html_text import html_lines

_FAKE_HEAD = b"%PDF-1.7\n%TESTLAB-TEST-DOUBLE\n"
_FAKE_TAIL = b"\n%%EOF\n"


def fake_print_pdf(files, document, header, footer, base_url):
    html = files[document].decode("utf-8")
    html = html.replace("<main>", header + "<main>", 1).replace("</main>", "</main>" + footer, 1)
    return _FAKE_HEAD + html.encode("utf-8") + _FAKE_TAIL


def is_real_pdf(data):
    return data.startswith(b"%PDF-") and not data.startswith(_FAKE_HEAD)


def pdf_lines(data):
    """Lines of text of a (real or stand-in) PDF."""
    assert data.startswith(b"%PDF-"), "not a PDF"
    if data.startswith(_FAKE_HEAD):
        lines = html_lines(data[len(_FAKE_HEAD) : -len(_FAKE_TAIL)].decode("utf-8"))
        return [line.replace(" Page of ", " ") for line in lines]  # Chromium fills in the numbers
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() for page in reader.pages)
    return [line.strip() for line in text.splitlines() if line.strip()]
