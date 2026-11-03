"""Django settings for Miday.

Values come from environment variables, which default to the project's
``.env`` file, with development fallbacks. Anything machine-specific can also
go in ``local_settings.py`` next to this file, which is imported last.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path):
    """Read KEY=VALUE lines into os.environ without overriding real variables.

    Lets manage.py, run.sh and PythonAnywhere's WSGI file share one config.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    values = {}  # later lines win, as when a shell sources the file
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    for key, value in values.items():
        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / ".env")


def env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# SECURITY WARNING: development fallback only — run.sh writes a real key to .env.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-3k1q8m2v7c5x9z4w6t0r",
)
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in .env: the built-in key is public. run.sh creates one.")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "picker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "picker.middleware.VoterMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

# SQLite is shared by gunicorn's threads: IMMEDIATE transactions take the write
# lock up front, so a read-then-write inside atomic() waits instead of failing
# with "database is locked".
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            # WAL lets reads continue during a write, but needs a local disk;
            # set SQLITE_WAL=0 on network storage such as PythonAnywhere's.
            "init_command": (
                "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
                if env_bool("SQLITE_WAL", True) else "PRAGMA journal_mode=DELETE;"
            ),
        },
    }
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "picker"},
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Riyadh")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Not the manifest storage: the vendored Bootstrap files reference source maps
# that are not shipped, which the manifest post-processing refuses.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Served over plain HTTP on the LAN: cookies must not be marked Secure, or the
# browser drops them and every POST fails the CSRF check.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
# Browsers ignore (and warn about) this header on plain-HTTP origins.
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # Scanners probing with other Host headers; Django already answers 400.
        "django.security.DisallowedHost": {"handlers": [], "propagate": False},
    },
}

# --- Miday ---------------------------------------------------

# The address colleagues use to reach this machine; share links are built from
# it. run.sh fills it from the LAN IP when .env leaves it blank.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
# Behind an HTTPS proxy (PythonAnywhere, a tunnel) Django sees plain HTTP, so
# the browser's https:// Origin must be trusted explicitly for POSTs to pass.
if PUBLIC_BASE_URL:
    _public = urlsplit(PUBLIC_BASE_URL)
    CSRF_TRUSTED_ORIGINS = [f"{_public.scheme}://{_public.netloc}".lower()]  # browsers send lower case

# How often an open voting page checks for new votes.
LIVE_REFRESH_SECONDS = max(2, env_int("LIVE_REFRESH_SECONDS", 4))

# Official Places API (New). Enable "Places API (New)" and "Maps Grounding Lite"
# for the key's project.
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
# Unofficial lookup through the public Google Maps page; used when there is no
# key or the official lookup fails. Set GMAPS_KEYLESS=0 to turn it off.
GMAPS_KEYLESS = env_bool("GMAPS_KEYLESS", True)
# Upper bound on billable Place Details calls per day (1,000/month are free).
GMAPS_DAILY_DETAILS_CAP = env_int("GMAPS_DAILY_DETAILS_CAP", 50)
GMAPS_LANGUAGE = os.environ.get("GMAPS_LANGUAGE", "en")
GMAPS_REGION = os.environ.get("GMAPS_REGION", "SA")

try:
    from .local_settings import *  # noqa: F401,F403
except ImportError:
    pass
