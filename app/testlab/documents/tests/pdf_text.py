"""PDF test helpers.

With the docx renderer, tests replace the DOCX → PDF conversion with
`fake_docx_to_pdf` (conftest.py): a fast stand-in whose output starts like a PDF and carries
the rendered DOCX, so the printed text can still be checked. Tests marked
`libreoffice` use the real conversion and real PDFs.
"""

import io

import pypdf

from .docx_text import docx_lines

_FAKE_HEAD = b"%PDF-1.7\n%TESTLAB-TEST-DOUBLE\n"
_FAKE_TAIL = b"\n%%EOF\n"


def fake_docx_to_pdf(docx):
    return _FAKE_HEAD + docx + _FAKE_TAIL


def is_real_pdf(data):
    return data.startswith(b"%PDF-") and not data.startswith(_FAKE_HEAD)


def pdf_lines(data):
    """Lines of text of a (real or stand-in) TCN PDF."""
    assert data.startswith(b"%PDF-"), "not a PDF"
    if data.startswith(_FAKE_HEAD):
        return docx_lines(data[len(_FAKE_HEAD) : -len(_FAKE_TAIL)])
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() for page in reader.pages)
    return [line.strip() for line in text.splitlines() if line.strip()]
