from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, Prefetch, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from sales.models import Account, Transaction
from sales.pagination import AccountPagination
from sales.serializers import (
    AccountMetricSerializer,
    SummarySerializer,
    TransactionSerializer,
)

MONEY_FIELD = DecimalField(max_digits=12, decimal_places=2)
ORDERING_FIELDS = {
    "code",
    "name",
    "posted_total",
    "transaction_count",
    "pending_count",
}


def account_metrics() -> QuerySet[Account]:
    return Account.objects.annotate(
        transaction_count=Count("transactions"),
        pending_count=Count(
            "transactions",
            filter=Q(transactions__state=Transaction.State.PENDING),
        ),
        posted_total=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__state=Transaction.State.POSTED),
            ),
            Value(Decimal("0.00")),
            output_field=MONEY_FIELD,
        ),
    ).prefetch_related(
        Prefetch(
            "transactions",
            queryset=Transaction.objects.order_by("-id"),
            to_attr="computed_transactions",
        )
    )


class AccountListView(ListAPIView):
    serializer_class = AccountMetricSerializer
    pagination_class = AccountPagination

    def get_queryset(self) -> QuerySet[Account]:
        ordering = self.request.query_params.get("ordering", "-posted_total")
        if ordering.removeprefix("-") not in ORDERING_FIELDS:
            raise ValidationError({"ordering": [f'Unsupported ordering field "{ordering}".']})
        tie_breaker = "id" if ordering.removeprefix("-") == "code" else "code"
        return account_metrics().order_by(ordering, tie_breaker)


class SummaryView(APIView):
    def get(self, request: Request) -> Response:
        groups = list(
            Account.objects.values("region")
            .annotate(
                account_count=Count("id", distinct=True),
                transaction_count=Count("transactions"),
                posted_total=Coalesce(
                    Sum(
                        "transactions__amount",
                        filter=Q(transactions__state=Transaction.State.POSTED),
                    ),
                    Value(Decimal("0.00")),
                    output_field=MONEY_FIELD,
                ),
            )
            .order_by("region")
        )
        grand_total = Transaction.objects.filter(state=Transaction.State.POSTED).aggregate(
            total=Coalesce(
                Sum("amount"),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            )
        )["total"]
        serializer = SummarySerializer({"groups": groups, "grand_total": grand_total})
        return Response(serializer.data)


class TransactionViewSet(ModelViewSet):
    queryset = Transaction.objects.select_related("account").all()
    serializer_class = TransactionSerializer
