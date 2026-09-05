from fixture_project import settings as original

globals().update({name: getattr(original, name) for name in dir(original) if name.isupper()})
INSTALLED_APPS = [a for a in original.INSTALLED_APPS if not a.startswith("rest_framework")]
ROOT_URLCONF = __name__
urlpatterns = []
MIDDLEWARE = []
