from django.urls import include, path
from rest_framework.routers import DefaultRouter
from widgets.views import WidgetViewSet

router = DefaultRouter()
router.register("widgets", WidgetViewSet, basename="widget")

urlpatterns = [path("api/", include(router.urls))]
