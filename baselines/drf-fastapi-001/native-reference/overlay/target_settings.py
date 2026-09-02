"""Serving settings for the native FastAPI request layer.

The serving process keeps Django for the ORM only, so DRF must not be loaded
into it. The original settings stay untouched for the retained Django test
suite, which still exercises the source DRF application.
"""

from fixture_project.settings import *  # noqa: F403

INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS  # noqa: F405
    if app != "rest_framework"
]
