"""Django settings for the PlateMates backend.

Every value that differs between deployments (local Mac, Raspberry Pi, cloud VM) comes from the
environment, loaded from a gitignored `.env` at the repository root. Nothing here is specific to a
team or to an LLM provider.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env", override=False)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or ("insecure-dev-only-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Traefik terminates HTTPS (for devices on the home network) and says so in this header; the
# backend port itself is published on 127.0.0.1 only, so the header cannot be forged from outside.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "mozilla_django_oidc",
    "apps.accounts",
    "apps.catalog",
    "apps.recipes",
    "apps.teams",
    "apps.menus",
    "apps.assistant",
    "apps.siteconfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

# PostgreSQL is the only supported database: the schema relies on ArrayField and pgvector.
DATABASES = {
    "default": dj_database_url.config(
        default="postgres://platemates:platemates@localhost:5432/platemates",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Two caches, read in turn by `apps.core.cache.CacheManager`: each process's memory first
# (seconds, so a change made elsewhere shows up soon), then Redis, shared by every process.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "TIMEOUT": int(os.getenv("CACHE_REDIS_TIMEOUT_SECONDS", str(12 * 3600))),
        "KEY_PREFIX": "platemates",
    },
    "local": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "platemates-local",
        "TIMEOUT": int(os.getenv("CACHE_MEMORY_TIMEOUT_SECONDS", "10")),
    },
}

# Italian by default; English available. The SPA has its own translations (frontend/src/i18n);
# these cover the admin, choice labels and API error messages. Per-request language comes from
# the Accept-Language header via LocaleMiddleware.
LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "it")
LANGUAGES = [("it", "Italiano"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Europe/Rome")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # The SPA is same-origin and authenticated by the Django session that the OIDC login opens.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# -- Authentication: Keycloak via OIDC ------------------------------------------------------------
# Keycloak authenticates (email/password, Google, Microsoft, Apple); Django is its OIDC client and
# turns a successful login into an ordinary session. See apps/accounts and docs/architecture.md.
# ModelBackend stays for local superusers (`createsuperuser`), e.g. to reach the admin when
# Keycloak is down.

AUTHENTICATION_BACKENDS = [
    "apps.accounts.oidc.KeycloakBackend",
    "django.contrib.auth.backends.ModelBackend",
]

KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "platemates")
# Browsers reach Keycloak under /auth on the app's own origin (Traefik or the Vite proxy forward
# it), so the endpoints they are sent to are relative paths: login works from whatever address
# the app was opened at (localhost, the LAN name or IP). The backend calls Keycloak directly on
# the internal URL (a container hostname under Docker Compose).
KEYCLOAK_PATH = "/auth"
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", "http://localhost:8180/auth").rstrip("/")
_oidc_browser = f"{KEYCLOAK_PATH}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"
_oidc_internal = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"

OIDC_RP_CLIENT_ID = os.getenv("OIDC_RP_CLIENT_ID", "platemates-backend")
OIDC_RP_CLIENT_SECRET = os.getenv("OIDC_RP_CLIENT_SECRET", "")
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid email profile"
OIDC_USE_PKCE = True
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc_browser}/auth"
OIDC_OP_LOGOUT_ENDPOINT = f"{_oidc_browser}/logout"
OIDC_OP_TOKEN_ENDPOINT = f"{_oidc_internal}/token"
OIDC_OP_USER_ENDPOINT = f"{_oidc_internal}/userinfo"
OIDC_OP_JWKS_ENDPOINT = f"{_oidc_internal}/certs"
OIDC_AUTHENTICATE_CLASS = "apps.accounts.oidc.KeycloakAuthenticationRequestView"
OIDC_OP_LOGOUT_URL_METHOD = "apps.accounts.oidc.keycloak_logout_url"
# Kept server-side in the session, only as `id_token_hint` for logout.
OIDC_STORE_ID_TOKEN = True
OIDC_TIMEOUT = 15
LOGIN_URL = "/oidc/authenticate/"
LOGIN_REDIRECT_URL = "/"
LOGIN_REDIRECT_URL_FAILURE = "/?login=failed"
LOGOUT_REDIRECT_URL = "/"

# Which social providers are configured, in the order the login screen shows them. The same
# variables configure Keycloak through `manage.py setup_keycloak`.
KEYCLOAK_IDENTITY_PROVIDERS = {
    "google": bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET")),
    "microsoft": bool(os.getenv("MICROSOFT_CLIENT_ID") and os.getenv("MICROSOFT_CLIENT_SECRET")),
    "apple": bool(
        os.getenv("APPLE_CLIENT_ID")
        and os.getenv("APPLE_TEAM_ID")
        and os.getenv("APPLE_KEY_ID")
        and os.getenv("APPLE_PRIVATE_KEY_FILE")
    ),
}

# -- AI components --------------------------------------------------------------------------------
# Both the generative model and the embedding model are external services reached through an
# OpenAI-compatible API. Swapping provider means changing these variables, never the code.
# See `ai/` and docs/architecture.md.

AI = {
    "CHAT": {
        # "unsloth_studio" adds Studio-specific behaviour (model-loaded checks, thinking toggle) on
        # top of the plain "openai_compatible" protocol.
        "PROVIDER": os.getenv("LLM_PROVIDER", "unsloth_studio"),
        "BASE_URL": os.getenv("LLM_BASE_URL", "http://127.0.0.1:8888").rstrip("/"),
        "API_KEY": os.getenv("LLM_API_KEY") or None,
        "MODEL": os.getenv("LLM_MODEL", "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"),
        # Model that reads photos. Defaults to the chat model: no swap in Studio, and in a
        # comparison on recipe photos (2026-10-06) Qwen3.6 transcribed faithfully where
        # gemma-4-E2B misread and reordered words.
        "VISION_MODEL": os.getenv("LLM_VISION_MODEL")
        or os.getenv("LLM_MODEL", "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"),
        "TIMEOUT_SECONDS": float(os.getenv("LLM_TIMEOUT_SECONDS", "300")),
    },
    "EMBEDDINGS": {
        "PROVIDER": os.getenv("EMBEDDINGS_PROVIDER", "openai_compatible"),
        "BASE_URL": os.getenv("EMBEDDINGS_BASE_URL", "http://127.0.0.1:8100").rstrip("/"),
        "API_KEY": os.getenv("EMBEDDINGS_API_KEY") or None,
        "MODEL": os.getenv(
            "EMBEDDINGS_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ),
        "TIMEOUT_SECONDS": float(os.getenv("EMBEDDINGS_TIMEOUT_SECONDS", "60")),
    },
}
