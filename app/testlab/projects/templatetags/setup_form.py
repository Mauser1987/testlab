from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def was(field, changes):
    """Marker "changed — was: …" for an input that differs from the source.

    `changes` maps input names to objects with an `old` display value (see
    tcn/diff.py). Without `changes` (e.g. on the project defaults page) the
    filter renders nothing. `field` is a bound form field or an input name.
    """
    if not changes:
        return ""
    change = changes.get(field if isinstance(field, str) else field.html_name)
    if change is None:
        return ""
    old = change.old or "(empty)"
    if "\n" in old:
        return format_html('<details class="was"><summary>changed — was:</summary><pre>{}</pre></details>', old)
    return format_html('<span class="was">changed — was: {}</span>', old)
