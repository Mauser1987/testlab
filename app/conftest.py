import pytest
from django.contrib.auth.models import User

from testlab.documents import pdf
from testlab.documents.tests.pdf_text import fake_docx_to_pdf


@pytest.fixture(autouse=True)
def pdf_conversion(request, monkeypatch):
    """Fast stand-in for LibreOffice, except in tests marked `libreoffice` (skipped if not installed)."""
    if request.node.get_closest_marker("libreoffice"):
        if not pdf.soffice_available():
            pytest.skip("LibreOffice (soffice) is not installed")
        return
    monkeypatch.setattr(pdf, "docx_to_pdf", fake_docx_to_pdf)


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
