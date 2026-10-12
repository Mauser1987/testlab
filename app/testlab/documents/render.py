"""Render controlled documents to PDF: HTML template bundles printed by headless Chromium.

The PDF is the document users see and the one stored at issue or
finalization. It is rendered from a document template, never from the
interactive pages: an HTML template bundle (body document, Chromium
header/footer templates, print CSS, logo, fonts) printed by headless
Chromium through Playwright (chromium.py). Chromium is the only renderer
(validated on Linux and on the corporate Windows workstation, M1 spec §19).

    tcn_template()          doc_templates/tcn/          Test Change Notice
    run_report_template()   doc_templates/run_report/   Test Run Report

`sha256` identifies a bundle (stored as template_sha256) and
`render_pdf(context)` prints exactly those bytes. Documents issued or
finalized earlier are stored files: they are never rendered again, so
their recorded template hashes stay valid history.
"""

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Engine, TemplateDoesNotExist, TemplateSyntaxError

from . import pdf

# Base URL of the files of an HTML template bundle; they are served from memory, never fetched.
_BUNDLE_URL = "https://template.testlab.invalid/"

# A file reference in Chromium's header/footer templates other than an inlined data: URI.
_FILE_REFERENCE = re.compile(r"""(?:\b(?:src|href|srcset)\s*=\s*|url\(\s*)(?!["']?\s*data:)""", re.IGNORECASE)


def template_path(name):
    return Path(settings.TESTLAB_TEMPLATE_DIR) / name


def tcn_template():
    """The TCN document template, read once."""
    return ChromiumTemplate.load("tcn")


class ChromiumTemplate:
    """An HTML document template bundle printed by headless Chromium (§19).

    Directory <name>/ with the body document (tcn.html for the TCN,
    report.html for the Test Run Report), header.html and footer.html
    (Chromium's header/footer templates, repeated on every page; Chromium
    fills in the page number and page count), the stylesheet, logo and
    fonts. All files are read into memory once: `sha256` is the bundle
    manifest hash and the PDF is printed from exactly those bytes; Chromium
    can load nothing outside the bundle (no network, no system fonts asked
    for by name). The HTML is rendered by a separate Django template engine
    — no request, no context processors, no access to the application's
    page templates. Header and footer cannot load files, so they inline
    bundle files with {% bundle_data_uri %}.

    `assets` passed to render_pdf are files of one document only (the
    pictures and plots of a report), served under assets/ next to the
    bundle; they are not part of the bundle or its hash.
    """

    ASSET_DIR = "assets/"

    def __init__(self, name, files, document="tcn.html"):
        self.name = name
        self.files = files  # bundle-relative POSIX path → bytes
        self.document = document

    @property
    def sha256(self):
        """SHA-256 of the bundle: of the lines "<path>\\0<SHA-256 of the file>\\n", sorted by path."""
        manifest = "".join(f"{path}\0{hashlib.sha256(data).hexdigest()}\n" for path, data in sorted(self.files.items()))
        return hashlib.sha256(manifest.encode()).hexdigest()

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
    """The Test Run Report document template (M2C), read once."""
    return ChromiumTemplate.load("run_report", document="report.html")
