import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY and "collectstatic" not in sys.argv:
    raise RuntimeError("Добавьте секрет Django в .env")
DEBUG = False
ALLOWED_HOSTS = []
for value in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(","):
    if value.strip():
        ALLOWED_HOSTS.append(value.strip())
CSRF_TRUSTED_ORIGINS = []
for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(","):
    if value.strip():
        CSRF_TRUSTED_ORIGINS.append(value.strip())
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "bot.apps.BotConfig",
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
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASE_FILE = BASE_DIR / "data" / "navi.sqlite3"
if "migrate" in sys.argv:
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
elif not DATABASE_FILE.is_file():
    raise RuntimeError("Не найдена готовая база data/navi.sqlite3")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": DATABASE_FILE,
    "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "data" / "files"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_PROXY_URL = os.getenv("OPENAI_PROXY_URL", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
try:
    public_address = urlsplit(PUBLIC_BASE_URL)
    public_port = public_address.port
except Exception:
    raise RuntimeError("Укажите правильный PUBLIC_BASE_URL в .env") from None
if public_port == 0:
    raise RuntimeError("Укажите правильный порт в PUBLIC_BASE_URL")
if not public_address.hostname or public_address.username is not None or public_address.password is not None:
    raise RuntimeError("Укажите адрес без логина и пароля в PUBLIC_BASE_URL")
if public_address.path or public_address.query or public_address.fragment:
    raise RuntimeError("PUBLIC_BASE_URL должен быть адресом без пути и параметров")
LOCAL_HTTP = False
if public_address.scheme == "http" and public_address.hostname in ("localhost", "127.0.0.1", "::1"):
    LOCAL_HTTP = True
    for host in ALLOWED_HOSTS:
        if host not in ("localhost", "127.0.0.1", "[::1]"):
            raise RuntimeError("Для HTTP разрешены только localhost и локальные IP в DJANGO_ALLOWED_HOSTS")
elif public_address.scheme != "https":
    raise RuntimeError("Для внешнего адреса PUBLIC_BASE_URL нужен HTTPS")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not LOCAL_HTTP
CSRF_COOKIE_SECURE = not LOCAL_HTTP
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = not LOCAL_HTTP
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
if LOCAL_HTTP:
    SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
