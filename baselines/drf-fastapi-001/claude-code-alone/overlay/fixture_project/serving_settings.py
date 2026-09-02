"""Django settings used by the FastAPI serving process (target_app.py).

This module reuses fixture_project.settings verbatim (including the
BENCH_DB_PATH database wiring) but strips rest_framework out of
INSTALLED_APPS so the serving process's app registry never loads DRF or
any Django request-serving machinery. Django is kept around for the ORM
only.
"""
from __future__ import annotations

from fixture_project.settings import *  # noqa: F401,F403
from fixture_project.settings import INSTALLED_APPS as _BASE_INSTALLED_APPS

INSTALLED_APPS = [app for app in _BASE_INSTALLED_APPS if app != "rest_framework"]
