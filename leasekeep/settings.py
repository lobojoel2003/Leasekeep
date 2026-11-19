"""Django settings for Leasekeep.

Everything that differs between installations is read from environment
variables; see ``.env.example`` for the full list. ``LEASEKEEP_ENV`` selects
sensible defaults:

* ``development`` (default): debug on, SQLite unless ``DATABASE_URL`` is set.
* ``production``: debug off, secure cookies, HTTPS, a real ``DJANGO_SECRET_KEY``
  is required. The Docker image sets this.
* ``test``: used by the test suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


LEASEKEEP_ENV = env("LEASEKEEP_ENV", "development").lower()
if LEASEKEEP_ENV not in {"development", "production", "test"}:
    raise ImproperlyConfigured("LEASEKEEP_ENV must be development, production or test.")
PRODUCTION = LEASEKEEP_ENV == "production"
TESTING = LEASEKEEP_ENV == "test"

DEBUG = env_bool("DJANGO_DEBUG", LEASEKEEP_ENV == "development")

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if PRODUCTION:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when LEASEKEEP_ENV=production.")
    SECRET_KEY = "leasekeep-insecure-development-key-do-not-use-in-production"  # noqa: S105

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "" if PRODUCTION else "localhost,127.0.0.1,[::1],testserver")
# The container health check calls /healthz on localhost.
ALLOWED_HOSTS += [h for h in ("localhost", "127.0.0.1") if h not in ALLOWED_HOSTS]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "leasekeep.core",
    "leasekeep.formulas",
    "leasekeep.homes",
    "leasekeep.billing",
    "leasekeep.portal",
    "leasekeep.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves collected static files in production; runserver handles them in development.
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if PRODUCTION else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "leasekeep.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PACKAGE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "leasekeep.core.context_processors.leasekeep",
            ],
        },
    },
]

WSGI_APPLICATION = "leasekeep.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DATABASE_CONN_MAX_AGE", 600),
        conn_health_checks=True,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

AUTHENTICATION_BACKENDS = ["leasekeep.core.backends.EmailOrUsernameBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("LEASEKEEP_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [PACKAGE_DIR / "static"]
STATIC_ROOT = Path(env("LEASEKEEP_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("LEASEKEEP_MEDIA_ROOT", str(BASE_DIR / "media")))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
LEASEKEEP_MAX_UPLOAD_MB = env_int("LEASEKEEP_MAX_UPLOAD_MB", 10)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if PRODUCTION
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

# --- Email -----------------------------------------------------------------
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if PRODUCTION
    else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Leasekeep <no-reply@localhost>")
LEASEKEEP_STAFF_NOTIFICATION_EMAIL = env("LEASEKEEP_STAFF_NOTIFICATION_EMAIL")

# --- Payments --------------------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")
STRIPE_PAYMENT_METHOD_TYPES = env_list("STRIPE_PAYMENT_METHOD_TYPES", "us_bank_account,card")
LEASEKEEP_CURRENCY = env("LEASEKEEP_CURRENCY", "usd").lower()

# --- Security --------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = env_int("LEASEKEEP_SESSION_AGE_SECONDS", 60 * 60 * 12)
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
    if not SECURE_HSTS_PRELOAD:
        # Preloading is a deliberate, hard-to-undo choice left to each operator.
        SILENCED_SYSTEM_CHECKS = ["security.W021"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LEASEKEEP_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
