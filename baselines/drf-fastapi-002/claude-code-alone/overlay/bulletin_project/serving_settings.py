"""Django settings used by the FastAPI serving process (target_app.py).

Reuses bulletin_project.settings (and therefore the BENCH_DB_PATH database
mechanism) unchanged, but strips every rest_framework app out of
INSTALLED_APPS so the serving process never needs djangorestframework
installed at request-serving time. Django is kept around for the ORM only.
"""
from __future__ import annotations

from bulletin_project.settings import *  # noqa: F401,F403
from bulletin_project.settings import INSTALLED_APPS as _BASE_INSTALLED_APPS

INSTALLED_APPS = [
    app
    for app in _BASE_INSTALLED_APPS
    if app != "rest_framework" and not app.startswith("rest_framework.")
]
