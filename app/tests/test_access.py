"""AT-15: every page requires login (M1 spec §11)."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/projects/",
        "/projects/new/",
        "/projects/1/",
        "/projects/1/edit/",
        "/projects/1/defaults/",
        "/projects/1/tcn/new/",
        "/tcn/1/",
        "/tcn/1/preview/",
        "/tcn/1/issue/",
        "/tcn/1/document/",
        "/tcn/1/new-revision/",
        "/tcn/1/cancel/",
        "/tcn/1/delete/",
        "/accounts/password_change/",
        "/admin/auth/user/",
    ],
)
def test_anonymous_request_redirects_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login") + "?next=")


@pytest.mark.django_db
def test_anonymous_admin_redirects_to_admin_login(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


@pytest.mark.django_db
def test_login_page_is_public(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert b"Log in" in response.content


def test_login_then_home_shows_user(client, user):
    response = client.post(reverse("login"), {"username": "mgeerts", "password": "pw-for-tests-only"})
    assert response.status_code == 302
    assert response["Location"] == reverse("home")

    response = client.get(reverse("home"), follow=True)
    assert response.redirect_chain == [(reverse("projects:list"), 302)]
    assert b"Maria Geerts" in response.content
    assert b"Log out" in response.content


def test_wrong_password_is_rejected(client, user):
    response = client.post(reverse("login"), {"username": "mgeerts", "password": "wrong"})
    assert response.status_code == 200
    assert b"did not match" in response.content
    assert client.get(reverse("home")).status_code == 302


def test_logout_ends_session(client, user):
    client.force_login(user)
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert response["Location"] == reverse("login")
    assert client.get(reverse("home")).status_code == 302
