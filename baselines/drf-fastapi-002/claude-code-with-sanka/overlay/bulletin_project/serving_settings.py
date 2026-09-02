"""Serving-only Django settings: same DB/config wiring as bulletin_project.settings,
but with every rest_framework app removed from INSTALLED_APPS so the FastAPI
serving process never depends on rest_framework being installed as a Django app."""

from bulletin_project.settings import *  # noqa: F401,F403

INSTALLED_APPS = [app for app in INSTALLED_APPS if not app.startswith("rest_framework")]
