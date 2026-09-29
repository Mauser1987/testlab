"""Registration, email login and administrator approval (stabilization decision S2)."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse

from testlab.accounts.forms import AWAITING_APPROVAL
from testlab.tcn.services import initials

pytestmark = pytest.mark.django_db

PASSWORD = "Wet-seal-2026!"


@pytest.fixture(autouse=True)
def corporate_domain(settings):
    settings.TESTLAB_ALLOWED_EMAIL_DOMAINS = ["example.com"]


def register(client, email="jane.doe@example.com", **overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": email,
        "password1": PASSWORD,
        "password2": PASSWORD,
        **overrides,
    }
    return client.post(reverse("register"), data)


def login(client, username, password=PASSWORD):
    return client.post(reverse("login"), {"username": username, "password": password})


def messages_text(response):
    return response.content.decode()


# --- Login | Register ----------------------------------------------------------------------


def test_login_and_register_link_to_each_other(client):
    login_page = client.get(reverse("login")).content.decode()
    assert "Email address" in login_page and reverse("register") in login_page
    register_page = client.get(reverse("register"))
    assert register_page.status_code == 200  # no login required
    content = register_page.content.decode()
    assert reverse("login") in content
    for field in ["first_name", "last_name", "email", "password1", "password2"]:
        assert f'name="{field}"' in content
    assert 'name="username"' not in content  # no username to invent


# --- Registration -------------------------------------------------------------------------------


def test_registration_creates_inactive_account(client):
    response = register(client, email="  Jane.Doe@Example.COM ")
    assert response.status_code == 302 and response["Location"] == reverse("login")
    user = User.objects.get()
    assert (user.username, user.email) == ("jane.doe@example.com", "jane.doe@example.com")
    assert (user.first_name, user.last_name) == ("Jane", "Doe")
    assert not user.is_active and not user.is_staff and not user.is_superuser
    assert user.check_password(PASSWORD)
    assert AWAITING_APPROVAL == "Your TestLab account has been created and is awaiting administrator approval."
    assert AWAITING_APPROVAL in client.get(response["Location"]).content.decode()


@pytest.mark.parametrize(
    "email",
    [
        "jane@gmail.com",
        "jane@notexample.com",
        "jane@sub.example.com",
        "jane@example.com.evil.org",
        "jane@example.co",
        "example.com@evil.org",
    ],
)
def test_external_email_rejected_and_no_account_created(client, email):
    response = register(client, email=email)
    assert response.status_code == 200
    assert "Only corporate email addresses (@example.com) can register. No account was created." in messages_text(
        response
    )
    assert not User.objects.exists()


@pytest.mark.parametrize("email", ["JANE@EXAMPLE.COM", "jane@Example.Com"])
def test_domain_case_does_not_matter(client, email):
    register(client, email=email)
    assert User.objects.get().email == "jane@example.com"


def test_several_domains_and_configured_case(client, settings):
    settings.TESTLAB_ALLOWED_EMAIL_DOMAINS = ["Example.COM", "@corp.example.org"]
    register(client, email="a@example.com")
    register(client, email="b@CORP.example.org")
    response = register(client, email="c@example.org")
    assert "(@example.com, @corp.example.org)" in messages_text(response)
    assert sorted(User.objects.values_list("email", flat=True)) == ["a@example.com", "b@corp.example.org"]


def test_registration_closed_without_configured_domains(client, settings):
    settings.TESTLAB_ALLOWED_EMAIL_DOMAINS = []
    content = client.get(reverse("register")).content.decode()
    assert "Registration is not open" in content and 'name="password1"' not in content
    response = register(client)
    assert response.status_code == 200 and not User.objects.exists()


def test_duplicate_email_rejected_in_any_case(client, user):
    user.email = "maria.geerts@example.com"
    user.save()
    response = register(client, email="Maria.Geerts@EXAMPLE.com")
    assert "An account with this email address already exists." in messages_text(response)
    register(client)
    response = register(client, email="JANE.DOE@example.com")
    assert "An account with this email address already exists." in messages_text(response)
    assert User.objects.count() == 2


def test_password_confirmation_and_strength(client):
    response = register(client, password2="Different-2026!")
    assert "The two passwords do not match." in messages_text(response)
    response = register(client, password1="12345678", password2="12345678")
    assert "This password is too common." in messages_text(response)
    response = register(client, first_name="Jacqueline", password1="Jacqueline1", password2="Jacqueline1")
    assert "too similar" in messages_text(response)
    assert not User.objects.exists()


def test_required_fields(client):
    response = register(client, first_name=" ", last_name="")
    assert response.status_code == 200 and not User.objects.exists()


# --- Login and approval ------------------------------------------------------------------------


def test_pending_account_cannot_log_in(client):
    register(client)
    response = login(client, "jane.doe@example.com")
    assert "Your TestLab account is awaiting administrator approval." in messages_text(response)
    assert "_auth_user_id" not in client.session
    response = login(client, "jane.doe@example.com", password="wrong")  # no hint without the password
    assert "did not match" in messages_text(response) and "awaiting" not in messages_text(response)


def test_admin_approval_then_login_with_email(client, django_user_model):
    register(client)
    admin = django_user_model.objects.create_superuser("admin", "admin@example.com", "admin-pw-2026")
    client.force_login(admin)
    changelist = reverse("admin:auth_user_changelist")
    pending = client.get(changelist + "?approval=pending").content.decode()
    assert "jane.doe@example.com" in pending and "admin@example.com" not in pending
    jane = User.objects.get(email="jane.doe@example.com")
    response = client.post(changelist, {"action": "approve", "_selected_action": [jane.pk]})
    assert response.status_code == 302
    jane.refresh_from_db()
    assert jane.is_active and not jane.is_staff

    client.logout()
    response = login(client, "Jane.Doe@EXAMPLE.com")  # case-insensitive
    assert response.status_code == 302 and client.session["_auth_user_id"] == str(jane.pk)
    assert initials(jane) == "JD"  # "Prepared by" default from the registered names


def test_admin_can_approve_on_the_user_page_too(client, django_user_model):
    register(client)
    jane = User.objects.get()
    jane.is_active = True  # what ticking "Active" in admin does
    jane.save()
    assert login(client, "jane.doe@example.com").status_code == 302


def test_deactivated_account_gets_its_own_message(client):
    register(client)
    jane = User.objects.get()
    jane.is_active = True
    jane.save()
    login(client, "jane.doe@example.com")
    client.logout()
    jane.refresh_from_db()
    jane.is_active = False
    jane.save()
    response = login(client, "jane.doe@example.com")
    assert "has been deactivated" in messages_text(response)


def test_non_admin_cannot_approve(client):
    register(client)
    register(client, email="john@example.com", first_name="John")
    john = User.objects.get(email="john@example.com")
    john.is_active = True
    john.save()
    client.force_login(john)
    assert client.get(reverse("admin:auth_user_changelist")).status_code == 302  # to the admin login
    assert not User.objects.get(email="jane.doe@example.com").is_active


# --- Bootstrap accounts ------------------------------------------------------------------------------


def test_bootstrap_superuser_logs_in_with_username_or_email(client, monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "bootstrap-pw-2026")
    call_command("createsuperuser", interactive=False, username="Mohammed", email="it.admin@example.com")
    assert login(client, "Mohammed", "bootstrap-pw-2026").status_code == 302
    client.logout()
    assert login(client, "IT.Admin@example.com", "bootstrap-pw-2026").status_code == 302


def test_ambiguous_email_logs_nobody_in(client, django_user_model):
    django_user_model.objects.create_user("one", "shared@example.com", PASSWORD)
    django_user_model.objects.create_user("two", "shared@example.com", PASSWORD)
    assert login(client, "shared@example.com").status_code == 200
    assert login(client, "one").status_code == 302  # the username still works


def test_logged_in_user_is_sent_home_from_register(client, user):
    client.force_login(user)
    assert client.get(reverse("register"))["Location"] == reverse("home")
