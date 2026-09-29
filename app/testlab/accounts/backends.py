"""Login with the corporate email address (stabilization decision S2).

Django's standard User model is kept. A self-registered user gets the
normalised (lower-case) email address as username as well as email, so the
username never has to be invented or remembered, and the unique username
column also makes the email address unique for these accounts. Accounts
made by createsuperuser or in admin may have another username; they can
log in with it or with their email address.

Corporate SSO (Entra ID/LDAP) can later be added as another authentication
backend, or replace this one, without changes to the TCN domain model: the
domain only refers to users through foreign keys.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


def find_user(identifier):
    """The one user with this email address or username; None when none or ambiguous."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    users = get_user_model()._default_manager
    if "@" in identifier:
        matches = users.filter(Q(email__iexact=identifier) | Q(username__iexact=identifier))
    else:
        matches = users.filter(username=identifier)
    matches = list(matches.distinct()[:2])
    return matches[0] if len(matches) == 1 else None


class EmailOrUsernameBackend(ModelBackend):
    """ModelBackend that also accepts the email address (case-insensitive) as login name.

    Inactive accounts (awaiting approval, or deactivated) cannot log in.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None
        user = find_user(username)
        if user is None:
            # Same work as for an existing user, so response times reveal nothing.
            get_user_model()().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
