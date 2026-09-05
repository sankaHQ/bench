from typing import ClassVar

from django.urls import include, path
from rest_framework.routers import Route, SimpleRouter
from sales.views import AccountListView, SummaryView, TransactionViewSet


class TransactionRouter(SimpleRouter):
    routes: ClassVar[list[Route]] = [
        Route(
            url=r"^{prefix}{trailing_slash}$",
            mapping={"post": "create"},
            name="{basename}-list",
            detail=False,
            initkwargs={"suffix": "List"},
        ),
        Route(
            url=r"^{prefix}/{lookup}{trailing_slash}$",
            mapping={"patch": "partial_update", "delete": "destroy"},
            name="{basename}-detail",
            detail=True,
            initkwargs={"suffix": "Instance"},
        ),
    ]


router = TransactionRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("api/accounts/", AccountListView.as_view(), name="account-list"),
    path("api/summary/", SummaryView.as_view(), name="summary"),
    path("api/", include(router.urls)),
]
