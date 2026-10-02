"""Template tags of HTML document template bundles (render.py), not of the application pages."""

import base64
from pathlib import PurePosixPath

from django import template

from .chromium_print import content_type

register = template.Library()


@register.simple_tag(takes_context=True)
def bundle_data_uri(context, path):
    """A bundle file as a data: URI, e.g. {% bundle_data_uri "logo.jpg" %}.

    For Chromium's header and footer templates, which cannot load files.
    Reads the bytes loaded with the bundle (the ones template_sha256 describes).
    """
    files = context.template.engine.bundle_files
    if path not in files:
        raise template.TemplateSyntaxError(f"{path} is not a file of the document template")
    mime = content_type(PurePosixPath(path).name)
    return f"data:{mime};base64,{base64.b64encode(files[path]).decode('ascii')}"
