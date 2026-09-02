"""Serving settings for the FastAPI process.

Reuses shop_config.settings (and its BENCH_DB_PATH-driven DATABASES
configuration) unchanged, but strips every rest_framework app so the
serving process never loads Django REST Framework.
"""
from __future__ import annotations

from shop_config.settings import *  # noqa: F401,F403

INSTALLED_APPS = [app for app in INSTALLED_APPS if not app.startswith("rest_framework")]  # noqa: F405
