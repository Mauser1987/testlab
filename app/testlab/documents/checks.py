from django.core.checks import Warning

from .pdf import soffice_available


def libreoffice_check(app_configs, **kwargs):
    """`manage.py check` warns when TCN PDFs cannot be generated (preview and issue would fail)."""
    if soffice_available():
        return []
    return [
        Warning(
            "LibreOffice (soffice) was not found: TCN PDF preview and issue will fail.",
            hint="Install LibreOffice, or set TESTLAB_SOFFICE to the path of soffice (soffice.com on Windows).",
            id="testlab.W001",
        )
    ]
