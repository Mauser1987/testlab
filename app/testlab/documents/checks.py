from django.conf import settings
from django.core.checks import Warning

from .chromium import chromium_available
from .pdf import converter_available

_MISSING = {
    "libreoffice": (
        "LibreOffice (soffice) was not found: TCN PDF preview and issue will fail.",
        "Install LibreOffice, or set TESTLAB_SOFFICE to the path of soffice (soffice.com on Windows).",
    ),
    "word": (
        "Microsoft Word cannot be automated: TCN PDF preview and issue will fail.",
        'TESTLAB_PDF_CONVERTER=word needs Windows, Microsoft Word and pywin32 (pip install -e ".[word]").',
    ),
    "auto": (
        "Neither LibreOffice nor Microsoft Word was found: TCN PDF preview and issue will fail.",
        "Install LibreOffice (or set TESTLAB_SOFFICE), or on Windows Microsoft Word with pywin32.",
    ),
}


def weasyprint_check(app_configs, **kwargs):
    """`manage.py check` warns when the HTML renderer cannot load WeasyPrint (preview and issue would fail)."""
    if settings.TESTLAB_TCN_RENDERER != "html":
        return []
    try:
        import weasyprint  # noqa: F401  (loads Pango)
    except (ImportError, OSError) as error:
        return [
            Warning(
                f"WeasyPrint could not be loaded: TCN PDF preview and issue will fail ({error}).",
                hint="Linux: install the Pango library (apt install libpango-1.0-0 libpangoft2-1.0-0). "
                "Windows: install Pango with MSYS2 (see README, Windows setup).",
                id="testlab.W002",
            )
        ]
    return []


def pdf_converter_check(app_configs, **kwargs):
    """`manage.py check` warns when the docx renderer cannot convert to PDF (preview and issue would fail)."""
    if settings.TESTLAB_TCN_RENDERER != "docx" or converter_available():
        return []
    message, hint = _MISSING[settings.TESTLAB_PDF_CONVERTER]
    return [Warning(message, hint=hint, id="testlab.W001")]


def chromium_check(app_configs, **kwargs):
    """`manage.py check` warns when the chromium renderer cannot print (preview and issue would fail)."""
    if settings.TESTLAB_TCN_RENDERER != "chromium":
        return []
    reason = chromium_available()
    if reason is None:
        return []
    return [
        Warning(
            f"{reason} TCN PDF preview and issue will fail.",
            hint="In the TestLab virtualenv: pip install -e . and then python -m playwright install chromium "
            "(behind a corporate proxy the download may need the company root certificate).",
            id="testlab.W003",
        )
    ]
