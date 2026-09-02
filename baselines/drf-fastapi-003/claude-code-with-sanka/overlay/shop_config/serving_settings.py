"""Settings used to serve the app without djangorestframework.

Reuses shop_config.settings (and its BENCH_DB_PATH-driven DATABASES
mechanism) unchanged, only pruning rest_framework from INSTALLED_APPS so the
serving process never needs it installed.
"""

from shop_config.settings import *  # noqa: F401,F403
from shop_config.settings import INSTALLED_APPS as _INSTALLED_APPS

INSTALLED_APPS = [app for app in _INSTALLED_APPS if app != "rest_framework"]
