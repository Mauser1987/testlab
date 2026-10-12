import pytest
from django.contrib.auth.models import User

from testlab.documents import chromium
from testlab.documents.tests.pdf_text import fake_print_pdf


@pytest.fixture(scope="session")
def chromium_missing():
    return chromium.chromium_available()


@pytest.fixture(autouse=True)
def chromium_marker(request, monkeypatch):
    """Tests marked `chromium` print real PDFs with Playwright's Chromium (skipped when it is not installed);
    the others use a fast stand-in that keeps the rendered text (pdf_text.fake_print_pdf)."""
    if request.node.get_closest_marker("chromium"):
        reason = request.getfixturevalue("chromium_missing")
        if reason:
            pytest.skip(reason)
        return
    monkeypatch.setattr(chromium, "print_pdf", fake_print_pdf)


@pytest.fixture(autouse=True)
def file_storage(settings, tmp_path):
    """Tests never write into the development file store."""
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
    }
    return tmp_path


@pytest.fixture
def user(db):
    return User.objects.create_user(
        "mgeerts", password="pw-for-tests-only", first_name="Maria", last_name="Geerts"
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user("mtest", password="pw-for-tests-only", first_name="Mark", last_name="Test")
