from django.core.checks import Warning

from .chromium import chromium_available


def chromium_check(app_configs, **kwargs):
    """`manage.py check` warns when Chromium cannot print (TCN and report PDFs would fail)."""
    reason = chromium_available()
    if reason is None:
        return []
    return [
        Warning(
            f"{reason} TCN and Test Run Report PDFs (preview, issue, finalization) will fail.",
            hint="In the TestLab virtualenv: pip install -e . and then python -m playwright install chromium "
            "(behind a corporate proxy the download may need the company root certificate).",
            id="testlab.W003",
        )
    ]
