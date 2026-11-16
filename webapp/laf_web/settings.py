"""Configuración de la aplicación web.

La base local mantiene el estado del recorrido. Supabase es una fuente de datos
opcional y sus credenciales nunca se exponen al navegador.
"""
from pathlib import Path
import os
import sys

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BASE_DIR.parent

# Prioriza variables ya definidas por el entorno. Para desarrollo local admite
# tanto webapp/.env como el .env compartido por el pipeline de Python.
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(REPOSITORY_ROOT / ".env", override=False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "demo-local-no-usar-en-produccion")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "recommender",
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
]

ROOT_URLCONF = "laf_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "recommender" / "templates"],
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

WSGI_APPLICATION = "laf_web.wsgi.application"
ASGI_APPLICATION = "laf_web.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "recommender" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Despliegue detrás de un proxy con HTTPS (Railway, nginx). Orígenes con esquema,
# separados por coma: https://mi-app.up.railway.app
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if os.getenv("DJANGO_BEHIND_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DOMAIN_CONFIG_DIR = Path(
    os.getenv("DOMAIN_CONFIG_DIR", REPOSITORY_ROOT / "config" / "domains")
)
FIXTURE_DIR = BASE_DIR / "fixtures"
RECOMMENDATION_EVALUATOR = os.getenv(
    "RECOMMENDATION_EVALUATOR",
    "recommender.services.evaluators.LAF1PreparedRecommendationEvaluator",
)
LAF_API_URL = os.getenv("LAF_API_URL", "http://127.0.0.1:8088/api/graph").strip()
LAF_API_TIMEOUT_SECONDS = max(
    0.1,
    float(os.getenv("LAF_API_TIMEOUT_SECONDS", "30")),
)
LAF_API_RESULTS_VALIDATED = os.getenv("LAF_API_RESULTS_VALIDATED", "0") == "1"
LAF_PRODUCT_DECISION_MODEL = os.getenv(
    "LAF_PRODUCT_DECISION_MODEL",
    "post_laf_multicriteria_v1",
).strip()
GRAPH_VISIBLE_NODE_LIMIT = min(
    int(os.getenv("GRAPH_VISIBLE_NODE_LIMIT", "250")),
    250,
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
# Respaldo con el fixture de demostración (webapp/fixtures/<dominio>.json) cuando
# Supabase no está configurado o no responde. Sus valores son ilustrativos y no
# salen de laf-api, por eso queda apagado salvo que se pida con 1. Sin la variable,
# la portada informa que no se pudo conectar con la base de datos. La suite de
# tests lo habilita por defecto porque sus recorridos usan el fixture.
_RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"
ALLOW_DEMO_FIXTURE = (
    os.getenv("ALLOW_DEMO_FIXTURE", "1" if _RUNNING_TESTS else "0") == "1"
)
DATASET_KEY = os.getenv("DATASET_KEY", "cafe_top20_demo_2026")
QUALITY_ASPECT_CACHE_SECONDS = max(
    0,
    int(os.getenv("QUALITY_ASPECT_CACHE_SECONDS", "300")),
)

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# Logs a consola (gunicorn/Railway los muestran). Los fallos del evaluador LAF
# se registran con traceback desde recommender.services.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "recommender": {"level": "INFO"},
        "django.request": {"level": "WARNING"},
    },
}
