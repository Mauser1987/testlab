"""TestLab settings, driven by TESTLAB_* environment variables.

Development defaults: DEBUG on, SQLite file in <repo>/data/.
Production: set TESTLAB_DEBUG=0, TESTLAB_SECRET_KEY, TESTLAB_ALLOWED_HOSTS
and TESTLAB_DATABASE_URL (PostgreSQL). SQLite is for development/tests only.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

APP_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = APP_DIR.parent


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


DEBUG = env_bool("TESTLAB_DEBUG", True)

SECRET_KEY = os.environ.get("TESTLAB_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("TESTLAB_SECRET_KEY must be set when TESTLAB_DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key"

ALLOWED_HOSTS = env_list("TESTLAB_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "testlab",
    "testlab.accounts",
    "testlab.projects",
    "testlab.tcn",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page requires login unless the view is marked login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATA_DIR = Path(os.environ.get("TESTLAB_DATA_DIR", REPO_DIR / "data"))

DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("TESTLAB_DATABASE_URL", f"sqlite:///{DATA_DIR / 'testlab.sqlite3'}"),
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Normal users log in with their corporate email address; the username of
# a bootstrap account made with createsuperuser also works (accounts/backends.py).
AUTHENTICATION_BACKENDS = ["testlab.accounts.backends.EmailOrUsernameBackend"]

# Self-registration (stabilization decision S2): only these email domains may
# register, e.g. TESTLAB_ALLOWED_EMAIL_DOMAINS=example.com,example.org. Empty:
# registration is closed. New accounts are inactive until an administrator
# activates them in Django admin.
TESTLAB_ALLOWED_EMAIL_DOMAINS = [
    domain.lower().lstrip("@") for domain in env_list("TESTLAB_ALLOWED_EMAIL_DOMAINS", [])
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = os.environ.get("TESTLAB_TIME_ZONE", "Europe/Amsterdam")
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("TESTLAB_STATIC_ROOT", REPO_DIR / "staticfiles")

# Server-side file storage: issued documents under projects/<project_no>/…
# (M1 spec §9.4). Development default inside the git-ignored data directory.
TESTLAB_FILE_ROOT = Path(os.environ.get("TESTLAB_FILE_ROOT", DATA_DIR / "files"))
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": TESTLAB_FILE_ROOT},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Word templates of generated documents (M1 spec §9.1).
TESTLAB_TEMPLATE_DIR = Path(os.environ.get("TESTLAB_TEMPLATE_DIR", APP_DIR / "doc_templates"))

# PDF conversion with LibreOffice headless (documents/pdf.py). TESTLAB_SOFFICE:
# path of soffice (soffice.com on Windows); empty = look on PATH and in the
# usual install locations. TESTLAB_PDF_TIMEOUT: seconds per conversion.
TESTLAB_SOFFICE = os.environ.get("TESTLAB_SOFFICE", "")
TESTLAB_PDF_TIMEOUT = int(os.environ.get("TESTLAB_PDF_TIMEOUT", "120"))

# Usual project-number format. A mismatch only gives a warning (M1 spec V1).
TESTLAB_PROJECT_NO_PATTERN = os.environ.get("TESTLAB_PROJECT_NO_PATTERN", r"^\d{4}RSD\d{2}TL$")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
