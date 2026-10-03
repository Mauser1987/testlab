from decimal import Decimal

from django import template

from testlab.tcn.services import initials as name_initials

register = template.Library()


@register.filter
def get(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def reading(value):
    """A stored reading as entered: 70.0500 → 70.05, 420.0000 → 420."""
    if value is None or value == "":
        return ""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text
    return value


@register.filter
def initials(user):
    """Who entered a reading: initials of the logged-in user, else the user name."""
    return name_initials(user) or user.get_username()
