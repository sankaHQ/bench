from typing import ClassVar

from django.urls import include, path
from orders.views import OrderViewSet
from rest_framework.routers import DynamicRoute, Route, SimpleRouter


class OrderRouter(SimpleRouter):
    routes: ClassVar[list[Route | DynamicRoute]] = [
        Route(
            url=r"^{prefix}{trailing_slash}$",
            mapping={"get": "list", "post": "create"},
            name="{basename}-list",
            detail=False,
            initkwargs={"suffix": "List"},
        ),
        Route(
            url=r"^{prefix}/{lookup}{trailing_slash}$",
            mapping={"get": "retrieve", "patch": "partial_update"},
            name="{basename}-detail",
            detail=True,
            initkwargs={"suffix": "Instance"},
        ),
        DynamicRoute(
            url=r"^{prefix}/{lookup}/{url_path}{trailing_slash}$",
            name="{basename}-{url_name}",
            detail=True,
            initkwargs={},
        ),
    ]


router = OrderRouter()
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [path("api/", include(router.urls))]
