"""Serving settings: the original settings without any DRF application.

The retained Django half keeps auth, contenttypes, and the posts app; the
token table remains in the database and is read through an unmanaged mirror.
"""

from bulletin_project.settings import *  # noqa: F403

INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS  # noqa: F405
    if not app.startswith("rest_framework")
]
