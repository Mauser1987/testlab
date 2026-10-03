"""Render the TCN document (M1 spec §9.1, stabilization decision S1).

The PDF is the document users see and the one stored at issue. It is
rendered from a document template, never from the interactive pages:

- HTML (default): an HTML template bundle with print CSS, rendered
  directly to PDF by WeasyPrint (HtmlTemplate).
- Chromium (TESTLAB_TCN_RENDERER=chromium, under validation, §19): an HTML
  template bundle with Chromium header/footer templates, printed by headless
  Chromium through Playwright (ChromiumTemplate, chromium.py). Intended to
  become the only renderer, replacing the other two.
- DOCX (TESTLAB_TCN_RENDERER=docx, transitional): Word template (docxtpl)
  → temporary DOCX → PDF (LibreOffice or Word, pdf.py). Kept until
  WeasyPrint is proven on the Windows workstations, then removed.

tcn_template() returns the configured template; `sha256` identifies it
(stored as template_sha256) and `render_pdf(context)` renders exactly
those bytes.
"""

import hashlib
import io
import re
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.template import Context, Engine, TemplateDoesNotExist, TemplateSyntaxError
from docxtpl import DocxTemplate
from lxml import etree

from . import pdf

# Base URL of the files of an HTML template bundle; they are served from memory, never fetched.
_BUNDLE_URL = "https://template.testlab.invalid/"

# A file reference in Chromium's header/footer templates other than an inlined data: URI.
_FILE_REFERENCE = re.compile(r"""(?:\b(?:src|href|srcset)\s*=\s*|url\(\s*)(?!["']?\s*data:)""", re.IGNORECASE)

# Fixed, not from the mimetypes module: on Windows that reads the registry, which varies per machine.
_CONTENT_TYPES = {
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def template_path(name):
    return Path(settings.TESTLAB_TEMPLATE_DIR) / name


def tcn_template():
    """The TCN document template of the configured renderer, read once."""
    if settings.TESTLAB_TCN_RENDERER == "docx":
        return WordTemplate.load("tcn.docx")
    if settings.TESTLAB_TCN_RENDERER == "chromium":
        return ChromiumTemplate.load("tcn_chromium")
    return HtmlTemplate.load("tcn")


class HtmlTemplate:
    """An HTML document template bundle: directory <name>/ with <name>.html, its stylesheet, images and fonts.

    All files are read into memory once: the PDF is rendered from exactly the
    bytes `sha256` describes, and nothing outside the bundle is loaded (no
    network, no system fonts asked for by name). The HTML is rendered by a
    separate Django template engine — no request, no context processors, no
    access to the application's page templates.
    """

    def __init__(self, name, files):
        self.name = name
        self.files = files  # bundle-relative POSIX path → bytes

    @classmethod
    def load(cls, name):
        root = template_path(name)
        files = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        if f"{name}.html" not in files:
            raise pdf.PdfConversionError(f"The document template {root / (name + '.html')} was not found.")
        return cls(name, files)

    @property
    def sha256(self):
        """SHA-256 of the bundle: of the lines "<path>\\0<SHA-256 of the file>\\n", sorted by path."""
        manifest = "".join(f"{path}\0{hashlib.sha256(data).hexdigest()}\n" for path, data in sorted(self.files.items()))
        return hashlib.sha256(manifest.encode()).hexdigest()

    def render_html(self, context):
        source = self.files[f"{self.name}.html"].decode("utf-8")
        return Engine(autoescape=True).from_string(source).render(Context(context))

    def render_pdf(self, context):
        """The PDF as bytes; raises pdf.PdfConversionError when it cannot be rendered."""
        try:
            # Imported on use: it loads Pango, and the DOCX renderer must work without it (transitional).
            import weasyprint
            from weasyprint.text.fonts import FontConfiguration
            from weasyprint.urls import FatalURLFetchingError, URLFetcher, URLFetcherResponse
        except (ImportError, OSError) as error:
            raise pdf.PdfConversionError(f"WeasyPrint could not be loaded: {error}") from error

        files = self.files

        class BundleFetcher(URLFetcher):
            def fetch(self, url, headers=None):
                path = url.removeprefix(_BUNDLE_URL)
                if not url.startswith(_BUNDLE_URL) or path not in files:
                    raise ValueError(f"{url} is not a file of the document template")
                content_type = _CONTENT_TYPES.get(PurePosixPath(path).suffix.lower(), "application/octet-stream")
                return URLFetcherResponse(url, files[path], {"Content-Type": content_type})

        try:
            html = weasyprint.HTML(
                string=self.render_html(context),
                base_url=_BUNDLE_URL,
                url_fetcher=BundleFetcher(fail_on_errors=True),  # a missing logo or font stops the rendering
            )
            return html.write_pdf(font_config=FontConfiguration())
        except (Exception, FatalURLFetchingError) as error:
            reason = f"{error} ({error.__cause__})" if error.__cause__ else str(error)  # the fetcher's reason
            raise pdf.PdfConversionError(f"The PDF could not be rendered: {reason}") from error


class ChromiumTemplate(HtmlTemplate):
    """An HTML document template bundle printed by headless Chromium (§19).

    Directory <name>/ with the body document (tcn.html for the TCN,
    report.html for the Test Run Report), header.html and footer.html
    (Chromium's header/footer templates, repeated on every page; Chromium
    fills in the page number and page count), the stylesheet, logo and
    fonts. Same model as HtmlTemplate: all files are read once, `sha256` is
    the bundle manifest hash, and the PDF is printed from exactly those
    bytes; Chromium can load nothing outside the bundle. Header and footer
    cannot load files, so they inline bundle files with {% bundle_data_uri %}.

    `assets` passed to render_pdf are files of one document only (the
    pictures and plots of a report), served under assets/ next to the
    bundle; they are not part of the bundle or its hash.
    """

    ASSET_DIR = "assets/"

    def __init__(self, name, files, document="tcn.html"):
        super().__init__(name, files)
        self.document = document

    @property
    def parts(self):
        return (self.document, "header.html", "footer.html")

    @classmethod
    def load(cls, name, document="tcn.html"):
        root = template_path(name)
        files = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        for part in (document, "header.html", "footer.html"):
            if part not in files:
                raise pdf.PdfConversionError(f"The document template {root / part} was not found.")
        return cls(name, files, document)

    def render_parts(self, context):
        """The rendered document, header.html and footer.html."""
        engine = Engine(autoescape=True, builtins=["testlab.documents.bundle_tags"])
        engine.bundle_files = self.files  # for {% bundle_data_uri %}
        return [engine.from_string(self.files[part].decode("utf-8")).render(Context(context)) for part in self.parts]

    def render_html(self, context):
        """Header, body and footer as one HTML text (for text regressions; never printed like this)."""
        document, header, footer = self.render_parts(context)
        return document.replace("<main>", header + "<main>", 1).replace("</main>", "</main>" + footer, 1)

    def render_pdf(self, context, assets=None):
        """The PDF as bytes; raises pdf.PdfConversionError when it cannot be rendered."""
        from . import chromium

        try:
            document, header, footer = self.render_parts(context)
        except (TemplateSyntaxError, TemplateDoesNotExist) as error:
            raise pdf.PdfConversionError(f"The document template could not be rendered: {error}") from error
        for part, html in (("header.html", header), ("footer.html", footer)):
            if _FILE_REFERENCE.search(html):
                raise pdf.PdfConversionError(
                    f"{part} may only use bundle files inlined with {{% bundle_data_uri %}}: "
                    "Chromium's header and footer templates cannot load files."
                )
        files = dict(self.files, **{self.document: document.encode("utf-8")})
        for path, data in (assets or {}).items():
            if not path.startswith(self.ASSET_DIR) or path in files:
                raise pdf.PdfConversionError(f"{path} is not a valid document asset path.")
            files[path] = data
        return chromium.print_pdf(files, self.document, header, footer, base_url=_BUNDLE_URL)


def run_report_template():
    """The Test Run Report document template (M2C): Chromium only."""
    return ChromiumTemplate.load("run_report", document="report.html")


class WordTemplate:
    """The Word template of the DOCX renderer (transitional, see the module docstring)."""

    def __init__(self, data):
        self.data = data

    @classmethod
    def load(cls, name):
        return cls(template_path(name).read_bytes())

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def render_pdf(self, context):
        return pdf.docx_to_pdf(render_docx(io.BytesIO(self.data), context))


def render_docx(template, context):
    """Render `template` (a path or a file object) with `context`; returns the DOCX as bytes.

    Internal step of WordTemplate.render_pdf; also used by the layout regression tests.
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
