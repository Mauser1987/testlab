"""PDF documents: the content type and the one error every rendering failure is reported as.

PDFs are printed by headless Chromium (chromium.py) from HTML template
bundles (render.py).
"""

PDF_CONTENT_TYPE = "application/pdf"


class PdfConversionError(Exception):
    """The PDF could not be generated; the message says why and what to do about it."""
