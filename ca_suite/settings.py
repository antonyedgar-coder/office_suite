from pathlib import Path
import os
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

_csrf_origins = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

if os.getenv("DJANGO_BEHIND_HTTPS_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "masters",
    "reports",
    "mis",
    "dirkyc",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.ActivityLogMiddleware",
    "core.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.InactiveUserMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ca_suite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "ca_suite.wsgi.application"


def _db():
    """
    Prefer DATABASE_URL (postgres:// or postgresql://).
    Fall back to PG* / POSTGRES_* env vars (common when linking Managed Postgres on App Platform).
    Otherwise SQLite for local dev when nothing is configured.
    """
    original = (os.getenv("DATABASE_URL") or "").strip()

    def _from_pg_env() -> dict | None:
        host = (
            (os.getenv("PGHOST") or os.getenv("POSTGRES_HOST") or os.getenv("DATABASE_HOST") or "")
            .strip()
        )
        if not host:
            return None
        name = (
            (os.getenv("PGDATABASE") or os.getenv("POSTGRES_DATABASE") or os.getenv("POSTGRES_DB") or "postgres")
            .strip()
        )
        user = ((os.getenv("PGUSER") or os.getenv("POSTGRES_USER") or "postgres")).strip()
        password = (os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD") or "").strip()
        port = (os.getenv("PGPORT") or os.getenv("POSTGRES_PORT") or "5432").strip()
        cfg: dict = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": user,
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
        }
        sslmode = (os.getenv("PGSSLMODE") or os.getenv("POSTGRES_SSLMODE") or "").strip().lower()
        if sslmode in ("require", "verify-ca", "verify-full"):
            cfg["OPTIONS"] = {"sslmode": sslmode}
        return cfg

    # DigitalOcean App Platform: DATABASE_URL may show as ${production-database.DATABASE_URL}
    # until the database is attached to the app. Django cannot expand that — fix it in DO.
    if original.startswith("${") and "}" in original:
        pg = _from_pg_env()
        if pg:
            return pg
        raise RuntimeError(
            "DATABASE_URL is still a DigitalOcean placeholder (e.g. ${production-database.DATABASE_URL}). "
            "The real connection string was never injected. In DigitalOcean: open your App → "
            "Resources / Components and add this Postgres cluster as a Database for this app "
            "(or delete DATABASE_URL and use Add resource → Database → Existing database). "
            "Alternatively, replace DATABASE_URL with the full postgresql://… URI from "
            "Databases → your cluster → Connection details (copy as single line)."
        )

    raw_url = original
    if not raw_url or raw_url in ("None", "null", "undefined"):
        raw_url = ""

    url = raw_url if raw_url.startswith(("postgres://", "postgresql://")) else ""

    if not url:
        pg = _from_pg_env()
        if pg:
            return pg
        if raw_url:
            raise RuntimeError(
                "DATABASE_URL is set but must start with postgres:// or postgresql:// "
                "(copy the full URI from DigitalOcean → Databases → your cluster → Connection details). "
                "Or remove DATABASE_URL and link the database so PGHOST/PGDATABASE are set."
            )
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}

    normalized = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(normalized)
    name = (parsed.path or "").lstrip("/") or "postgres"
    user = parsed.username or "postgres"
    password = parsed.password or ""
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    cfg: dict = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
    }
    q = parse_qs(parsed.query)
    sslmode = (q.get("sslmode") or [""])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        cfg["OPTIONS"] = {"sslmode": sslmode}
    return cfg


DATABASES = {"default": _db()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Email: use console in development (password appears in terminal). Set SMTP in production.
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.getenv("DJANGO_DEFAULT_FROM_EMAIL", "CA Office Suite <noreply@localhost>")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"

