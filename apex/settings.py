"""Settings for the APEX Logistics API.

There is no database and no sessions: shipments live in the Catalyst Data Store, and admins use a signed token
sent in the X-Apex-Token header (not a cookie), so Django's auth, session and CSRF apps are intentionally absent.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default):
    raw = os.environ.get(name)
    return [v.strip() for v in raw.split(',') if v.strip()] if raw else default


DEBUG = os.environ.get('DJANGO_DEBUG', '') == '1'

# Django needs a SECRET_KEY, but nothing here depends on it staying the same between restarts.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SESSION_SECRET') or secrets.token_urlsafe(50)

# AppSail URLs look like  <service>-<ZAID>.development.catalystappsail.<tld>. Add yours in ALLOWED_HOSTS if it differs.
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', [
    '.catalystappsail.com', '.catalystappsail.in', '.catalystappsail.eu', 'localhost', '127.0.0.1',
])

# Only needed if the website is hosted somewhere else (e.g. Catalyst Web Client Hosting). Empty = same-origin only.
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', [])

INSTALLED_APPS = ['logistics']

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'logistics.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'apex.urls'
WSGI_APPLICATION = 'apex.wsgi.application'
DATABASES = {}
APPEND_SLASH = False
USE_I18N = False
USE_TZ = True
TIME_ZONE = 'UTC'
DATA_UPLOAD_MAX_MEMORY_SIZE = 20_000
FRONTEND_FILE = BASE_DIR / 'frontend' / 'index.html'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
}
