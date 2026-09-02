from metrics_project.settings import *  # noqa: F403

INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS  # noqa: F405
    if not app.startswith("rest_framework")
]
