"""Text of a generated DOCX in reading order, for regression comparisons (AT-2)."""

import io

from docx import Document
from docx.oxml.ns import qn


def docx_lines(data):
    """Non-empty lines: header, body, footer; a table row is one line (cells joined by spaces)."""
    document = Document(io.BytesIO(data))
    section = document.sections[0]
    lines = []
    for part in (section.header._element, document.element.body, section.footer._element):
        lines += _block_lines(part)
    return [line for line in lines if line]


def normalized(lines):
    """Whitespace-normalised text (line breaks and repeated spaces are layout, not content)."""
    return " ".join(" ".join(lines).split())


def _block_lines(element):
    lines = []
    for child in element.iterchildren():
        if child.tag == qn("w:p"):
            lines.append(_text(child))
        elif child.tag == qn("w:tbl"):
            for row in child.iter(qn("w:tr")):
                cells = [" ".join(_block_lines(cell)) for cell in row.iter(qn("w:tc"))]
                lines.append(" ".join(cell for cell in cells if cell))
    return lines


def _text(paragraph):
    return "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
