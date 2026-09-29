"""Render the TCN document (M1 spec §9.1, stabilization decision S1).

Pipeline: context → Word template (docxtpl) → temporary DOCX → PDF
(LibreOffice, pdf.py). The PDF is the document users see and the one
stored at issue; the DOCX is an internal intermediate and is never served.
"""

import io
from pathlib import Path

from django.conf import settings
from docxtpl import DocxTemplate
from lxml import etree

from . import pdf


def template_path(name):
    return Path(settings.TESTLAB_TEMPLATE_DIR) / name


def render_pdf(template, context):
    """Render `template` with `context` and convert it; returns the PDF as bytes.

    Raises pdf.PdfConversionError when the PDF cannot be generated.
    """
    return pdf.docx_to_pdf(render_docx(template, context))


def render_docx(template, context):
    """Render `template` (a path or a file object) with `context`; returns the DOCX as bytes.

    Internal step of render_pdf; also used by the layout regression tests.
    """
    document = _Template(template)
    document.render(context, autoescape=True)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


class _Template(DocxTemplate):
    def fix_tables(self, xml):
        """Keep the column widths set in Word when a column loop yields fewer columns.

        docxtpl removes the unused grid columns but stretches the remaining ones
        to the old table width; a TCN with two seal columns would then get a wider
        label column than one with three. Here the unused columns are only dropped.
        """
        tree = etree.fromstring(xml, etree.XMLParser(recover=True))
        ns = "{%s}" % tree.nsmap["w"]
        for table in tree.iter(ns + "tbl"):
            grid = table.find(ns + "tblGrid")
            columns = grid.findall(ns + "gridCol")
            used = max((_row_width(row, ns) for row in table.findall(ns + "tr")), default=len(columns))
            if used > len(columns):  # more cells than the grid: docxtpl's own handling
                return super().fix_tables(xml)
            for column in columns[used:]:
                grid.remove(column)
        return tree


def _row_width(row, ns):
    width = 0
    for cell in row.findall(ns + "tc"):
        span = cell.find(f"{ns}tcPr/{ns}gridSpan")
        width += 1 if span is None else int(span.get(ns + "val"))
    return width
