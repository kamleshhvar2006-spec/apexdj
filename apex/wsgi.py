"""WSGI entry point used by gunicorn on AppSail: apex.wsgi:application"""
import os
import sys
from pathlib import Path

vendor = Path(__file__).resolve().parent.parent / 'vendor'
if vendor.is_dir():
    sys.path.insert(0, str(vendor))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apex.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
