import pytest
from django.contrib.auth.models import User


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
