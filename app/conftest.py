import pytest
from django.contrib.auth.models import User

from testlab.documents import chromium, pdf, pdf_word
from testlab.documents.tests.pdf_text import fake_docx_to_pdf


@pytest.fixture(autouse=True)
def tcn_renderer(settings):
    """Tests use the HTML renderer whatever TESTLAB_TCN_RENDERER says; docx tests set it themselves."""
    settings.TESTLAB_TCN_RENDERER = "html"


@pytest.fixture(scope="session")
def chromium_missing():
    return chromium.chromium_available()


@pytest.fixture(autouse=True)
def chromium_marker(request):
    """Tests marked `chromium` print real PDFs with Playwright's Chromium; skipped when it is not installed."""
    if request.node.get_closest_marker("chromium"):
        reason = request.getfixturevalue("chromium_missing")
        if reason:
            pytest.skip(reason)


@pytest.fixture(autouse=True)
def pdf_conversion(request, monkeypatch):
    """Fast stand-in for the docx renderer's PDF conversion, except in tests marked `libreoffice` or `word`
    (skipped if not installed). The HTML renderer (the default) always renders real PDFs."""
    if request.node.get_closest_marker("libreoffice"):
        if not pdf.soffice_available():
            pytest.skip("LibreOffice (soffice) is not installed")
        request.getfixturevalue("settings").TESTLAB_PDF_CONVERTER = "libreoffice"
        return
    if request.node.get_closest_marker("word"):
        if not pdf_word.word_available():
            pytest.skip("Microsoft Word with pywin32 is not available (Windows only)")
        request.getfixturevalue("settings").TESTLAB_PDF_CONVERTER = "word"
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
