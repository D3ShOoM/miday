# PythonAnywhere WSGI file for Miday.
# Paste this into the WSGI configuration file linked from the Web tab.
# Settings are read from __APP_DIR__/.env by config/settings.py.
import os
import sys

APP_DIR = "__APP_DIR__"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
