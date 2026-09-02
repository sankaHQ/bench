"""Serving settings: the original settings without the DRF request layer.

The ledger app is installed through a plain AppConfig so the source signal
receivers are never connected in the serving process; the native request
layer owns every side effect explicitly.
"""

from ledger_project.settings import *  # noqa: F403

INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS  # noqa: F405
    if not app.startswith("rest_framework")
]
INSTALLED_APPS = [
    "target_ledger_config.PlainLedgerConfig" if app == "ledger" else app for app in INSTALLED_APPS
]
