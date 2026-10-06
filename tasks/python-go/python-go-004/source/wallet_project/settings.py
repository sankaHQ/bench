import os

SECRET_KEY = "synthetic-wallet-fixture"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
INSTALLED_APPS = ["django.contrib.contenttypes", "rest_framework", "wallets"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("BENCH_DB_PATH", ":memory:"),
    }
}
MIDDLEWARE = []
ROOT_URLCONF = "wallet_project.urls"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = True
REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
