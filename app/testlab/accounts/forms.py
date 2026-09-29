"""Registration and login forms (stabilization decision S2)."""

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from .backends import find_user

AWAITING_APPROVAL = "Your TestLab account has been created and is awaiting administrator approval."


def allowed_domains():
    """TESTLAB_ALLOWED_EMAIL_DOMAINS, normalised: lower-case, without a leading "@"."""
    domains = (domain.strip().lower().lstrip("@") for domain in settings.TESTLAB_ALLOWED_EMAIL_DOMAINS)
    return [domain for domain in domains if domain]


def registration_open():
    return bool(allowed_domains())


def email_domain_allowed(email):
    """Server-side domain check: exact domain match, case-insensitive."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return "@" in email and domain in allowed_domains()


class LoginForm(AuthenticationForm):
    """Login with the corporate email address (or a bootstrap username)."""

    username = forms.CharField(
        label="Email address",
        max_length=254,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "size": 30}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Your email address and password did not match. Please try again.",
        "awaiting_approval": "Your TestLab account is awaiting administrator approval.",
        "inactive": "Your TestLab account has been deactivated. Contact a TestLab administrator.",
    }

    def clean(self):
        try:
            return super().clean()
        except ValidationError:
            # Only someone who knows the password learns that the account is inactive.
            user = find_user(self.cleaned_data.get("username"))
            password = self.cleaned_data.get("password")
            if user is not None and not user.is_active and password and user.check_password(password):
                code = "awaiting_approval" if user.last_login is None else "inactive"
                raise ValidationError(self.error_messages[code], code=code) from None
            raise


class RegistrationForm(forms.Form):
    """Self-registration: the account is created inactive, for an administrator to approve."""

    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150)
    # 150: the email address is also the username (max. 150 characters).
    email = forms.EmailField(label="Corporate email address", max_length=150)
    password1 = forms.CharField(
        label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not registration_open():
            raise ValidationError("Registration is not open. Contact a TestLab administrator.")
        if not email_domain_allowed(email):
            domains = ", ".join(f"@{domain}" for domain in allowed_domains())
            raise ValidationError(
                f"Only corporate email addresses ({domains}) can register. No account was created."
            )
        users = get_user_model()._default_manager
        if users.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two passwords do not match.")
        elif password2:
            candidate = get_user_model()(
                username=cleaned.get("email", ""),
                email=cleaned.get("email", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password2, candidate)
            except ValidationError as error:
                self.add_error("password2", error)
        return cleaned

    def save(self):
        data = self.cleaned_data
        try:
            with transaction.atomic():
                return get_user_model()._default_manager.create_user(
                    username=data["email"],
                    email=data["email"],
                    password=data["password1"],
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    is_active=False,  # awaiting administrator approval
                )
        except IntegrityError:  # registered at the same moment by another request
            self.add_error("email", "An account with this email address already exists.")
            return None
